from __future__ import annotations

import json
from pathlib import Path

import pytest

from dlstudio.production import ProductManifest, ProductionManifest
from dlstudio.services.telemetry import (
    TelemetryValidationError,
    load_telemetry_events,
    record_telemetry_event,
    summarize_telemetry,
)


def _manifest(tmp_path: Path) -> ProductionManifest:
    product_root = (tmp_path / "product").resolve()
    production_id = "2026_07_18_reel_01"
    product = ProductManifest(
        root=product_root,
        id="fixture_product",
        title="Fixture Product",
        version=1,
        game_root=(tmp_path / "game").resolve(),
        sources={},
        devlogs_dir=product_root / "devlogs",
        reels_dir=product_root / "reels",
        shared_dir=product_root / "shared",
        delivery_dir=product_root / "delivery",
    )
    root = product.reels_dir / production_id
    return ProductionManifest(
        root=root,
        id=production_id,
        kind="reel",
        date="2026-07-18",
        orientation="vertical",
        version=1,
        edit_dir=root / "edit",
        data_dir=root / "data",
        delivery_dir=product.delivery_dir / "reels" / production_id,
        product=product,
    )


def test_record_appends_scoped_jsonl_and_rewrites_stage_summary(tmp_path: Path):
    manifest = _manifest(tmp_path)
    preview = manifest.review_dir / "preview.mp4"
    preview.parent.mkdir(parents=True)
    preview.write_bytes(b"preview")
    final = manifest.delivery_dir / "video.mp4"
    final.parent.mkdir(parents=True)
    final.write_bytes(b"final")

    record_telemetry_event(
        manifest,
        stage="storyboard",
        agent_role="planner",
        wall_ms=1500,
        human_wait_ms=200,
        input_tokens=100,
        cached_input_tokens=80,
        output_tokens=20,
        artifact_paths=[preview],
        run_id="run_20260718_a1",
        timestamp="2026-07-18T01:02:03Z",
    )
    record_telemetry_event(
        manifest,
        stage="delivery",
        agent_role="packager",
        wall_ms=500,
        human_wait_ms=0,
        input_tokens=40,
        cached_input_tokens=10,
        output_tokens=5,
        artifact_paths=[final],
        timestamp="2026-07-18T01:03:03Z",
    )

    events = load_telemetry_events(manifest)
    assert [event.stage for event in events] == ["storyboard", "delivery"]
    assert events[0].product_id == manifest.product.id
    assert events[0].production_id == manifest.id
    assert events[0].run_id == "run_20260718_a1"
    assert events[0].artifact_paths == (
        "reels/2026_07_18_reel_01/data/review/preview.mp4",
    )
    assert events[1].artifact_paths == (
        "delivery/reels/2026_07_18_reel_01/video.mp4",
    )

    summary = json.loads(
        (manifest.review_dir / "telemetry_summary.json").read_text(encoding="utf-8")
    )
    assert summary["by_stage"]["storyboard"]["wall_ms"] == 1500
    assert summary["by_stage"]["delivery"]["events"] == 1
    assert summary["by_agent_role"]["planner"]["events"] == 1
    assert summary["by_agent_role"]["packager"]["output_tokens"] == 5
    assert summary["by_run_id"]["run_20260718_a1"]["events"] == 1
    assert summary["agent_roles"] == ["packager", "planner"]
    assert summary["total"] == {
        "events": 2,
        "wall_ms": 2000,
        "human_wait_ms": 200,
        "input_tokens": 140,
        "cached_input_tokens": 90,
        "output_tokens": 25,
    }


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("stage", ""),
        ("stage", "Final Render"),
        ("agent_role", ""),
        ("wall_ms", -1),
        ("human_wait_ms", -1),
        ("input_tokens", -1),
        ("cached_input_tokens", -1),
        ("output_tokens", -1),
    ],
)
def test_record_rejects_invalid_required_values(
    tmp_path: Path, field: str, value: object
):
    manifest = _manifest(tmp_path)
    artifact = manifest.review_dir / "artifact.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("ok", encoding="utf-8")
    values = {
        "stage": "review",
        "agent_role": "reviewer",
        "wall_ms": 1,
        "human_wait_ms": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "artifact_paths": [artifact],
    }
    values[field] = value

    with pytest.raises(TelemetryValidationError):
        record_telemetry_event(manifest, **values)


