"""cli/verify.py -- `dl2 verify --changed [--full]`, the owner-domain
verification facade (pattern from game-67-idle's `ai_studio` verify command).

The idea: map every changed path to the domain that OWNS it, then run only
that domain's test files, instead of the full 377+-test suite on every
one-line change. Ownership discipline is the point, not speed alone: a path
under `common/dlstudio/src/dlstudio/` that maps to no known domain is a HARD
ERROR (exit 2), never a silent skip -- either the domain table below is
missing an entry (fix it) or the caller should fall back to `--full`.

Domain table (source-relative to common/dlstudio/src/dlstudio/):

    model/ | ir.py      -> test_cache, test_compile_*, test_raster_*,
                            test_render_* (IR/model is a shared contract;
                            a change there has the widest blast radius)
    compile/ | check/   -> test_compile_*, test_check, test_e2e
    render/raster/      -> test_raster_*
    render/ (else)      -> test_render_*, test_assemble_mix, test_graph,
                            test_e2e
    cache/              -> test_cache
    cli/                -> test_cli, test_verify_cmd
    api/                -> test_api
    services/           -> test_services_*

Outside the src/dlstudio/ tree:
    common/dlstudio/tests/x.py     -> itself
    common/dlstudio/webui/**       -> `npm run build` in webui/ if a `npm`
                                       executable is on PATH, else warn-skip
                                       (never a hard failure -- node is an
                                       optional local toolchain, not part of
                                       the Python test suite)
    docs/**, common/quality/**,
    .claude/agents/*.md, any *.md  -> no tests; reported as "docs-only"
    anything else under
    common/dlstudio/ (e.g. pyproject.toml)
                                    -> conservatively treated as a wide-blast
                                       "model_ir"-domain change (packaging/dep
                                       changes can affect anything) -- NOT
                                       the ownership-discipline exit-2 case,
                                       which is reserved for src/dlstudio/
    anything outside common/dlstudio entirely
                                    -> ignored, with a note (this facade only
                                       owns the dlstudio package)
"""
from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

PACKAGE_ROOT = "common/dlstudio"
SRC_ROOT = f"{PACKAGE_ROOT}/src/dlstudio"
TESTS_ROOT = f"{PACKAGE_ROOT}/tests"
WEBUI_ROOT = f"{PACKAGE_ROOT}/webui"

# domain -> pytest file-stem patterns (globbed against tests/*.py, no
# extension). Order within a tuple doesn't matter; order of the SRC prefix
# table below does (most specific prefix first).
DOMAIN_TESTS: dict[str, tuple[str, ...]] = {
    "model_ir": ("test_cache", "test_compile_*", "test_raster_*", "test_render_*"),
    "compile_check": ("test_compile_*", "test_check", "test_e2e"),
    "render_raster": ("test_raster_*",),
    "render": ("test_render_*", "test_assemble_mix", "test_graph", "test_e2e"),
    "cache": ("test_cache",),
    "cli": ("test_cli", "test_verify_cmd"),
    "api": ("test_api",),
    "services": ("test_services_*",),
}

# Ordered longest/most-specific-prefix-first: render/raster/ MUST be checked
# before the bare render/ prefix, or every raster change would incorrectly
# widen to the full render/ domain.
_SRC_PREFIX_DOMAINS: tuple[tuple[str, str], ...] = (
    ("render/raster/", "render_raster"),
    ("render/", "render"),
    ("model/", "model_ir"),
    ("ir.py", "model_ir"),
    ("compile/", "compile_check"),
    ("check/", "compile_check"),
    ("cache/", "cache"),
    ("cli/", "cli"),
    ("api/", "api"),
    ("services/", "services"),
)


class VerifyError(Exception):
    """Raised for an unmapped path under common/dlstudio/src/dlstudio --
    ownership discipline: fix DOMAIN_TESTS/_SRC_PREFIX_DOMAINS or pass
    --full, never silently skip a source change."""


