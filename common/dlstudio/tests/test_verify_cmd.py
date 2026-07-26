"""Tests for dlstudio.cli.verify -- `dl2 verify --changed [--full]`, the
owner-domain verification facade.

Three independent seams are monkeypatched separately so each concern is
testable in isolation without ever spawning a real (nested) pytest process:
  - `verify.git_repo_root`   -- which repo root to operate from
  - `verify.git_status_paths` -- which paths are "changed"
  - `verify.run_pytest`      -- the actual subprocess invocation

`REPO_ROOT` is fetched once via the REAL `git_repo_root()` (a cheap `git
rev-parse --show-toplevel` call) -- tests that need a real tests/ directory
to glob real test files against (the "services domain resolves real files"
tests) point at the actual repo, since that's the only tests/ directory
that's guaranteed to exist and be current.
"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

import pytest

from dlstudio import cli
from dlstudio.cli import verify

REPO_ROOT = verify.git_repo_root()
DLSTUDIO_DIR = REPO_ROOT / "common" / "dlstudio"


def _ns(*, changed=False, full=False):
    return argparse.Namespace(changed=changed, full=full)


# ─── classify_path: domain table ───────────────────────────────────────

@pytest.mark.parametrize("path,expected_domain", [
    ("common/dlstudio/src/dlstudio/compile/timeline.py", "compile_check"),
    ("common/dlstudio/src/dlstudio/check/__init__.py", "compile_check"),
    ("common/dlstudio/src/dlstudio/render/raster/_content.py", "render_raster"),
    ("common/dlstudio/src/dlstudio/render/raster/__init__.py", "render_raster"),
    ("common/dlstudio/src/dlstudio/render/beat.py", "render"),
    ("common/dlstudio/src/dlstudio/render/assemble.py", "render"),
    ("common/dlstudio/src/dlstudio/render/graph.py", "render"),
    ("common/dlstudio/src/dlstudio/cache/__init__.py", "cache"),
    ("common/dlstudio/src/dlstudio/cli/__init__.py", "cli"),
    ("common/dlstudio/src/dlstudio/cli/verify.py", "cli"),
    ("common/dlstudio/src/dlstudio/api/__init__.py", "api"),
    ("common/dlstudio/src/dlstudio/services/stock.py", "services"),
    ("common/dlstudio/src/dlstudio/services/publish.py", "services"),
])
def test_classify_path_domain_table(path, expected_domain):
    c = verify.classify_path(path)
    assert c.kind == "domain"
    assert c.domain == expected_domain
    assert c.tests == verify.DOMAIN_TESTS[expected_domain]


def test_classify_path_render_raster_wins_over_bare_render_prefix():
    c = verify.classify_path("common/dlstudio/src/dlstudio/render/raster/_util.py")
    assert c.domain == "render_raster"
    assert c.tests == verify.DOMAIN_TESTS["render_raster"]


# ─── F9: render_raster domain also covers beat compositing + full e2e ──

def test_render_raster_domain_includes_render_beat_and_e2e():
    assert verify.DOMAIN_TESTS["render_raster"] == ("test_raster_*", "test_render_beat", "test_e2e")


# ─── F4: compile_check domain also covers render tests (check.verify_output) ──

def test_compile_check_domain_includes_render_and_assemble_mix_tests():
    assert verify.DOMAIN_TESTS["compile_check"] == (
        "test_compile_*", "test_check", "test_e2e", "test_render_*", "test_assemble_mix",
    )


def test_classify_path_check_dir_pulls_in_render_tests():
    c = verify.classify_path("common/dlstudio/src/dlstudio/check/__init__.py")
    assert c.domain == "compile_check"
    assert "test_render_*" in c.tests
    assert "test_assemble_mix" in c.tests


# ─── F1: model/ | ir.py is a shared contract -> the FULL suite, not a ──
# ─── fixed (and inevitably under-inclusive) test-stem list           ──

@pytest.mark.parametrize("path", [
    "common/dlstudio/src/dlstudio/model/edit.py",
    "common/dlstudio/src/dlstudio/model/content.py",
    "common/dlstudio/src/dlstudio/ir.py",
])
def test_classify_path_model_ir_triggers_full_suite(path):
    c = verify.classify_path(path)
    assert c.kind == "full_suite"
    assert c.domain == "model_ir"
    assert c.tests == verify.FULL_SUITE_TESTS == ("tests",)


def test_classify_path_test_self_maps_to_its_own_stem():
    c = verify.classify_path("common/dlstudio/tests/test_cli.py")
    assert c.kind == "test_self"
    assert c.tests == ("test_cli",)


# ─── F2: tests/*.py that ISN'T test_*.py (conftest, _builders, future ──
# ─── helpers) has no single owning test file -> the FULL suite        ──

@pytest.mark.parametrize("path", [
    "common/dlstudio/tests/conftest.py",
    "common/dlstudio/tests/_builders.py",
])
def test_classify_path_test_helper_files_trigger_full_suite(path):
    c = verify.classify_path(path)
    assert c.kind == "full_suite"
    assert c.tests == verify.FULL_SUITE_TESTS


# ─── F8: non-.py files under tests/ (fixtures, golden images) -> the ──
# ─── FULL suite too -- they're consumed across raster/e2e tests       ──

@pytest.mark.parametrize("path", [
    "common/dlstudio/tests/fixtures/words_basic.json",
    "common/dlstudio/tests/golden/plate_plain.png",
])
def test_classify_path_non_py_test_assets_trigger_full_suite(path):
    c = verify.classify_path(path)
    assert c.kind == "full_suite"
    assert c.tests == verify.FULL_SUITE_TESTS


def test_classify_path_webui():
    c = verify.classify_path("common/dlstudio/webui/src/App.tsx")
    assert c.kind == "webui"


@pytest.mark.parametrize("path", [
    "docs/ARCHITECTURE_V2.md",
    "common/quality/VQ-SYNC.md",
    "common/quality/README.md",
    ".claude/agents/video-reviewer.md",
    "AGENTS.md",
    "common/README.md",
    "common/PIPELINE.md",
])
def test_classify_path_docs_only(path):
    assert verify.classify_path(path).kind == "docs"


def test_classify_path_unmapped_src_path_under_dlstudio():
    c = verify.classify_path("common/dlstudio/src/dlstudio/newthing/module.py")
    assert c.kind == "unmapped"


def test_classify_path_production_contract_runs_full_suite():
    c = verify.classify_path("common/dlstudio/src/dlstudio/production.py")
    assert c.kind == "full_suite"
    assert c.domain == "model_ir"
    assert c.tests == verify.FULL_SUITE_TESTS


def test_classify_path_bare_package_init_is_unmapped():
    c = verify.classify_path("common/dlstudio/src/dlstudio/__init__.py")
    assert c.kind == "unmapped"


def test_classify_path_dlstudio_root_config_is_wide_domain_not_exit2():
    """pyproject.toml lives under common/dlstudio/ but NOT under src/dlstudio
    -- the ownership-discipline exit-2 rule is scoped to src/dlstudio only,
    so this must resolve to a (conservative, wide) full-suite change, not
    "unmapped"."""
    c = verify.classify_path("common/dlstudio/pyproject.toml")
    assert c.kind == "full_suite"
    assert c.domain == "model_ir"
    assert c.tests == verify.FULL_SUITE_TESTS


@pytest.mark.parametrize("path", [
    "trolley/edits/reel_30k/beats.py",
    "neotolis_diary/data/reels/live_capture/take1.mp4",
    "common/devlog/stock.py",
    "common/devlog/cli.py",
])
def test_classify_path_outside_package_is_ignored(path):
    assert verify.classify_path(path).kind == "ignored"


def test_classify_path_normalizes_backslashes():
    c = verify.classify_path("common\\dlstudio\\src\\dlstudio\\cache\\__init__.py")
    assert c.kind == "domain" and c.domain == "cache"


# ─── git_status_paths: NUL-safe parsing ────────────────────────────────

def _fake_git_run(stdout: str):
    def fake_run(cmd, cwd, capture_output, text, check, encoding=None, errors=None):
        return subprocess.CompletedProcess(cmd, 0, stdout=stdout, stderr="")
    return fake_run


def test_git_status_paths_parses_simple_entries(monkeypatch):
    stdout = (
        "M  common/dlstudio/src/dlstudio/cli/__init__.py\0"
        "?? common/dlstudio/tests/test_verify_cmd.py\0"
    )
    monkeypatch.setattr(verify.subprocess, "run", _fake_git_run(stdout))
    paths = verify.git_status_paths(Path("."))
    assert paths == [
        "common/dlstudio/src/dlstudio/cli/__init__.py",
        "common/dlstudio/tests/test_verify_cmd.py",
    ]


def test_git_status_paths_skips_rename_original_path_token(monkeypatch):
    # Rename: two NUL-terminated tokens -- new path, then original path.
    stdout = (
        "R  common/dlstudio/src/dlstudio/cache/new_name.py\0"
        "common/dlstudio/src/dlstudio/cache/old_name.py\0"
    )
    monkeypatch.setattr(verify.subprocess, "run", _fake_git_run(stdout))
    paths = verify.git_status_paths(Path("."))
    assert paths == ["common/dlstudio/src/dlstudio/cache/new_name.py"]


def test_git_status_paths_handles_filename_with_space(monkeypatch):
    stdout = "?? common/dlstudio/tests/fixture with space.py\0"
    monkeypatch.setattr(verify.subprocess, "run", _fake_git_run(stdout))
    paths = verify.git_status_paths(Path("."))
    assert paths == ["common/dlstudio/tests/fixture with space.py"]


def test_git_status_paths_empty_when_clean(monkeypatch):
    monkeypatch.setattr(verify.subprocess, "run", _fake_git_run(""))
    assert verify.git_status_paths(Path(".")) == []


# ─── F11: git status subprocess call is decode-safe (never raises on ──
# ─── a non-UTF-8 filename) ──────────────────────────────────────────

def test_git_status_paths_passes_utf8_replace_encoding(monkeypatch):
    captured = {}

    def fake_run(cmd, cwd, capture_output, text, check, encoding=None, errors=None):
        captured["encoding"] = encoding
        captured["errors"] = errors
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr(verify.subprocess, "run", fake_run)
    verify.git_status_paths(Path("."))
    assert captured["encoding"] == "utf-8"
    assert captured["errors"] == "replace"


# ─── resolve_test_files ─────────────────────────────────────────────────

def test_resolve_test_files_expands_and_dedups(tmp_path):
    for name in ["test_compile_mix.py", "test_compile_probe.py", "test_check.py", "test_e2e.py"]:
        (tmp_path / name).write_text("", encoding="utf-8")
    files = verify.resolve_test_files({"test_compile_*", "test_check", "test_e2e"}, tmp_path)
    assert files == [
        "tests/test_check.py",
        "tests/test_compile_mix.py",
        "tests/test_compile_probe.py",
        "tests/test_e2e.py",
    ]


def test_resolve_test_files_missing_pattern_yields_nothing(tmp_path):
    assert verify.resolve_test_files({"test_totally_nonexistent_*"}, tmp_path) == []


def test_run_pytest_uses_repository_local_unique_basetemp(monkeypatch, tmp_path):
    captured = {}

    class _FixedUuid:
        hex = "fixed"

    monkeypatch.setattr(verify.uuid, "uuid4", lambda: _FixedUuid())

    def fake_run(cmd, cwd):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(verify.subprocess, "run", fake_run)
    result = verify.run_pytest(["tests/test_cli.py"], cwd=tmp_path)

    assert result.returncode == 0
    assert captured["cwd"] == tmp_path
    basetemp_index = captured["cmd"].index("--basetemp") + 1
    assert Path(captured["cmd"][basetemp_index]) == tmp_path / "tmp" / "verify" / "pytest-fixed"
    assert (tmp_path / "tmp" / "verify").is_dir()


def test_resolve_test_files_against_the_real_tests_dir_finds_new_phase4_files():
    """Sanity check against the real tests/ directory this suite lives in:
    proves test_services_stock.py / test_services_publish.py / this very
    file are discoverable the same way `dl2 verify` would find them."""
    files = verify.resolve_test_files({"test_services_*", "test_cli", "test_verify_cmd"}, DLSTUDIO_DIR / "tests")
    assert "tests/test_services_stock.py" in files
    assert "tests/test_services_publish.py" in files
    assert "tests/test_cli.py" in files
    assert "tests/test_verify_cmd.py" in files


# ─── cmd_verify: --full passthrough ─────────────────────────────────────

def test_cmd_verify_full_passthrough_runs_whole_suite(monkeypatch):
    captured = {}

    def fake_run_pytest(files, *, cwd):
        captured["files"] = files
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(["pytest", *files], 0)

    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(verify, "run_pytest", fake_run_pytest)

    code = verify.cmd_verify(_ns(full=True))
    assert code == 0
    assert captured["files"] == ["tests"]
    assert captured["cwd"] == DLSTUDIO_DIR


def test_cmd_verify_full_ignores_changed_flag(monkeypatch):
    """--full wins even if --changed is also set -- it's a full passthrough,
    not a merge of the two modes."""
    calls = {"git_status_paths": 0}

    def spy_git_status_paths(root):
        calls["git_status_paths"] += 1
        return []

    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(verify, "git_status_paths", spy_git_status_paths)
    monkeypatch.setattr(verify, "run_pytest", lambda files, *, cwd: subprocess.CompletedProcess(["pytest"], 0))

    code = verify.cmd_verify(_ns(changed=True, full=True))
    assert code == 0
    assert calls["git_status_paths"] == 0  # never consulted under --full


def test_cmd_verify_full_propagates_nonzero_exit(monkeypatch):
    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(verify, "run_pytest", lambda files, *, cwd: subprocess.CompletedProcess(["pytest"], 1))
    assert verify.cmd_verify(_ns(full=True)) == 1


# ─── cmd_verify: neither flag ───────────────────────────────────────────

def test_cmd_verify_neither_flag_errors(capsys):
    code = verify.cmd_verify(_ns())
    assert code == 1
    assert "--changed or --full" in capsys.readouterr().err


# ─── cmd_verify: --changed ───────────────────────────────────────────────

def _no_pytest_allowed(*_a, **_k):
    raise AssertionError("run_pytest must not be called")


def test_cmd_verify_changed_no_changes_is_clean_exit(monkeypatch, capsys):
    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(verify, "git_status_paths", lambda root: [])
    monkeypatch.setattr(verify, "run_pytest", _no_pytest_allowed)

    code = verify.cmd_verify(_ns(changed=True))
    assert code == 0
    assert "no changed paths" in capsys.readouterr().out


def test_cmd_verify_changed_unmapped_path_exits_2(monkeypatch, capsys):
    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: ["common/dlstudio/src/dlstudio/newthing/module.py"],
    )
    monkeypatch.setattr(verify, "run_pytest", _no_pytest_allowed)

    code = verify.cmd_verify(_ns(changed=True))
    assert code == 2
    err = capsys.readouterr().err
    assert "unmapped path" in err
    assert "newthing/module.py" in err


def test_cmd_verify_changed_unmapped_short_circuits_before_running_anything(monkeypatch):
    """One unmapped path must fail the whole run even if other changed paths
    map cleanly -- ownership discipline is all-or-nothing, not best-effort."""
    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: [
            "common/dlstudio/src/dlstudio/cache/__init__.py",
            "common/dlstudio/src/dlstudio/newthing/module.py",
        ],
    )
    monkeypatch.setattr(verify, "run_pytest", _no_pytest_allowed)
    assert verify.cmd_verify(_ns(changed=True)) == 2


def test_cmd_verify_changed_docs_only_reports_and_skips_tests(monkeypatch, capsys):
    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: ["docs/ARCHITECTURE_V2.md", "AGENTS.md", "common/quality/VQ-SYNC.md"],
    )
    monkeypatch.setattr(verify, "run_pytest", _no_pytest_allowed)

    code = verify.cmd_verify(_ns(changed=True))
    assert code == 0
    assert "docs-only" in capsys.readouterr().out


def test_cmd_verify_changed_outside_package_is_ignored_with_note(monkeypatch, capsys):
    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: ["trolley/edits/reel_30k/beats.py"],
    )
    monkeypatch.setattr(verify, "run_pytest", _no_pytest_allowed)

    code = verify.cmd_verify(_ns(changed=True))
    assert code == 0
    out = capsys.readouterr().out
    assert "ignored" in out


def test_cmd_verify_changed_services_domain_runs_resolved_real_files(monkeypatch):
    captured = {}

    def fake_run_pytest(files, *, cwd):
        captured["files"] = files
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(["pytest", *files], 0)

    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: ["common/dlstudio/src/dlstudio/services/stock.py"],
    )
    monkeypatch.setattr(verify, "run_pytest", fake_run_pytest)

    code = verify.cmd_verify(_ns(changed=True))
    assert code == 0
    assert captured["cwd"] == DLSTUDIO_DIR
    assert "tests/test_services_stock.py" in captured["files"]
    assert "tests/test_services_publish.py" in captured["files"]
    assert "tests/test_services_audio.py" in captured["files"]


def test_cmd_verify_changed_cli_domain_includes_verify_cmd_tests(monkeypatch):
    captured = {}

    def fake_run_pytest(files, *, cwd):
        captured["files"] = files
        return subprocess.CompletedProcess(["pytest"], 0)

    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: ["common/dlstudio/src/dlstudio/cli/__init__.py"],
    )
    monkeypatch.setattr(verify, "run_pytest", fake_run_pytest)

    assert verify.cmd_verify(_ns(changed=True)) == 0
    assert "tests/test_cli.py" in captured["files"]
    assert "tests/test_verify_cmd.py" in captured["files"]


def test_cmd_verify_changed_multiple_domains_are_unioned(monkeypatch):
    captured = {}

    def fake_run_pytest(files, *, cwd):
        captured["files"] = files
        return subprocess.CompletedProcess(["pytest"], 0)

    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: [
            "common/dlstudio/src/dlstudio/cache/__init__.py",
            "common/dlstudio/src/dlstudio/api/__init__.py",
        ],
    )
    monkeypatch.setattr(verify, "run_pytest", fake_run_pytest)

    assert verify.cmd_verify(_ns(changed=True)) == 0
    assert "tests/test_cache.py" in captured["files"]
    assert "tests/test_api.py" in captured["files"]


# ─── cmd_verify: full_suite widening (F1/F2/F8) ─────────────────────────

def test_cmd_verify_changed_model_ir_change_widens_to_full_suite(monkeypatch):
    captured = {}

    def fake_run_pytest(files, *, cwd):
        captured["files"] = files
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(["pytest", *files], 0)

    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: ["common/dlstudio/src/dlstudio/ir.py"],
    )
    monkeypatch.setattr(verify, "run_pytest", fake_run_pytest)

    code = verify.cmd_verify(_ns(changed=True))
    assert code == 0
    assert captured["files"] == ["tests"]
    assert captured["cwd"] == DLSTUDIO_DIR


def test_cmd_verify_changed_test_conftest_change_widens_to_full_suite(monkeypatch):
    captured = {}

    def fake_run_pytest(files, *, cwd):
        captured["files"] = files
        return subprocess.CompletedProcess(["pytest", *files], 0)

    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: ["common/dlstudio/tests/conftest.py"],
    )
    monkeypatch.setattr(verify, "run_pytest", fake_run_pytest)

    code = verify.cmd_verify(_ns(changed=True))
    assert code == 0
    assert captured["files"] == ["tests"]


def test_cmd_verify_changed_full_suite_wins_over_other_domain_hits(monkeypatch):
    """A model_ir change alongside an unrelated narrow-domain change must
    still widen to the full suite (it's a superset), not run only the
    resolved narrow-domain files."""
    captured = {}

    def fake_run_pytest(files, *, cwd):
        captured["files"] = files
        return subprocess.CompletedProcess(["pytest", *files], 0)

    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: [
            "common/dlstudio/src/dlstudio/cache/__init__.py",
            "common/dlstudio/src/dlstudio/model/edit.py",
        ],
    )
    monkeypatch.setattr(verify, "run_pytest", fake_run_pytest)

    code = verify.cmd_verify(_ns(changed=True))
    assert code == 0
    assert captured["files"] == ["tests"]


def test_cmd_verify_changed_full_suite_propagates_pytest_failure(monkeypatch):
    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: ["common/dlstudio/src/dlstudio/ir.py"],
    )
    monkeypatch.setattr(verify, "run_pytest", lambda files, *, cwd: subprocess.CompletedProcess(["pytest"], 1))
    assert verify.cmd_verify(_ns(changed=True)) == 1


def test_cmd_verify_changed_propagates_pytest_failure(monkeypatch):
    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: ["common/dlstudio/src/dlstudio/cache/__init__.py"],
    )
    monkeypatch.setattr(verify, "run_pytest", lambda files, *, cwd: subprocess.CompletedProcess(["pytest"], 1))
    assert verify.cmd_verify(_ns(changed=True)) == 1


# ─── webui: warn-skip without node, run when present ───────────────────

def test_run_webui_build_warns_and_skips_without_npm(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(verify.shutil, "which", lambda exe: None)
    rc = verify.run_webui_build(tmp_path)
    assert rc is None
    assert "npm not found" in capsys.readouterr().out


def test_run_webui_build_invokes_npm_when_present(monkeypatch, tmp_path):
    monkeypatch.setattr(verify.shutil, "which", lambda exe: r"C:\nodejs\npm.cmd")
    captured = {}

    def fake_run(cmd, cwd):
        captured["cmd"] = cmd
        captured["cwd"] = cwd
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr(verify.subprocess, "run", fake_run)
    rc = verify.run_webui_build(tmp_path)
    assert rc == 0
    assert captured["cmd"] == [r"C:\nodejs\npm.cmd", "run", "build"]
    assert captured["cwd"] == tmp_path


def test_cmd_verify_changed_webui_only_warns_and_skips_without_npm(monkeypatch, capsys):
    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: ["common/dlstudio/webui/src/App.tsx"],
    )
    monkeypatch.setattr(verify, "run_pytest", _no_pytest_allowed)
    monkeypatch.setattr(verify.shutil, "which", lambda exe: None)

    code = verify.cmd_verify(_ns(changed=True))
    assert code == 0
    out = capsys.readouterr().out
    assert "npm not found" in out


def test_cmd_verify_changed_webui_only_fails_when_build_fails(monkeypatch):
    monkeypatch.setattr(verify, "git_repo_root", lambda: REPO_ROOT)
    monkeypatch.setattr(
        verify, "git_status_paths",
        lambda root: ["common/dlstudio/webui/src/App.tsx"],
    )
    monkeypatch.setattr(verify, "run_pytest", _no_pytest_allowed)
    monkeypatch.setattr(verify.shutil, "which", lambda exe: "/usr/bin/npm")
    monkeypatch.setattr(
        verify.subprocess, "run",
        lambda cmd, cwd: subprocess.CompletedProcess(cmd, 1),
    )

    code = verify.cmd_verify(_ns(changed=True))
    assert code == 1


# ─── smoke: real ambient git status, still hermetic (run_pytest stubbed) ──

def test_cmd_verify_changed_real_git_status_smoke(monkeypatch):
    """Doesn't assert on which specific paths are dirty (that's whatever the
    working tree happens to have) -- only that the real git_status_paths ->
    classify_path -> resolve_test_files pipeline runs end to end without
    crashing. run_pytest is still stubbed so this never spawns a real nested
    pytest process."""
    monkeypatch.setattr(
        verify, "run_pytest",
        lambda files, *, cwd: subprocess.CompletedProcess(["pytest", *files], 0),
    )
    code = verify.cmd_verify(_ns(changed=True))
    assert isinstance(code, int)


# ─── CLI wiring ─────────────────────────────────────────────────────────

def test_cli_wires_verify_changed():
    args = cli._build_parser().parse_args(["verify", "--changed"])
    assert args.changed is True and args.full is False
    assert args.func is verify.cmd_verify


def test_cli_wires_verify_full():
    args = cli._build_parser().parse_args(["verify", "--full"])
    assert args.full is True


def test_cli_wires_verify_both_flags():
    args = cli._build_parser().parse_args(["verify", "--changed", "--full"])
    assert args.changed is True and args.full is True
