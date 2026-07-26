"""Tests for dlstudio.cli.newvideo (`dl2 new-video` scaffolding) and the
packaged dlstudio.template it copies from.

new-video is not wired into cli._build_parser() yet (the orchestrator adds
that line later), so these tests build a private parser around
newvideo.add_subparser -- the exact pattern the real wiring will use.
"""
from __future__ import annotations

import argparse
import importlib
import uuid
from pathlib import Path

import pytest

from dlstudio import cli
from dlstudio.cli import newvideo
from dlstudio.model import Edit


def _unique_pkg(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="dl2")
    sub = parser.add_subparsers(dest="command", required=True)
    newvideo.add_subparser(sub)
    return parser.parse_args(argv)


def _scaffold(tmp_path: Path, monkeypatch, project: str, *extra: str) -> int:
    """Run `dl2 new-video <project> *extra` in a tmp workspace (devlog.toml
    marker at tmp_path, cwd inside it -- the same workspace-root discovery
    every other cli command uses)."""
    (tmp_path / "devlog.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    args = _parse(["new-video", project, *extra])
    return args.func(args)


def _import_created_edit(tmp_path: Path, monkeypatch, pkg: str, edit_name: str = "main"):
    monkeypatch.syspath_prepend(str(tmp_path))
    return importlib.import_module(f"{pkg}.edits.{edit_name}")


# ─── the packaged template itself ──────────────────────────────────────

def test_template_package_imports_and_exposes_edit():
    template = importlib.import_module("dlstudio.template")
    assert isinstance(template.EDIT, Edit)
    assert template.EDIT.design.resolution == (1920, 1080)


# ─── argparse wiring ────────────────────────────────────────────────────

def test_parse_defaults():
    args = _parse(["new-video", "proj"])
    assert args.project == "proj"
    assert args.format == "landscape"
    assert args.edit_name == "main"
    assert args.func is newvideo.cmd_new_video


def test_parse_rejects_unknown_format():
    with pytest.raises(SystemExit):
        _parse(["new-video", "proj", "--format", "square"])


# ─── created structure ──────────────────────────────────────────────────

def test_new_video_creates_full_structure(tmp_path, monkeypatch):
    pkg = _unique_pkg("vidproj")
    assert _scaffold(tmp_path, monkeypatch, pkg) == 0

    proj = tmp_path / pkg
    assert (proj / "__init__.py").is_file()
    assert (proj / "edits" / "__init__.py").is_file()
    for name in newvideo.TEMPLATE_FILES:
        assert (proj / "edits" / "main" / name).is_file()
    for sub in newvideo.DATA_SUBDIRS:
        assert (proj / "data" / sub).is_dir()


def test_new_video_custom_edit_name(tmp_path, monkeypatch):
    pkg = _unique_pkg("vidproj_name")
    assert _scaffold(tmp_path, monkeypatch, pkg, "--edit-name", "teaser") == 0
    assert (tmp_path / pkg / "edits" / "teaser" / "beats.py").is_file()


# ─── the created edit package imports and exposes EDIT ──────────────────

def test_created_edit_imports_and_exposes_edit(tmp_path, monkeypatch):
    pkg = _unique_pkg("vidproj_import")
    _scaffold(tmp_path, monkeypatch, pkg)
    mod = _import_created_edit(tmp_path, monkeypatch, pkg)
    assert isinstance(mod.EDIT, Edit)
    assert mod.EDIT.order            # the template ships a non-empty edit
    assert mod.EDIT.mix.music        # ...including the music example


def test_created_edit_teaches_non_looping_identity_bound_video(tmp_path, monkeypatch):
    pkg = _unique_pkg("vidproj_identity")
    _scaffold(tmp_path, monkeypatch, pkg)
    mod = _import_created_edit(tmp_path, monkeypatch, pkg)

    gameplay = mod.EDIT.beats["b01"].scene
    assert gameplay.loop is False
    assert gameplay.asset_id == "capture:gameplay_01"
    assert gameplay.editorial_role == "gameplay"
    assert gameplay.offset == 5.0

    infographic = mod.EDIT.beats["b02"].chunks[-1].content
    assert infographic.editorial_role == "presentation"
    assert infographic.render_manifest.endswith(".mp4.render.json")


def test_landscape_resolution(tmp_path, monkeypatch):
    pkg = _unique_pkg("vidproj_land")
    _scaffold(tmp_path, monkeypatch, pkg, "--format", "landscape")
    mod = _import_created_edit(tmp_path, monkeypatch, pkg)
    assert mod.EDIT.design.resolution == (1920, 1080)


def test_vertical_resolution(tmp_path, monkeypatch):
    pkg = _unique_pkg("vidproj_vert")
    _scaffold(tmp_path, monkeypatch, pkg, "--format", "vertical")
    mod = _import_created_edit(tmp_path, monkeypatch, pkg)
    assert mod.EDIT.design.resolution == (1080, 1920)


# ─── refusals / errors ──────────────────────────────────────────────────

def test_existing_edit_dir_raises_cli_error(tmp_path, monkeypatch):
    pkg = _unique_pkg("vidproj_dup")
    _scaffold(tmp_path, monkeypatch, pkg)
    with pytest.raises(cli.CliError, match="already exists"):
        _scaffold(tmp_path, monkeypatch, pkg)


def test_second_edit_in_same_project_is_allowed(tmp_path, monkeypatch):
    pkg = _unique_pkg("vidproj_second")
    _scaffold(tmp_path, monkeypatch, pkg)
    assert _scaffold(tmp_path, monkeypatch, pkg, "--edit-name", "reel01") == 0
    assert (tmp_path / pkg / "edits" / "reel01" / "design.py").is_file()
    # the first edit is untouched
    assert (tmp_path / pkg / "edits" / "main" / "design.py").is_file()


def test_non_identifier_project_raises(tmp_path, monkeypatch):
    with pytest.raises(cli.CliError, match="identifier"):
        _scaffold(tmp_path, monkeypatch, "bad-name")


def test_non_identifier_edit_name_raises(tmp_path, monkeypatch):
    pkg = _unique_pkg("vidproj_badedit")
    with pytest.raises(cli.CliError, match="identifier"):
        _scaffold(tmp_path, monkeypatch, pkg, "--edit-name", "1bad")


# ─── rewrite_resolution unit ────────────────────────────────────────────

def test_rewrite_resolution_replaces_line():
    src = "X = 1\nRESOLUTION = (1920, 1080)\nY = RESOLUTION\n"
    out = newvideo.rewrite_resolution(src, (1080, 1920))
    assert "RESOLUTION = (1080, 1920)" in out
    assert "(1920, 1080)" not in out


def test_rewrite_resolution_requires_exactly_one_line():
    with pytest.raises(ValueError, match="exactly one"):
        newvideo.rewrite_resolution("W = 1\n", (1080, 1920))
    two = "RESOLUTION = (1920, 1080)\nRESOLUTION = (1080, 1920)\n"
    with pytest.raises(ValueError, match="exactly one"):
        newvideo.rewrite_resolution(two, (1080, 1920))
