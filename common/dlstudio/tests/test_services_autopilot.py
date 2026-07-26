from __future__ import annotations

import json
from pathlib import Path

from PIL import Image


def test_build_asset_catalog_records_quality_provenance_and_duplicates(tmp_path):
    from dlstudio.services.autopilot import build_asset_catalog

    footage = tmp_path / "data" / "footage" / "game"
    images = tmp_path / "data" / "images" / "canvas"
    footage.mkdir(parents=True)
    images.mkdir(parents=True)
    portrait = Image.new("RGB", (1080, 1920), "#223344")
    portrait.save(footage / "portrait.png")
    portrait.save(images / "duplicate.png")
    Image.new("RGB", (1920, 1080), "#445566").save(images / "landscape.png")
    out = tmp_path / "data" / "assets" / "catalog.json"

    catalog = build_asset_catalog(tmp_path, out_path=out)

    assert out.is_file()
    assert len(catalog.assets) == 3
    by_name = {Path(asset.path).name: asset for asset in catalog.assets}
    assert by_name["portrait.png"].orientation == "vertical"
    assert by_name["portrait.png"].source_role == "real_product"
    assert by_name["landscape.png"].orientation == "landscape"
    assert "duplicate" in by_name["portrait.png"].quality_flags
    assert by_name["portrait.png"].sha256 == by_name["duplicate.png"].sha256
    payload = json.loads(out.read_text(encoding="utf-8"))
    assert payload["version"] == 1


def test_validate_shot_manifest_catches_duplicate_pacing_readability_and_source(tmp_path):
    from dlstudio.services.autopilot import AssetCatalog, AssetRecord, validate_shot_manifest

    catalog = AssetCatalog(
        root=str(tmp_path),
        assets=[
            AssetRecord(
                path="data/images/old_canvas.png",
                sha256="a" * 64,
                size=100,
                modified_at="2026-07-01T00:00:00",
                kind="image",
                width=720,
                height=1280,
                duration=None,
                fps=None,
                orientation="vertical",
                intended_for="vertical",
                provenance="canvas",
                source_role="reference",
                quality_flags=["stale"],
            )
        ],
    )
    shots = [
        {
            "id": "s01",
            "vo_range": [0, 5],
            "purpose": "show_real_gameplay",
            "src": "data/images/old_canvas.png",
            "source_role": "reference",
            "t0": 0.0,
            "t1": 0.8,
            "min_readable_duration": 2.2,
            "reuse": "forbidden",
            "motion": "none",
            "intent": "normal",
            "approved": True,
        },
        {
            "id": "s02",
            "vo_range": [6, 10],
            "purpose": "another_claim",
            "src": "data/images/old_canvas.png",
            "source_role": "reference",
            "t0": 0.8,
            "t1": 7.8,
            "min_readable_duration": 2.0,
            "reuse": "forbidden",
            "motion": "none",
            "intent": "normal",
            "approved": True,
        },
    ]

    report = validate_shot_manifest(
        shots, catalog, orientation="landscape", final=True
    )
    codes = {issue.code for issue in report.issues}

    assert {"VQ-DUP", "VQ-PACE", "VQ-READ", "VQ-SOURCE"} <= codes
    assert report.ok is False


def test_validate_shot_manifest_accepts_intentional_callback_and_readable_text(tmp_path):
    from dlstudio.services.autopilot import AssetCatalog, AssetRecord, validate_shot_manifest

    asset = AssetRecord(
        path="data/footage/game.mp4",
        sha256="b" * 64,
        size=1000,
        modified_at="2026-07-18T00:00:00",
        kind="video",
        width=1080,
        height=1920,
        duration=12.0,
        fps=60.0,
        orientation="vertical",
        intended_for="vertical",
        provenance="game_capture",
        source_role="real_product",
        quality_flags=[],
    )
    catalog = AssetCatalog(root=str(tmp_path), assets=[asset])
    shots = [
        {
            "id": "s01", "vo_range": [0, 4], "purpose": "show_real_gameplay",
            "src": asset.path, "source_role": "real_product", "t0": 0.0, "t1": 3.0,
            "min_readable_duration": 2.0, "reuse": "callback", "motion": "native",
            "intent": "normal", "approved": True,
        },
        {
            "id": "s02", "vo_range": [10, 14], "purpose": "callback_to_gameplay",
            "src": asset.path, "source_role": "real_product", "t0": 8.0, "t1": 11.0,
            "min_readable_duration": 2.0, "reuse": "callback", "motion": "native",
            "intent": "callback", "approved": True,
        },
    ]

    report = validate_shot_manifest(shots, catalog, orientation="vertical", final=True)

    assert report.ok
    assert not report.issues


def test_validate_shot_manifest_accepts_opposite_orientation_inside_inset(tmp_path):
    from dlstudio.services.autopilot import AssetCatalog, AssetRecord, validate_shot_manifest

    asset = AssetRecord(
        path="data/footage/landscape_game.mp4",
        sha256="c" * 64,
        size=1000,
        modified_at="2026-07-18T00:00:00",
        kind="video",
        width=1920,
        height=1080,
        duration=12.0,
        fps=30.0,
        orientation="landscape",
        intended_for="landscape",
        provenance="game_capture",
        source_role="real_product",
        quality_flags=[],
    )
    catalog = AssetCatalog(root=str(tmp_path), assets=[asset])
    shots = [{
        "id": "s01", "vo_range": [0, 6], "purpose": "show_real_gameplay",
        "src": asset.path, "source_role": "real_product", "t0": 0.0, "t1": 4.0,
        "min_readable_duration": 2.0, "reuse": "forbidden", "motion": "native",
        "intent": "normal", "presentation": "inset", "approved": True,
    }]

    report = validate_shot_manifest(shots, catalog, orientation="vertical", final=True)

    assert report.ok
    assert not report.issues
