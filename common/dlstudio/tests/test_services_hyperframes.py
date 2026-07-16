"""Tests for dlstudio.services.hyperframes -- the `npx hyperframes` bridge.

`subprocess.run` and `shutil.which` are monkeypatched on the module under
test, so no test here ever needs node/npx installed or spawns a real
process: render tests assert on the argv/env/kwargs the bridge would have
handed to subprocess (mocking style of test_services_stock.py /
test_services_tts.py). `init_project` is pure filesystem work and runs for
real against tmp_path.
"""
from __future__ import annotations

import json
import subprocess

import pytest

from dlstudio.services import hyperframes as hf

FAKE_NPX = "C:/fake/node/npx.cmd"


def _completed(rc: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def _mock_toolchain(monkeypatch, captured: dict, *, rc: int = 0, stderr: str = ""):
    """Fake both `shutil.which` (npx present) and `subprocess.run` (records
    argv + kwargs, returns a canned CompletedProcess)."""
    monkeypatch.setattr(hf.shutil, "which", lambda name: FAKE_NPX)

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _completed(rc=rc, stderr=stderr)

    monkeypatch.setattr(hf.subprocess, "run", fake_run)


# ─── init_project ───────────────────────────────────────────────────────

def test_init_project_scaffolds_expected_files(tmp_path):
    root = hf.init_project(tmp_path / "bar_demo")
    assert root == tmp_path / "bar_demo"
    assert (root / "index.html").is_file()
    assert (root / "meta.json").is_file()
    assert (root / "compositions").is_dir()
    assert (root / "assets").is_dir()

    meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    assert meta["name"] == "bar_demo"
    assert meta["id"] == "bar_demo"
    assert meta["createdBy"] == "dl2 gen-html --init"


def test_init_project_starter_registers_paused_window_timelines(tmp_path):
    root = hf.init_project(tmp_path / "tl_demo")
    html = (root / "index.html").read_text(encoding="utf-8")
    # the deterministic-seek contract: a paused timeline registered under
    # the composition root's data-composition-id
    assert "gsap.timeline({ paused: true })" in html
    assert 'window.__timelines["root"] = tl;' in html
    assert 'data-composition-id="root"' in html


def test_init_project_title_is_escaped_into_index(tmp_path):
    root = hf.init_project(tmp_path / "titled", title="A<B & C")
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "A&lt;B &amp; C" in html


def test_init_project_refuses_non_empty_dir(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError, match="not empty"):
        hf.init_project(target)
    assert (target / "keep.txt").exists()  # untouched


def test_init_project_force_overwrites_starter_files(tmp_path):
    target = tmp_path / "existing"
    hf.init_project(target)
    root = hf.init_project(target, force=True, title="SECOND RUN")
    assert "SECOND RUN" in (root / "index.html").read_text(encoding="utf-8")


# ─── render_html: argv / env / kwargs ───────────────────────────────────

def test_render_html_builds_expected_npx_argv(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "bars")
    out = tmp_path / "infographics" / "bars.mp4"

    result = hf.render_html(project, out)

    assert result == out.resolve()
    cmd = captured["cmd"]
    assert cmd[0] == FAKE_NPX
    assert cmd[1:4] == ["-y", "hyperframes", "render"]
    assert cmd[4] == str(project.resolve())
    assert cmd[cmd.index("--output") + 1] == str(out.resolve())
    assert cmd[cmd.index("--quality") + 1] == "draft"
    assert captured["kwargs"]["cwd"] == project.resolve()


def test_render_html_out_dir_is_auto_created(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "bars")
    out = tmp_path / "deep" / "nested" / "bars.mp4"
    assert not out.parent.exists()
    hf.render_html(project, out)
    assert out.parent.is_dir()


def test_render_html_quality_final_maps_to_high(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "bars")
    hf.render_html(project, tmp_path / "out.mp4", quality="final")
    cmd = captured["cmd"]
    assert cmd[cmd.index("--quality") + 1] == "high"


def test_render_html_rejects_unknown_quality(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "bars")
    with pytest.raises(ValueError, match="unsupported quality"):
        hf.render_html(project, tmp_path / "out.mp4", quality="ultra")
    assert "cmd" not in captured  # rejected before any subprocess work


def test_render_html_env_carries_use_system_ca_and_no_color(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    monkeypatch.delenv("NODE_OPTIONS", raising=False)
    project = hf.init_project(tmp_path / "bars")
    hf.render_html(project, tmp_path / "out.mp4")
    env = captured["kwargs"]["env"]
    assert env["NODE_OPTIONS"] == "--use-system-ca"
    assert env["NO_COLOR"] == "1"


def test_render_html_preserves_existing_node_options(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    monkeypatch.setenv("NODE_OPTIONS", "--max-old-space-size=4096")
    project = hf.init_project(tmp_path / "bars")
    hf.render_html(project, tmp_path / "out.mp4")
    node_options = captured["kwargs"]["env"]["NODE_OPTIONS"]
    assert "--max-old-space-size=4096" in node_options
    assert "--use-system-ca" in node_options


def test_render_html_does_not_duplicate_use_system_ca(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    monkeypatch.setenv("NODE_OPTIONS", "--use-system-ca")
    project = hf.init_project(tmp_path / "bars")
    hf.render_html(project, tmp_path / "out.mp4")
    node_options = captured["kwargs"]["env"]["NODE_OPTIONS"]
    assert node_options.count("--use-system-ca") == 1


def test_render_html_subprocess_decodes_utf8_with_replace(tmp_path, monkeypatch):
    # 0.12 class: child output must be decoded as utf-8+replace, never the
    # ANSI code page (Cyrillic paths are the target environment).
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "bars")
    hf.render_html(project, tmp_path / "out.mp4")
    kwargs = captured["kwargs"]
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert kwargs["text"] is True
    assert kwargs["capture_output"] is True


# ─── render_html: error paths ───────────────────────────────────────────

def test_render_html_missing_npx_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(hf.shutil, "which", lambda name: None)
    project = hf.init_project(tmp_path / "bars")
    with pytest.raises(RuntimeError, match="Node.js 22"):
        hf.render_html(project, tmp_path / "out.mp4")


def test_render_html_missing_entry_file_raises_before_npx_probe(tmp_path, monkeypatch):
    # entry check comes first, so the most actionable error wins even on a
    # machine without node -- which() returning None must not mask it
    monkeypatch.setattr(hf.shutil, "which", lambda name: None)
    empty = tmp_path / "empty_project"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="index.html"):
        hf.render_html(empty, tmp_path / "out.mp4")


def test_render_html_failure_raises_with_stderr_tail(tmp_path, monkeypatch):
    captured: dict = {}
    stderr = "\n".join([f"noise line {i}" for i in range(30)] + ["boom: chrome not found"])
    _mock_toolchain(monkeypatch, captured, rc=1, stderr=stderr)
    project = hf.init_project(tmp_path / "bars")
    out = tmp_path / "out" / "bars.mp4"

    with pytest.raises(RuntimeError, match="rc=1") as excinfo:
        hf.render_html(project, out)
    assert "boom: chrome not found" in str(excinfo.value)

    debug = out.resolve().with_suffix(".mp4.hyperframes_error.txt")
    assert debug.is_file()
    assert "boom: chrome not found" in debug.read_text(encoding="utf-8")
