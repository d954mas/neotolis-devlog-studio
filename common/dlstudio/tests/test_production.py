from __future__ import annotations

import os
from pathlib import Path

import pytest

from dlstudio.model import Edit


def _write_product(root: Path) -> Path:
    root.mkdir(parents=True, exist_ok=True)
    (root / "product.toml").write_text(
        "\n".join(
            [
                'id = "not_a_trolley_problem"',
                'title = "Not a Trolley Problem!"',
                'game_root = "C:/projects/game-67-idle"',
                "",
                "[sources]",
                'steam = "https://store.steampowered.com/app/example"',
                'itch = "https://example.itch.io/not-a-trolley-problem"',
                'diary = "https://neotolis-diary.dev"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    return root


def _write_minimal_production(root: Path, production_id: str) -> Path:
    _write_product(root)
    production = root / "reels" / production_id
    edit_dir = production / "edit"
    edit_dir.mkdir(parents=True)
    (production / "production.toml").write_text(
        "\n".join(
            [
                f'id = "{production_id}"',
                'kind = "reel"',
                'date = "2026-07-18"',
                'orientation = "vertical"',
                'edit_path = "edit"',
                'data_root = "data"',
                f'delivery_root = "../../delivery/reels/{production_id}"',
                "",
            ]
        ),
        encoding="utf-8",
    )
    (edit_dir / "__init__.py").write_text(
        "\n".join(
            [
                "from dlstudio.model import Design, Edit, Fonts, Palette",
                "EDIT = Edit(",
                "    name='filesystem-production-v1',",
                "    design=Design(",
                "        resolution=(1080, 1920),",
                "        palette=Palette(tokens={'bg': '#000000', 'text': '#ffffff'}),",
                "        fonts=Fonts(main='data/fonts/main.ttf'),",
                "    ),",
                "    beats={}, order=[], output='data/finalize/final.mp4',",
                ")",
                "",
            ]
        ),
        encoding="utf-8",
    )
    return production


def test_product_manifest_loads_canonical_paths(tmp_path):
    from dlstudio.production import load_product_manifest

    _write_product(tmp_path)

    manifest = load_product_manifest(tmp_path)

    assert manifest.id == "not_a_trolley_problem"
    assert manifest.root == tmp_path.resolve()
    assert manifest.game_root == Path("C:/projects/game-67-idle")
    assert manifest.sources["diary"] == "https://neotolis-diary.dev"
    assert manifest.reels_dir == (tmp_path / "reels").resolve()
    assert manifest.delivery_dir == (tmp_path / "delivery").resolve()


@pytest.mark.parametrize(
    "production_id",
    ["2026-07-18_reel_01", "2026_07_18_reel", "reel_2026_07_18_01"],
)
def test_production_manifest_rejects_noncanonical_ids(tmp_path, production_id):
    from dlstudio.production import ProductionError, load_production_manifest

    production = _write_minimal_production(tmp_path, production_id)

    with pytest.raises(ProductionError, match="YYYY_MM_DD"):
        load_production_manifest(production)


def test_filesystem_production_edit_loads_and_scopes_cwd(tmp_path, monkeypatch):
    from dlstudio.cli import load_edit

    production = _write_minimal_production(
        tmp_path / "not_a_trolley_problem", "2026_07_18_reel_01"
    )
    start = Path.cwd()
    try:
        edit, project_root = load_edit(str(production))
        assert isinstance(edit, Edit)
        assert edit.name == "filesystem-production-v1"
        assert project_root == production.resolve()
        assert Path.cwd() == production.resolve()
        assert Path(edit.output) == Path("data/finalize/final.mp4")
    finally:
        os.chdir(start)


def test_filesystem_production_edit_can_be_addressed_by_manifest(tmp_path):
    from dlstudio.cli import load_edit

    production = _write_minimal_production(
        tmp_path / "not_a_trolley_problem", "2026_07_18_reel_01"
    )
    start = Path.cwd()
    try:
        edit, project_root = load_edit(str(production / "production.toml"))
        assert edit.name == "filesystem-production-v1"
        assert project_root == production.resolve()
    finally:
        os.chdir(start)


def test_product_colon_production_reference_loads(tmp_path, monkeypatch):
    from dlstudio.cli import load_edit

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    (workspace / "devlog.toml").write_text("", encoding="utf-8")
    production = _write_minimal_production(
        workspace / "not_a_trolley_problem", "2026_07_18_reel_01"
    )
    start = Path.cwd()
    try:
        monkeypatch.chdir(workspace)
        edit, project_root = load_edit(
            "not_a_trolley_problem:2026_07_18_reel_01"
        )
        assert edit.name == "filesystem-production-v1"
        assert project_root == production.resolve()
    finally:
        os.chdir(start)


def test_one_character_product_reference_is_not_parsed_as_windows_drive(
    tmp_path,
):
    from dlstudio.production import (
        is_filesystem_edit_ref,
        resolve_production_reference,
    )

    workspace = tmp_path / "workspace"
    workspace.mkdir()
    product = workspace / "x"
    production = _write_minimal_production(
        product,
        "2026_07_18_reel_01",
    )
    manifest = product / "product.toml"
    manifest.write_text(
        manifest.read_text(encoding="utf-8").replace(
            'id = "not_a_trolley_problem"',
            'id = "x"',
        ),
        encoding="utf-8",
    )
    reference = "x:2026_07_18_reel_01"

    assert is_filesystem_edit_ref(reference)
    assert resolve_production_reference(reference, workspace) == production.resolve()


def test_production_output_paths_are_isolated(tmp_path):
    from dlstudio.production import load_production_manifest

    first = _write_minimal_production(tmp_path, "2026_07_18_reel_01")
    second = _write_minimal_production(tmp_path, "2026_07_18_reel_02")

    a = load_production_manifest(first)
    b = load_production_manifest(second)

    assert a.finalize_dir != b.finalize_dir
    assert a.review_dir != b.review_dir
    assert a.publish_dir != b.publish_dir
    assert a.finalize_dir == (first / "data" / "finalize").resolve()
    assert a.delivery_dir == (
        tmp_path / "delivery" / "reels" / "2026_07_18_reel_01"
    ).resolve()


def test_filesystem_edit_reload_observes_source_changes(tmp_path):
    from dlstudio.cli import load_edit

    production = _write_minimal_production(tmp_path, "2026_07_18_reel_01")
    start = Path.cwd()
    try:
        first, _ = load_edit(str(production))
        init_path = production / "edit" / "__init__.py"
        source = init_path.read_text(encoding="utf-8")
        init_path.write_text(
            source.replace("filesystem-production-v1", "filesystem-production-v2"),
            encoding="utf-8",
        )
        second, _ = load_edit(str(production))
        assert first.name == "filesystem-production-v1"
        assert second.name == "filesystem-production-v2"
    finally:
        os.chdir(start)


def test_filesystem_edit_output_must_stay_in_production_finalize(tmp_path):
    from dlstudio.cli import CliError, load_edit

    production = _write_minimal_production(tmp_path, "2026_07_18_reel_01")
    init_path = production / "edit" / "__init__.py"
    source = init_path.read_text(encoding="utf-8")
    init_path.write_text(
        source.replace("data/finalize/final.mp4", "../../escaped.mp4"),
        encoding="utf-8",
    )
    start = Path.cwd()
    try:
        with pytest.raises(CliError, match="output.*data/finalize"):
            load_edit(str(production))
    finally:
        os.chdir(start)


def test_manifest_rejects_data_root_the_runtime_cannot_honor(tmp_path):
    from dlstudio.production import ProductionError, load_production_manifest

    production = _write_minimal_production(tmp_path, "2026_07_18_reel_01")
    manifest_path = production / "production.toml"
    source = manifest_path.read_text(encoding="utf-8")
    manifest_path.write_text(
        source.replace('data_root = "data"', 'data_root = "custom-data"'),
        encoding="utf-8",
    )

    with pytest.raises(ProductionError, match="data_root.*data"):
        load_production_manifest(production)