@dataclass(frozen=True)
class Classification:
    path: str
    kind: str  # "domain" | "test_self" | "webui" | "docs" | "ignored" | "unmapped"
    domain: str | None = None
    tests: tuple[str, ...] = field(default_factory=tuple)


def classify_path(path: str) -> Classification:
    """Map one changed path (repo-root-relative, forward or back slashes)
    to the domain that owns it. Never raises -- "unmapped" is a normal
    Classification value; cmd_verify decides what to do with it (exit 2)."""
    norm = path.replace("\\", "/").strip()

    if norm.endswith(".md") or norm.startswith("common/quality/"):
        return Classification(path=norm, kind="docs")

    if norm.startswith(f"{TESTS_ROOT}/") and norm.endswith(".py"):
        stem = Path(norm).stem
        return Classification(path=norm, kind="test_self", tests=(stem,))

    if norm.startswith(f"{WEBUI_ROOT}/"):
        return Classification(path=norm, kind="webui")

    if norm.startswith(f"{SRC_ROOT}/"):
        rel = norm[len(SRC_ROOT) + 1:]
        for prefix, domain in _SRC_PREFIX_DOMAINS:
            if rel == prefix.rstrip("/") or rel.startswith(prefix):
                return Classification(path=norm, kind="domain", domain=domain, tests=DOMAIN_TESTS[domain])
        return Classification(path=norm, kind="unmapped")

    if norm.startswith(f"{PACKAGE_ROOT}/"):
        # Under common/dlstudio/ but outside src/dlstudio, tests/, webui/
        # (e.g. pyproject.toml) -- a packaging/dependency change, treated
        # conservatively as the widest-blast domain rather than guessed
        # narrower. Deliberately NOT the exit-2 case (that's reserved for
        # unmapped paths under src/dlstudio specifically).
        return Classification(path=norm, kind="domain", domain="model_ir", tests=DOMAIN_TESTS["model_ir"])

    return Classification(path=norm, kind="ignored")


# ─── git status (NUL-safe) ─────────────────────────────────────────────────

def git_repo_root(start: Path | None = None) -> Path:
    result = subprocess.run(
        ["git", "rev-parse", "--show-toplevel"],
        cwd=(start or Path.cwd()),
        capture_output=True, text=True, check=True,
    )
    return Path(result.stdout.strip())


def git_status_paths(repo_root: Path) -> list[str]:
    """`git status --porcelain=v1 -z`, parsed from the NUL-delimited form
    (not the human `->` rename-arrow text form) so filenames containing
    spaces, quotes, or non-ASCII characters can never be misparsed. Rename/
    copy entries (status starting with R/C) carry an extra NUL-terminated
    "original path" token after the new path -- we only care about the new
    path (what the working tree looks like now), so that extra token is
    consumed and discarded.
    """
    result = subprocess.run(
        ["git", "status", "--porcelain=v1", "-z"],
        cwd=repo_root, capture_output=True, text=True, check=True,
    )
    tokens = result.stdout.split("\0")
    paths: list[str] = []
    i = 0
    while i < len(tokens):
        entry = tokens[i]
        i += 1
        if not entry:
            continue
        status, path = entry[:2], entry[3:]
        paths.append(path)
        if status[0] in ("R", "C"):
            i += 1  # skip the original-path token
    return paths


# ─── test file resolution + pytest invocation ─────────────────────────────

def resolve_test_files(patterns: set[str], tests_dir: Path) -> list[str]:
    """Expand domain test-stem patterns (e.g. "test_compile_*") against the
    real tests/ directory, returning sorted, de-duplicated paths relative to
    the dlstudio package root (e.g. "tests/test_compile_mix.py")."""
    found: set[str] = set()
    for pattern in patterns:
        for hit in sorted(tests_dir.glob(f"{pattern}.py")):
            found.add(f"tests/{hit.name}")
    return sorted(found)


