from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


def _facts(tmp_path: Path, *, content: bytes = b"take-one") -> dict:
    artifact = tmp_path / "data" / "footage" / "day5.mp4"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(content)
    metadata = tmp_path / "data" / "footage" / "day5.mp4.capture.json"
    metadata.write_bytes(b'{"trusted":"recorder"}')
    batch = tmp_path / "data" / "plan" / "capture_batch.json"
    batch.parent.mkdir(parents=True, exist_ok=True)
    batch.write_bytes(b'{"version":2,"requests":[]}')
    results = tmp_path / "data" / "plan" / "capture_results.json"
    results.write_bytes(b'{"version":2,"results":[]}')
    return {
        "request_id": "day5_station",
        "artifact_path": "data/footage/day5.mp4",
        "artifact_sha256": hashlib.sha256(content).hexdigest(),
        "metadata_path": "data/footage/day5.mp4.capture.json",
        "metadata_sha256": hashlib.sha256(metadata.read_bytes()).hexdigest(),
        "capture_batch_path": "data/plan/capture_batch.json",
        "capture_batch_sha256": hashlib.sha256(batch.read_bytes()).hexdigest(),
        "capture_results_path": "data/plan/capture_results.json",
        "capture_results_sha256": hashlib.sha256(results.read_bytes()).hexdigest(),
        "editorial_role": "gameplay",
        "capture_method": "realtime_window",
        "state_id": "day5.station.new_visual",
        "build_id": "exe-sha256:" + "a" * 64,
        "action_id": "station_queue_and_tram_pass",
        "actual_width": 1920,
        "actual_height": 1080,
        "actual_fps": 60,
        "actual_duration": 31,
        "simulation_rate": 1.0,
        "continuous": True,
        "clean_ui": True,
        "client_area": True,
        "cursor_visible": False,
        "content_seconds": 21,
        "head_handle_seconds": 5,
        "tail_handle_seconds": 5,
        "frame_audit_passed": True,
    }


def _register(tmp_path: Path, facts: dict):
    from dlstudio.services.asset_registry import _register_ingested_captures

    return _register_ingested_captures(tmp_path, [facts])


def test_register_validated_capture_creates_stable_semantic_identity(tmp_path):
    registry = _register(tmp_path, _facts(tmp_path))

    asset = registry.assets[0]
    assert asset.asset_id == "capture:day5_station"
    assert asset.revision == 1
    assert asset.status == "validated"
    assert asset.state_id == "day5.station.new_visual"
    assert asset.artifact_path == "data/footage/day5.mp4"
    assert (tmp_path / "data" / "assets" / "registry.json").is_file()


def test_replacing_approved_capture_invalidates_approval_and_increments_revision(
    tmp_path,
):
    from dlstudio.services.asset_registry import (
        approve_asset,
    )

    first = _facts(tmp_path, content=b"take-one")
    registered = _register(tmp_path, first)
    current = registered.assets[0]
    approved = approve_asset(
        tmp_path,
        "capture:day5_station",
        expected_sha256=first["artifact_sha256"],
        expected_revision=current.revision,
        expected_validation_sha256=current.validation_sha256,
        approved_by="author",
    )
    assert approved.assets[0].status == "approved"

    second = _facts(tmp_path, content=b"take-two")
    updated = _register(tmp_path, second)

    asset = updated.assets[0]
    assert asset.asset_id == "capture:day5_station"
    assert asset.revision == 2
    assert asset.status == "validated"
    assert asset.approved_sha256 is None
    assert asset.approved_at is None


def test_approve_asset_requires_exact_current_sha(tmp_path):
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        approve_asset,
    )

    registered = _register(tmp_path, _facts(tmp_path))
    current = registered.assets[0]

    with pytest.raises(AssetRegistryError, match="SHA mismatch"):
        approve_asset(
            tmp_path,
            "capture:day5_station",
            expected_sha256="0" * 64,
            expected_revision=current.revision,
            expected_validation_sha256=current.validation_sha256,
            approved_by="author",
        )


