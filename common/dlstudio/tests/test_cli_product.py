from __future__ import annotations

import argparse
import json
import tomllib
from pathlib import Path

import pytest

from dlstudio import cli
from dlstudio.cli import product


def _parse(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="dl2")
    sub = parser.add_subparsers(dest="command", required=True)
    product.add_subparsers(sub)
    return parser.parse_args(argv)


def _workspace(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "devlog.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    return tmp_path


def _new_product(tmp_path: Path, monkeypatch, product_id: str = "space_game") -> Path:
    _workspace(tmp_path, monkeypatch)
    args = _parse(["new-product", product_id])
    assert args.func(args) == 0
    return tmp_path / product_id


def test_parser_exposes_product_commands_and_defaults():
    new_product = _parse(["new-product", "space_game"])
    assert new_product.product == "space_game"
    assert new_product.title is None
    assert new_product.game_root == "."
    assert new_product.func is product.cmd_new_product

    new_production = _parse(
        ["new-production", "space_game", "--kind", "reel", "--date", "2026-07-18"]
    )
    assert new_production.kind == "reel"
    assert new_production.date == "2026-07-18"
    assert new_production.orientation is None
    assert new_production.func is product.cmd_new_production

    listing = _parse(["list-productions", "space_game"])
    assert listing.func is product.cmd_list_productions

    dedupe = _parse(["dedupe-assets", "space_game"])
    assert dedupe.apply is False
    assert dedupe.func is product.cmd_dedupe_assets


def test_main_cli_parser_registers_all_product_commands():
    parser = cli._build_parser()
    assert parser.parse_args(["new-product", "space_game"]).func is product.cmd_new_product
    assert parser.parse_args(
        ["new-production", "space_game", "--kind", "reel"]
    ).func is product.cmd_new_production
    assert parser.parse_args(
        ["list-productions", "space_game"]
    ).func is product.cmd_list_productions
    assert parser.parse_args(
        ["dedupe-assets", "space_game"]
    ).func is product.cmd_dedupe_assets


def test_new_product_creates_exact_product_tree_and_manifest(tmp_path, monkeypatch):
    root = _new_product(tmp_path, monkeypatch, "not_a_trolley_problem")

    manifest = tomllib.loads((root / "product.toml").read_text(encoding="utf-8"))
    assert manifest == {
        "id": "not_a_trolley_problem",
        "title": "Not a Trolley Problem",
        "game_root": ".",
        "sources": {},
    }
    assert (root / "shared" / "preferences.toml").is_file()
    for name in product.SHARED_ASSET_SUBDIRS:
        assert (root / "shared" / "assets" / name).is_dir()
    for name in ("devlogs", "reels", "delivery/devlogs", "delivery/reels"):
        assert (root / name).is_dir()


def test_new_product_accepts_explicit_manifest_metadata(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    args = _parse(
        [
            "new-product",
            "space_game",
            "--title",
            "Space: The Game",
            "--game-root",
            "C:/projects/space-game",
        ]
    )
    assert args.func(args) == 0

    manifest = tomllib.loads(
        (tmp_path / "space_game" / "product.toml").read_text(encoding="utf-8")
    )
    assert manifest["title"] == "Space: The Game"
    assert manifest["game_root"] == "C:/projects/space-game"


def test_new_product_refuses_invalid_or_existing_product(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    with pytest.raises(cli.CliError, match="identifier"):
        _parse(["new-product", "bad-name"]).func(_parse(["new-product", "bad-name"]))

    existing = tmp_path / "space_game"
    existing.mkdir()
    sentinel = existing / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    with pytest.raises(cli.CliError, match="already exists"):
        _parse(["new-product", "space_game"]).func(
            _parse(["new-product", "space_game"])
        )
    assert sentinel.read_text(encoding="utf-8") == "keep"


@pytest.mark.parametrize(
    ("kind", "orientation", "collection"),
    [("devlog", "landscape", "devlogs"), ("reel", "vertical", "reels")],
)
def test_new_production_creates_manifest_tree_and_packaged_edit(
    tmp_path, monkeypatch, kind, orientation, collection
):
    root = _new_product(tmp_path, monkeypatch)
    args = _parse(
        ["new-production", "space_game", "--kind", kind, "--date", "2026-07-18"]
    )
    assert args.func(args) == 0

    production_id = f"2026_07_18_{kind}_01"
    production_root = root / collection / production_id
    manifest = tomllib.loads(
        (production_root / "production.toml").read_text(encoding="utf-8")
    )
    assert manifest == {
        "id": production_id,
        "kind": kind,
        "date": "2026-07-18",
        "orientation": orientation,
        "edit_path": "edit",
        "data_root": "data",
        "delivery_root": f"../../delivery/{collection}/{production_id}",
    }
    for name in product.TEMPLATE_FILES:
        assert (production_root / "edit" / name).is_file()
    for name in product.PRODUCTION_DATA_SUBDIRS:
        assert (production_root / "data" / name).is_dir()

    design = (production_root / "edit" / "design.py").read_text(encoding="utf-8")
    expected_resolution = "RESOLUTION = (1080, 1920)" if orientation == "vertical" else "RESOLUTION = (1920, 1080)"
    assert expected_resolution in design
    contract = production_root / "data" / "plan" / "story_contract.json"
    if kind == "reel":
        payload = json.loads(contract.read_text(encoding="utf-8"))
        assert set(payload["standalone_story"]) == {"premise", "causal_turn", "payoff"}
    else:
        assert not contract.exists()
        story_map = json.loads(
            (production_root / "data" / "plan" / "story_map.json").read_text(
                encoding="utf-8"
            )
        )
        shot_manifest = json.loads(
            (production_root / "data" / "plan" / "shot_manifest.json").read_text(
                encoding="utf-8"
            )
        )
        assert story_map["schema"] == "devlog.longform_story_map/v1"
        assert len(story_map["mini_arcs"]) == 6
        assert shot_manifest["profile"] == "longform_devlog"
        assert shot_manifest["target_semantic_change_seconds"] == [3, 6]


def test_new_production_allocates_next_id_for_same_date_and_kind(tmp_path, monkeypatch):
    root = _new_product(tmp_path, monkeypatch)
    existing = root / "reels" / "2026_07_18_reel_07"
    existing.mkdir()

    args = _parse(
        ["new-production", "space_game", "--kind", "reel", "--date", "2026-07-18"]
    )
    assert args.func(args) == 0
    assert (root / "reels" / "2026_07_18_reel_08").is_dir()


def test_new_production_allows_explicit_orientation(tmp_path, monkeypatch):
    root = _new_product(tmp_path, monkeypatch)
    args = _parse(
        [
            "new-production",
            "space_game",
            "--kind",
            "reel",
            "--date",
            "2026-07-18",
            "--orientation",
            "landscape",
        ]
    )
    assert args.func(args) == 0
    manifest = tomllib.loads(
        (root / "reels" / "2026_07_18_reel_01" / "production.toml").read_text(
            encoding="utf-8"
        )
    )
    assert manifest["orientation"] == "landscape"


def test_new_production_rejects_invalid_date_before_creating_files(tmp_path, monkeypatch):
    root = _new_product(tmp_path, monkeypatch)
    args = _parse(
        ["new-production", "space_game", "--kind", "reel", "--date", "18-07-2026"]
    )
    with pytest.raises(cli.CliError, match="YYYY-MM-DD"):
        args.func(args)
    assert list((root / "reels").iterdir()) == []


def test_list_productions_is_sorted_and_reports_manifest_fields(
    tmp_path, monkeypatch, capsys
):
    _new_product(tmp_path, monkeypatch)
    capsys.readouterr()
    for kind, date in (("reel", "2026-07-19"), ("devlog", "2026-07-18")):
        args = _parse(
            ["new-production", "space_game", "--kind", kind, "--date", date]
        )
        assert args.func(args) == 0
    capsys.readouterr()

    args = _parse(["list-productions", "space_game"])
    assert args.func(args) == 0
    assert capsys.readouterr().out.splitlines() == [
        "2026_07_18_devlog_01\tdevlog\t2026-07-18\tlandscape",
        "2026_07_19_reel_01\treel\t2026-07-19\tvertical",
    ]


def test_dedupe_assets_is_dry_run_by_default_and_apply_is_idempotent(
    tmp_path, monkeypatch, capsys
):
    root = _new_product(tmp_path, monkeypatch)
    first = root / "devlogs" / "2026_07_18_devlog_01" / "data" / "music" / "track.ogg"
    second = root / "reels" / "2026_07_18_reel_01" / "data" / "music" / "track.ogg"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    first.write_bytes(b"same-track")
    second.write_bytes(b"same-track")
    capsys.readouterr()

    assert _parse(["dedupe-assets", "space_game"]).func(
        _parse(["dedupe-assets", "space_game"])
    ) == 0
    assert "dry-run: 1 groups, 2 relinked" in capsys.readouterr().out
    assert not (root / "shared" / "migration" / "dedup_report.json").exists()

    apply_args = _parse(["dedupe-assets", "space_game", "--apply"])
    assert apply_args.func(apply_args) == 0
    assert first.samefile(second)
    capsys.readouterr()

    assert apply_args.func(apply_args) == 0
    assert "0 relinked, 2 unchanged" in capsys.readouterr().out