def run_pytest(file_args: list[str], *, cwd: Path) -> subprocess.CompletedProcess:
    """Seam for tests: invokes pytest as a SUBPROCESS (sys.executable -m
    pytest ...), never in-process -- `dl2 verify` running the suite that
    contains dl2 verify's own tests must not recurse into the current
    interpreter's pytest session. Tests monkeypatch this function directly
    to assert on the collected file list without paying for a real (nested)
    pytest run."""
    cmd = [sys.executable, "-m", "pytest", *file_args, "-q"]
    return subprocess.run(cmd, cwd=cwd)


def run_webui_build(webui_dir: Path) -> int | None:
    """`npm run build` in webui/ if `npm` is on PATH; returns the exit code,
    or None (with a printed warning) if npm isn't available -- a missing
    node toolchain is a warn-skip, never a hard verify failure."""
    npm = shutil.which("npm")
    if not npm:
        print("[dl2 verify] warn: npm not found on PATH -- skipping webui build")
        return None
    result = subprocess.run([npm, "run", "build"], cwd=webui_dir)
    return result.returncode


# ─── command ────────────────────────────────────────────────────────────

def cmd_verify(args: argparse.Namespace) -> int:
    repo_root = git_repo_root()
    dlstudio_dir = repo_root / "common" / "dlstudio"
    tests_dir = dlstudio_dir / "tests"

    if args.full:
        print("[dl2 verify] --full: running the entire suite")
        result = run_pytest(["tests"], cwd=dlstudio_dir)
        return result.returncode

    if not args.changed:
        print("[dl2 verify] error: pass --changed or --full", file=sys.stderr)
        return 1

    changed = git_status_paths(repo_root)
    if not changed:
        print("[dl2 verify] no changed paths (working tree clean)")
        return 0

    classifications = [classify_path(p) for p in changed]

    unmapped = [c for c in classifications if c.kind == "unmapped"]
    if unmapped:
        for c in unmapped:
            print(f"[dl2 verify] error: unmapped path under src/dlstudio: {c.path}", file=sys.stderr)
        print(
            "[dl2 verify] ownership discipline: add this path to the domain "
            "table in cli/verify.py, or run `dl2 verify --full`.",
            file=sys.stderr,
        )
        return 2

    docs = [c for c in classifications if c.kind == "docs"]
    ignored = [c for c in classifications if c.kind == "ignored"]
    webui = [c for c in classifications if c.kind == "webui"]
    domain_hits = [c for c in classifications if c.kind in ("domain", "test_self")]

    print(f"[dl2 verify] {len(changed)} changed path(s):")
    for c in classifications:
        label = c.domain or c.kind
        print(f"[dl2 verify]   {label:<14} {c.path}")

    for c in ignored:
        print(f"[dl2 verify] note: {c.path} is outside common/dlstudio -- ignored")

    patterns: set[str] = set()
    for c in domain_hits:
        patterns.update(c.tests)

    webui_rc: int | None = None
    if webui:
        print(f"[dl2 verify] webui/ changed ({len(webui)} path(s)) -- building")
        webui_rc = run_webui_build(dlstudio_dir / "webui")

    if not patterns:
        if webui:
            print("[dl2 verify] docs-only + webui: no Python tests to run")
            return webui_rc or 0
        print("[dl2 verify] docs-only: no tests to run")
        return 0

    files = resolve_test_files(patterns, tests_dir)
    if not files:
        print("[dl2 verify] domain matched but no test files found on disk (stale domain table?)")
        return webui_rc or 0

    print(f"[dl2 verify] running {len(files)} test file(s): {', '.join(files)}")
    result = run_pytest(files, cwd=dlstudio_dir)
    return result.returncode or (webui_rc or 0)


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "verify",
        help="map changed paths to owning domain(s) and run only their tests",
    )
    p.add_argument("--changed", action="store_true", help="verify only domains touched by uncommitted changes")
    p.add_argument("--full", action="store_true", help="run the entire test suite, ignoring --changed")
    p.set_defaults(func=cmd_verify)