def test_resolve_approved_asset_rejects_file_changed_after_approval(tmp_path):
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        approve_asset,
        resolve_approved_asset,
    )

    facts = _facts(tmp_path)
    registered = _register(tmp_path, facts)
    current = registered.assets[0]
    approve_asset(
        tmp_path,
        "capture:day5_station",
        expected_sha256=facts["artifact_sha256"],
        expected_revision=current.revision,
        expected_validation_sha256=current.validation_sha256,
        approved_by="author",
    )
    (tmp_path / facts["artifact_path"]).write_bytes(b"changed-after-approval")

    with pytest.raises(AssetRegistryError, match="approved asset is stale"):
        resolve_approved_asset(tmp_path, "capture:day5_station")


def test_semantic_relabel_of_same_file_invalidates_approval(tmp_path):
    from dlstudio.services.asset_registry import (
        approve_asset,
    )

    facts = _facts(tmp_path)
    registered = _register(tmp_path, facts)
    current = registered.assets[0]
    approve_asset(
        tmp_path,
        "capture:day5_station",
        expected_sha256=facts["artifact_sha256"],
        expected_revision=current.revision,
        expected_validation_sha256=current.validation_sha256,
        approved_by="author",
    )
    relabeled = dict(facts, state_id="day4.station.old_visual")

    registry = _register(tmp_path, relabeled)

    assert registry.assets[0].revision == 2
    assert registry.assets[0].status == "validated"
    assert registry.assets[0].approved_sha256 is None


def test_register_validated_captures_is_atomic(tmp_path):
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
    )

    good = _facts(tmp_path)
    missing = dict(
        good,
        request_id="day6_station",
        artifact_path="data/footage/missing.mp4",
    )

    with pytest.raises(AssetRegistryError, match="missing"):
        from dlstudio.services.asset_registry import _register_ingested_captures

        _register_ingested_captures(tmp_path, [good, missing])

    assert not (tmp_path / "data" / "assets" / "registry.json").exists()


def test_approval_rejects_stale_semantic_revision_even_when_media_sha_is_same(
    tmp_path,
):
    from dlstudio.services.asset_registry import AssetRegistryError, approve_asset

    first = _facts(tmp_path)
    old = _register(tmp_path, first).assets[0]
    relabeled = dict(first, state_id="day5.station.corrected")
    current = _register(tmp_path, relabeled).assets[0]

    assert current.artifact_sha256 == old.artifact_sha256
    assert current.revision == old.revision + 1
    with pytest.raises(AssetRegistryError, match="revision mismatch"):
        approve_asset(
            tmp_path,
            current.asset_id,
            expected_sha256=old.artifact_sha256,
            expected_revision=old.revision,
            expected_validation_sha256=old.validation_sha256,
            approved_by="author",
        )


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("capture_method", "deterministic_devapi", "realtime_window"),
        ("build_id", "legacy-source:unknown", "exe-sha256"),
        ("action_id", "", "action_id"),
        ("simulation_rate", 10.0, "simulation_rate"),
        ("continuous", False, "continuous"),
        ("clean_ui", False, "clean_ui"),
        ("client_area", False, "client_area"),
        ("cursor_visible", True, "cursor_visible"),
        ("head_handle_seconds", 0, "head_handle_seconds"),
        ("tail_handle_seconds", 0, "tail_handle_seconds"),
        ("frame_audit_passed", False, "frame_audit"),
    ],
)
def test_ingested_gameplay_rechecks_trusted_contract(
    tmp_path,
    field,
    value,
    message,
):
    from dlstudio.services.asset_registry import AssetRegistryError

    with pytest.raises(AssetRegistryError, match=message):
        _register(tmp_path, dict(_facts(tmp_path), **{field: value}))
