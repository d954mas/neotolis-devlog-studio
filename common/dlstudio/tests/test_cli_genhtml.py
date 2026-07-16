"""Tests for dlstudio.cli.genhtml -- `dl2 gen-html` argparse wiring +
convention resolution.

The parser is built PRIVATELY (argparse.ArgumentParser + add_subparsers +
genhtml.add_subparser) so these tests exercise only this module's wiring,
never the full dl2 parser. The handler's services calls are monkeypatched on
the `dlstudio.services` package (the same object the handler's lazy
`from dlstudio import services` resolves to), so no test here touches
node/npx or writes real project files.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import pytest

import dlstudio.services as services
from dlstudio.cli import CliError, genhtml


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dl2-test")
    sub = parser.add_subparsers(dest="command", required=True)
    genhtml.add_subparser(sub)
    return parser


def _parse(*argv: str) -> argparse.Namespace:
    return _parser().parse_args(["gen-html", *argv])


# ─── flag parsing ───────────────────────────────────────────────────────

def test_parses_init_flag_and_defaults():
    args = _parse("bars", "--init")
    assert args.dir == "bars"
    assert args.init is True
    assert args.out is None
    assert args.quality == "draft"
    assert args.func is genhtml.cmd_gen_html


def test_parses_out_and_quality():
    args = _parse("bars", "--out", "data/infographics/x.mp4", "--quality", "final")
    assert args.init is False
    assert args.out == "data/infographics/x.mp4"
    assert args.quality == "final"


def test_rejects_unknown_quality():
    with pytest.raises(SystemExit):
        _parse("bars", "--quality", "ultra")


def test_dir_is_required():
    with pytest.raises(SystemExit):
        _parse()


# ─── <dir> convention resolution ────────────────────────────────────────

def test_bare_asset_name_resolves_under_data_hyperframes():
    assert genhtml._resolve_project_dir("bars") == Path("data/hyperframes") / "bars"


def test_path_with_separator_is_taken_as_is():
    assert genhtml._resolve_project_dir("some/deep/asset_x") == Path("some/deep/asset_x")


def test_existing_directory_bare_name_is_taken_as_is(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "real_dir").mkdir()
    assert genhtml._resolve_project_dir("real_dir") == Path("real_dir")


# ─── handler: init ──────────────────────────────────────────────────────

def test_handler_init_scaffolds_resolved_convention_dir(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(services, "init_project", lambda d: calls.setdefault("dir", d))
    monkeypatch.setattr(
        services, "render_html",
        lambda *a, **k: pytest.fail("render_html must not run for --init alone"),
    )
    args = _parse("bars", "--init")
    assert args.func(args) == 0
    assert calls["dir"] == Path("data/hyperframes") / "bars"


def test_handler_init_file_exists_error_becomes_cli_error(monkeypatch):
    def boom(d):
        raise FileExistsError(f"{d} already exists and is not empty.")

    monkeypatch.setattr(services, "init_project", boom)
    args = _parse("bars", "--init")
    with pytest.raises(CliError, match="not empty"):
        args.func(args)


def test_handler_init_with_out_scaffolds_then_renders(monkeypatch):
    calls: dict = {}
    monkeypatch.setattr(services, "init_project", lambda d: calls.setdefault("init", d))

    def fake_render(project_dir, out, *, quality):
        calls["render"] = (project_dir, out, quality)
        return out

    monkeypatch.setattr(services, "render_html", fake_render)
    args = _parse("bars", "--init", "--out", "data/infographics/bars.mp4")
    assert args.func(args) == 0
    assert calls["init"] == Path("data/hyperframes") / "bars"
    assert calls["render"] == (
        Path("data/hyperframes") / "bars", Path("data/infographics/bars.mp4"), "draft",
    )


# ─── handler: render ────────────────────────────────────────────────────

def test_handler_render_defaults_out_from_asset_name(monkeypatch):
    calls: dict = {}

    def fake_render(project_dir, out, *, quality):
        calls["render"] = (project_dir, out, quality)
        return out

    monkeypatch.setattr(services, "render_html", fake_render)
    args = _parse("bars")
    assert args.func(args) == 0
    assert calls["render"] == (
        Path("data/hyperframes") / "bars",
        Path("data/infographics") / "bars.mp4",
        "draft",
    )


def test_handler_render_path_dir_derives_default_out_from_dir_name(monkeypatch):
    calls: dict = {}

    def fake_render(project_dir, out, *, quality):
        calls["render"] = (project_dir, out, quality)
        return out

    monkeypatch.setattr(services, "render_html", fake_render)
    args = _parse("some/deep/asset_x", "--quality", "final")
    assert args.func(args) == 0
    assert calls["render"] == (
        Path("some/deep/asset_x"),
        Path("data/infographics") / "asset_x.mp4",
        "final",
    )


def test_handler_render_explicit_out_wins(monkeypatch):
    calls: dict = {}

    def fake_render(project_dir, out, *, quality):
        calls["render"] = (project_dir, out, quality)
        return out

    monkeypatch.setattr(services, "render_html", fake_render)
    args = _parse("bars", "--out", "elsewhere/final.mp4")
    assert args.func(args) == 0
    assert calls["render"][1] == Path("elsewhere/final.mp4")


def test_handler_wraps_service_runtime_error_in_cli_error(monkeypatch):
    def boom(project_dir, out, *, quality):
        raise RuntimeError("HyperFrames render failed (rc=1). stderr tail:\nboom")

    monkeypatch.setattr(services, "render_html", boom)
    args = _parse("bars")
    with pytest.raises(CliError, match=r"rc=1"):
        args.func(args)
