from __future__ import annotations

from pathlib import Path


def _write_production(product: Path, collection: str, production_id: str, kind: str) -> Path:
    root = product / collection / production_id
    (root / "edit").mkdir(parents=True)
    (root / "edit" / "__init__.py").write_text("", encoding="utf-8")
    date = production_id[:10].replace("_", "-")
    orientation = "landscape" if kind == "devlog" else "vertical"
    (root / "production.toml").write_text(
        "\n".join(
            (
                f'id = "{production_id}"',
                f'kind = "{kind}"',
                f'date = "{date}"',
                f'orientation = "{orientation}"',
                'edit_path = "edit"',
                'data_root = "data"',
                f'delivery_root = "../../delivery/{collection}/{production_id}"',
            )
        ),
        encoding="utf-8",
    )
    return root


def test_product_overview_lists_devlogs_and_reels_with_current_marker(tmp_path):
    product = tmp_path / "not_a_trolley_problem"
    product.mkdir()
    (product / "product.toml").write_text(
        '\n'.join((
            'id = "not_a_trolley_problem"',
            'title = "Not a Trolley Problem"',
            'game_root = "."',
            '[sources]',
        )),
        encoding="utf-8",
    )
    devlog = _write_production(
        product, "devlogs", "2026_07_17_devlog_01", "devlog"
    )
    reel = _write_production(
        product, "reels", "2026_07_18_reel_01", "reel"
    )

    from dlstudio.services.product_overview import build_product_overview

    overview = build_product_overview(reel)

    assert overview.product_id == "not_a_trolley_problem"
    assert overview.title == "Not a Trolley Problem"
    assert overview.current_production_id == reel.name
    assert [item.id for item in overview.productions] == [devlog.name, reel.name]
    assert [item.current for item in overview.productions] == [False, True]
    assert overview.productions[0].studio_ref == (
        "not_a_trolley_problem:2026_07_17_devlog_01"
    )
