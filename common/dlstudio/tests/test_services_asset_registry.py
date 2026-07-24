from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


def _facts(tmp_path: Path, *, content: bytes = b"take-one") -> dict:
    artifact = tmp_path / "data" / "footage" / "day5.mp4"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(content)
    return {
        "request_id": "day5_station",
        "artifact_path": "data/footage/day5.mp4",
        "artifact_sha256": hashlib.sha256(content).hexdigest(),
        "editorial_role": "gameplay",
        "capture_method": "realtime_window",
        "state_id": "day5.station.new_visual",
        "build_id": "git:abc123",
        "actual_width": 1920,
        "actual_height": 1080,
        "actual_fps": 60,
        "actual_duration": 31,
        "head_handle_seconds": 5,
        "tail_handle_seconds": 5,
    }


def test_register_validated_capture_creates_stable_semantic_identity(tmp_path):
    from dlstudio.services.asset_registry import register_validated_capture

    registry = register_validated_capture(tmp_path, _facts(tmp_path))

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
        register_validated_capture,
    )

    first = _facts(tmp_path, content=b"take-one")
    register_validated_capture(tmp_path, first)
    approved = approve_asset(
        tmp_path,
        "capture:day5_station",
        expected_sha256=first["artifact_sha256"],
        approved_by="author",
    )
    assert approved.assets[0].status == "approved"

    second = _facts(tmp_path, content=b"take-two")
    updated = register_validated_capture(tmp_path, second)

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
        register_validated_capture,
    )

    register_validated_capture(tmp_path, _facts(tmp_path))

    with pytest.raises(AssetRegistryError, match="SHA mismatch"):
        approve_asset(
            tmp_path,
            "capture:day5_station",
            expected_sha256="0" * 64,
            approved_by="author",
        )


def test_resolve_approved_asset_rejects_file_changed_after_approval(tmp_path):
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        approve_asset,
        register_validated_capture,
        resolve_approved_asset,
    )

    facts = _facts(tmp_path)
    register_validated_capture(tmp_path, facts)
    approve_asset(
        tmp_path,
        "capture:day5_station",
        expected_sha256=facts["artifact_sha256"],
        approved_by="author",
    )
    (tmp_path / facts["artifact_path"]).write_bytes(b"changed-after-approval")

    with pytest.raises(AssetRegistryError, match="approved asset is stale"):
        resolve_approved_asset(tmp_path, "capture:day5_station")


def test_semantic_relabel_of_same_file_invalidates_approval(tmp_path):
    from dlstudio.services.asset_registry import (
        approve_asset,
        register_validated_capture,
    )

    facts = _facts(tmp_path)
    register_validated_capture(tmp_path, facts)
    approve_asset(
        tmp_path,
        "capture:day5_station",
        expected_sha256=facts["artifact_sha256"],
        approved_by="author",
    )
    relabeled = dict(facts, state_id="day4.station.old_visual")

    registry = register_validated_capture(tmp_path, relabeled)

    assert registry.assets[0].revision == 2
    assert registry.assets[0].status == "validated"
    assert registry.assets[0].approved_sha256 is None


def test_register_validated_captures_is_atomic(tmp_path):
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        register_validated_captures,
    )

    good = _facts(tmp_path)
    missing = dict(
        good,
        request_id="day6_station",
        artifact_path="data/footage/missing.mp4",
    )

    with pytest.raises(AssetRegistryError, match="missing"):
        register_validated_captures(tmp_path, [good, missing])

    assert not (tmp_path / "data" / "assets" / "registry.json").exists()