def test_record_rejects_cached_tokens_above_input_and_wait_above_wall(tmp_path: Path):
    manifest = _manifest(tmp_path)

    with pytest.raises(TelemetryValidationError, match="cached_input_tokens"):
        record_telemetry_event(
            manifest,
            stage="review",
            agent_role="reviewer",
            wall_ms=100,
            human_wait_ms=0,
            input_tokens=10,
            cached_input_tokens=11,
            output_tokens=0,
            artifact_paths=[],
        )
    with pytest.raises(TelemetryValidationError, match="human_wait_ms"):
        record_telemetry_event(
            manifest,
            stage="review",
            agent_role="reviewer",
            wall_ms=100,
            human_wait_ms=101,
            input_tokens=0,
            cached_input_tokens=0,
            output_tokens=0,
            artifact_paths=[],
        )


def test_record_rejects_missing_or_out_of_scope_artifacts(tmp_path: Path):
    manifest = _manifest(tmp_path)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")

    for artifact in (outside, manifest.review_dir / "missing.mp4"):
        with pytest.raises(TelemetryValidationError, match="artifact"):
            record_telemetry_event(
                manifest,
                stage="review",
                agent_role="reviewer",
                wall_ms=1,
                human_wait_ms=0,
                input_tokens=0,
                cached_input_tokens=0,
                output_tokens=0,
                artifact_paths=[artifact],
            )


def test_load_rejects_identity_mismatch_and_unknown_fields(tmp_path: Path):
    manifest = _manifest(tmp_path)
    path = manifest.review_dir / "telemetry.jsonl"
    path.parent.mkdir(parents=True)
    path.write_text(
        json.dumps(
            {
                "version": 1,
                "timestamp": "2026-07-18T01:02:03Z",
                "product_id": "wrong_product",
                "production_id": manifest.id,
                "stage": "review",
                "agent_role": "reviewer",
                "wall_ms": 1,
                "human_wait_ms": 0,
                "input_tokens": 0,
                "cached_input_tokens": 0,
                "output_tokens": 0,
                "artifact_paths": [],
                "unexpected": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(TelemetryValidationError):
        load_telemetry_events(manifest)


def test_summarize_is_deterministic_and_does_not_mix_identities(tmp_path: Path):
    manifest = _manifest(tmp_path)
    record_telemetry_event(
        manifest,
        stage="review",
        agent_role="reviewer",
        wall_ms=7,
        human_wait_ms=2,
        input_tokens=5,
        cached_input_tokens=3,
        output_tokens=1,
        artifact_paths=[],
    )
    events = load_telemetry_events(manifest)

    summary = summarize_telemetry(events)

    assert list(summary.by_stage) == ["review"]
    assert summary.total.events == 1
    assert summary.total.wall_ms == 7


def test_load_accepts_legacy_event_without_run_id(tmp_path: Path):
    manifest = _manifest(tmp_path)
    path = manifest.review_dir / "telemetry.jsonl"
    path.parent.mkdir(parents=True)
    payload = {
        "version": 1,
        "timestamp": "2026-07-18T01:02:03Z",
        "product_id": manifest.product.id,
        "production_id": manifest.id,
        "stage": "review",
        "agent_role": "reviewer",
        "wall_ms": 1,
        "human_wait_ms": 0,
        "input_tokens": 0,
        "cached_input_tokens": 0,
        "output_tokens": 0,
        "artifact_paths": [],
    }
    path.write_text(json.dumps(payload) + "\n", encoding="utf-8")

    events = load_telemetry_events(manifest)

    assert events[0].run_id is None
