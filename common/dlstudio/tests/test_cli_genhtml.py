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
    assert args.template is None
    assert args.orientation == "landscape"
    assert args.variables_file is None
    assert args.evidence_file is None
    assert args.production_root is None
    assert args.func is genhtml.cmd_gen_html


def test_parses_visual_block_scaffold_options():
    args = _parse(
        "chapter",
        "--init",
        "--template",
        "day-card",
        "--orientation",
        "vertical",
    )
    assert args.template == "day-card"
    assert args.orientation == "vertical"


def test_parses_variables_file():
    args = _parse(
        "chapter",
        "--variables-file",
        "chapter.json",
        "--evidence-file",
        "chapter.evidence.json",
        "--production-root",
        "video",
    )
    assert args.variables_file == "chapter.json"
    assert args.evidence_file == "chapter.evidence.json"
    assert args.production_root == "video"


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
    def fake_init(d, *, template, orientation):
        calls["init"] = (d, template, orientation)

    monkeypatch.setattr(services, "init_project", fake_init)
    monkeypatch.setattr(
        services, "render_html",
        lambda *a, **k: pytest.fail("render_html must not run for --init alone"),
    )
    args = _parse("bars", "--init")
    assert args.func(args) == 0
    assert calls["init"] == (
        Path("data/hyperframes") / "bars",
        None,
        "landscape",
    )


def test_handler_init_file_exists_error_becomes_cli_error(monkeypatch):
    def boom(d, **kwargs):
        raise FileExistsError(f"{d} already exists and is not empty.")

    monkeypatch.setattr(services, "init_project", boom)
    args = _parse("bars", "--init")
    with pytest.raises(CliError, match="not empty"):
        args.func(args)


def test_handler_init_with_out_scaffolds_then_renders(monkeypatch):
    calls: dict = {}
    def fake_init(d, *, template, orientation):
        calls["init"] = (d, template, orientation)

    monkeypatch.setattr(services, "init_project", fake_init)

    def fake_render(project_dir, out, *, quality, variables_file, evidence_file):
        calls["render"] = (project_dir, out, quality, variables_file, evidence_file)
        return out

    monkeypatch.setattr(services, "render_html", fake_render)
    args = _parse("bars", "--init", "--out", "data/infographics/bars.mp4")
    assert args.func(args) == 0
    assert calls["init"] == (
        Path("data/hyperframes") / "bars",
        None,
        "landscape",
    )
    assert calls["render"] == (
        Path("data/hyperframes") / "bars",
        Path("data/infographics/bars.mp4"),
        "draft",
        None,
        None,
    )


# ─── handler: render ────────────────────────────────────────────────────

def test_handler_render_defaults_out_from_asset_name(monkeypatch):
    calls: dict = {}

    def fake_render(project_dir, out, *, quality, variables_file, evidence_file):
        calls["render"] = (project_dir, out, quality, variables_file, evidence_file)
        return out

    monkeypatch.setattr(services, "render_html", fake_render)
    args = _parse("bars")
    assert args.func(args) == 0
    assert calls["render"] == (
        Path("data/hyperframes") / "bars",
        Path("data/infographics") / "bars.mp4",
        "draft",
        None,
        None,
    )


def test_handler_render_path_dir_derives_default_out_from_dir_name(monkeypatch):
    calls: dict = {}

    def fake_render(project_dir, out, *, quality, variables_file, evidence_file):
        calls["render"] = (project_dir, out, quality, variables_file, evidence_file)
        return out

    monkeypatch.setattr(services, "render_html", fake_render)
    args = _parse("some/deep/asset_x", "--quality", "final")
    assert args.func(args) == 0
    assert calls["render"] == (
        Path("some/deep/asset_x"),
        Path("data/infographics") / "asset_x.mp4",
        "final",
        None,
        None,
    )


def test_handler_render_explicit_out_wins(monkeypatch):
    calls: dict = {}

    def fake_render(project_dir, out, *, quality, variables_file, evidence_file):
        calls["render"] = (project_dir, out, quality, variables_file, evidence_file)
        return out

    monkeypatch.setattr(services, "render_html", fake_render)
    args = _parse("bars", "--out", "elsewhere/final.mp4")
    assert args.func(args) == 0
    assert calls["render"][1] == Path("elsewhere/final.mp4")


def test_handler_wraps_service_runtime_error_in_cli_error(monkeypatch):
    def boom(project_dir, out, *, quality, variables_file, evidence_file):
        raise RuntimeError("HyperFrames render failed (rc=1). stderr tail:\nboom")

    monkeypatch.setattr(services, "render_html", boom)
    args = _parse("bars")
    with pytest.raises(CliError, match=r"rc=1"):
        args.func(args)


def test_handler_requires_explicit_out_for_variables_file():
    args = _parse("ending", "--variables-file", "release.json")
    with pytest.raises(CliError, match="explicit --out"):
        args.func(args)


def test_handler_rejects_template_without_init():
    args = _parse("ending", "--template", "cta-endcard")
    with pytest.raises(CliError, match="requires --init"):
        args.func(args)


def test_handler_rejects_render_only_orientation():
    args = _parse("ending", "--orientation", "vertical")
    with pytest.raises(CliError, match="only used with --init"):
        args.func(args)


def test_handler_rejects_evidence_without_variables():
    args = _parse("ending", "--evidence-file", "proof.json", "--out", "ending.mp4")
    with pytest.raises(CliError, match="requires --variables-file"):
        args.func(args)


def test_handler_passes_template_orientation_and_variables_file(monkeypatch):
    calls: dict = {}

    def fake_init(d, *, template, orientation):
        calls["init"] = (d, template, orientation)

    def fake_render(project_dir, out, *, quality, variables_file, evidence_file):
        calls["render"] = (project_dir, out, quality, variables_file, evidence_file)
        return out

    monkeypatch.setattr(services, "init_project", fake_init)
    monkeypatch.setattr(services, "render_html", fake_render)
    args = _parse(
        "ending",
        "--init",
        "--template",
        "cta-endcard",
        "--orientation",
        "vertical",
        "--variables-file",
        "cta.json",
        "--out",
        "ending.mp4",
    )
    assert args.func(args) == 0
    assert calls["init"] == (
        Path("data/hyperframes") / "ending",
        "cta-endcard",
        "vertical",
    )
    assert calls["render"] == (
        Path("data/hyperframes") / "ending",
        Path("ending.mp4"),
        "draft",
        Path("cta.json"),
        None,
    )


def test_handler_passes_explicit_production_root(monkeypatch):
    calls: dict = {}

    def fake_render(
        project_dir,
        out,
        *,
        quality,
        variables_file,
        evidence_file,
        production_root,
    ):
        calls["render"] = {
            "project": project_dir,
            "out": out,
            "quality": quality,
            "variables": variables_file,
            "evidence": evidence_file,
            "production_root": production_root,
        }
        return out

    monkeypatch.setattr(services, "render_html", fake_render)
    args = _parse(
        "proof",
        "--out", "proof.mp4",
        "--variables-file", "values.json",
        "--evidence-file", "evidence.json",
        "--production-root", "video",
    )

    assert args.func(args) == 0
    assert calls["render"]["production_root"] == Path("video")
