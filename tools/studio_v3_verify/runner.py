from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Mapping, Sequence

from .gates import (
    GateResult,
    GateStatus,
    check_architecture,
    check_banned_surfaces,
    check_generated_client,
    check_performance_contract,
    check_toolchain,
    validate_canonical_vectors,
)


PACKAGE_ROOT = Path(__file__).resolve().parent
DEFAULT_REPO_ROOT = PACKAGE_ROOT.parents[1]


def load_config(path: Path = PACKAGE_ROOT / "config.json") -> dict[str, object]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if value.get("schema_version") != 1:
        raise ValueError(f"unsupported verify config schema: {value.get('schema_version')!r}")
    return value


def resolve_profile(
    requested: str,
    repo_root: Path,
    config: Mapping[str, object],
) -> str:
    if requested != "auto":
        return requested
    legacy_paths = [repo_root / str(path) for path in config["cutover_absent_paths"]]
    return "phase0" if any(path.exists() for path in legacy_paths) else "cutover"


def git_safe_environment(
    repo_root: Path,
    base: Mapping[str, str] | None = None,
) -> dict[str, str]:
    env = dict(os.environ if base is None else base)
    count = int(env.get("GIT_CONFIG_COUNT", "0"))
    env[f"GIT_CONFIG_KEY_{count}"] = "safe.directory"
    # Git for Windows compares the protected repository against slash-normalized
    # paths. Backslash values supplied through GIT_CONFIG_* do not satisfy the
    # dubious-ownership check.
    env[f"GIT_CONFIG_VALUE_{count}"] = repo_root.resolve().as_posix()
    env["GIT_CONFIG_COUNT"] = str(count + 1)
    return env


def verification_environment(repo_root: Path) -> dict[str, str]:
    env = git_safe_environment(repo_root)
    source = str(repo_root / "common" / "dlstudio" / "src")
    current = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = os.pathsep.join(
        part for part in (str(repo_root), source, current) if part
    )
    env["PYTHONUTF8"] = "1"
    env["PYTHONDONTWRITEBYTECODE"] = "1"
    env["PIP_DISABLE_PIP_VERSION_CHECK"] = "1"
    return env


def _process(
    command: Sequence[str],
    cwd: Path,
    env: Mapping[str, str] | None = None,
) -> int:
    return subprocess.run(list(command), cwd=cwd, env=env, check=False).returncode


def _external_result(name: str, command: Sequence[str], returncode: int) -> GateResult:
    details = () if returncode == 0 else (f"{' '.join(command)} exited {returncode}",)
    return GateResult(
        name=name,
        status=GateStatus.PASS if returncode == 0 else GateStatus.FAIL,
        details=details,
    )


def run(
    *,
    repo_root: Path,
    profile: str,
    scope: str,
    skip_toolchain: bool,
) -> list[GateResult]:
    config = load_config()
    resolved_profile = resolve_profile(profile, repo_root, config)
    cutover = resolved_profile == "cutover"
    source_root = repo_root / "common" / "dlstudio" / "src" / "dlstudio"
    vector_root = repo_root / "common" / "dlstudio" / "tests" / "v3_gates" / "vectors"
    webui_root = repo_root / "common" / "dlstudio" / "webui"
    env = verification_environment(repo_root)
    results: list[GateResult] = []

    if skip_toolchain:
        results.append(
            GateResult(
                name="locked-toolchain",
                status=GateStatus.SKIP,
                details=("explicitly skipped",),
            )
        )
    else:
        results.append(check_toolchain(config["toolchain"]))
    results.extend(
        [
            check_architecture(source_root, config),
            check_banned_surfaces(source_root, repo_root, config, cutover=cutover),
            validate_canonical_vectors(vector_root),
            check_performance_contract(config["performance_hooks"]),
        ]
    )
    if scope == "static" or any(result.status is GateStatus.FAIL for result in results):
        return results

    pytest_target = (
        repo_root / "common" / "dlstudio" / "tests"
        if scope == "full"
        else repo_root / "common" / "dlstudio" / "tests" / "v3_gates"
    )
    temp_parent = repo_root / ".test-tmp"
    temp_parent.mkdir(parents=True, exist_ok=True)
    pytest_temp = Path(tempfile.mkdtemp(prefix="studio-v3-verify-", dir=temp_parent))
    pytest_command = [
        sys.executable,
        "-m",
        "pytest",
        str(pytest_target),
        "-q",
        "--basetemp",
        str(pytest_temp / "pytest"),
    ]
    try:
        pytest_rc = _process(pytest_command, repo_root, env)
    finally:
        if pytest_temp.is_dir() and pytest_temp.parent.resolve() == temp_parent.resolve():
            shutil.rmtree(pytest_temp)
    results.append(_external_result("python-tests", pytest_command, pytest_rc))
    if pytest_rc:
        return results

    generated = check_generated_client(
        repo_root,
        webui_root,
        strict=cutover,
        env=env,
    )
    results.append(generated)
    if generated.status is GateStatus.FAIL:
        return results

    npm = "npm.cmd" if os.name == "nt" else "npm"
    for name, command in (
        ("webui-tests", [npm, "test"]),
        ("webui-build", [npm, "run", "build"]),
    ):
        returncode = _process(command, webui_root, env)
        results.append(_external_result(name, command, returncode))
        if returncode:
            break
    return results


def _print_results(results: Sequence[GateResult], *, as_json: bool) -> None:
    if as_json:
        print(
            json.dumps(
                [
                    {
                        "name": result.name,
                        "status": result.status.value,
                        "details": list(result.details),
                        "metrics": dict(result.metrics),
                    }
                    for result in results
                ],
                indent=2,
                sort_keys=True,
            )
        )
        return
    for result in results:
        print(f"[{result.status.value.upper():4}] {result.name}")
        for detail in result.details:
            print(f"       {detail}")
        if result.metrics:
            metrics = ", ".join(f"{key}={value}" for key, value in result.metrics.items())
            print(f"       {metrics}")


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m tools.studio_v3_verify",
        description="Run the Studio v3 architecture, trust, portability, and test gates.",
    )
    parser.add_argument(
        "--profile",
        choices=("auto", "phase0", "cutover"),
        default="auto",
        help="auto is phase0 while known legacy paths exist, otherwise strict cutover",
    )
    parser.add_argument(
        "--scope",
        choices=("static", "gates", "full"),
        default="full",
        help="static checks only, focused v3 tests, or the complete dlstudio suite",
    )
    parser.add_argument(
        "--skip-toolchain",
        action="store_true",
        help="diagnostic only: skip local Python/Node version check",
    )
    parser.add_argument("--json", action="store_true", help="emit machine-readable results")
    parser.add_argument(
        "--repo-root",
        type=Path,
        default=DEFAULT_REPO_ROOT,
        help=argparse.SUPPRESS,
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    repo_root = args.repo_root.resolve()
    results = run(
        repo_root=repo_root,
        profile=args.profile,
        scope=args.scope,
        skip_toolchain=args.skip_toolchain,
    )
    _print_results(results, as_json=args.json)
    return 1 if any(result.status is GateStatus.FAIL for result in results) else 0
