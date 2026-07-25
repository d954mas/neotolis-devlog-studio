from __future__ import annotations

import hashlib
import json
from pathlib import Path
import threading

import pytest


def _facts(tmp_path: Path, *, content: bytes = b"take-one") -> dict:
    artifact = tmp_path / "data" / "footage" / "day5.mp4"
    artifact.parent.mkdir(parents=True, exist_ok=True)
    artifact.write_bytes(content)
    metadata = tmp_path / "data" / "footage" / "day5.mp4.capture.json"
    metadata.write_bytes(b'{"trusted":"recorder"}')
    game_report = tmp_path / "data" / "footage" / "day5.mp4.game.json"
    game_report.write_bytes(b'{"trusted":"game"}')
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
        "game_report_path": "data/footage/day5.mp4.game.json",
        "game_report_sha256": hashlib.sha256(game_report.read_bytes()).hexdigest(),
        "capture_batch_path": "data/plan/capture_batch.json",
        "capture_batch_sha256": hashlib.sha256(batch.read_bytes()).hexdigest(),
        "capture_results_path": "data/plan/capture_results.json",
        "capture_results_sha256": hashlib.sha256(results.read_bytes()).hexdigest(),
        "editorial_role": "gameplay",
        "capture_method": "realtime_window",
        "state_id": "day5.station.new_visual",
        "build_id": "exe-sha256:" + "a" * 64,
        "action_id": "station_queue_and_tram_pass",
        "seed": 42,
        "parameters": {},
        "initial_semantic_hash": "00000001",
        "action_semantic_hash": "00000002",
        "presentation": {
            "fit": "contain",
            "scale": 1.0,
            "source_crop": {
                "x": 0.0,
                "y": 0.0,
                "width": 1920.0,
                "height": 1080.0,
            },
            "focus_rect": None,
            "focus_tolerance_ratio": 0.05,
        },
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
        "game_elapsed_seconds": 31,
        "measured_playback_rate": 1.0,
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


def test_register_and_approve_hash_bound_reference_video(tmp_path, monkeypatch):
    from dlstudio.services.asset_registry import (
        approve_asset,
        register_file_asset,
        resolve_approved_asset,
    )

    artifact = tmp_path / "data" / "footage" / "stock.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"licensed-stock-video")
    monkeypatch.setattr(
        "dlstudio.services.asset_registry._validate_video_artifact",
        lambda path: None,
    )
    registry = register_file_asset(
        tmp_path,
        asset_id="stock:city-01",
        artifact_path="data/footage/stock.mp4",
        editorial_role="reference",
        source_type="stock",
        source_url="https://example.test/video/1",
        license_name="Pexels",
        credit="Example creator",
    )
    current = registry.assets[0]

    approved = approve_asset(
        tmp_path,
        current.asset_id,
        expected_sha256=current.artifact_sha256,
        expected_revision=current.revision,
        expected_validation_sha256=current.validation_sha256,
        approved_by="author",
    )

    assert approved.assets[0].status == "approved"
    assert resolve_approved_asset(tmp_path, current.asset_id) == artifact


def test_generic_registration_rejects_hyperframes_output(tmp_path):
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        register_file_asset,
    )

    artifact = tmp_path / "data" / "infographics" / "draft.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"draft-hyperframes-output")

    with pytest.raises(AssetRegistryError, match="render_manifest"):
        register_file_asset(
            tmp_path,
            asset_id="owned:draft-motion",
            artifact_path="data/infographics/draft.mp4",
            editorial_role="presentation",
            source_type="owned",
        )


def test_generic_registration_rejects_debug_proof_role(tmp_path, monkeypatch):
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        register_file_asset,
    )

    artifact = tmp_path / "data" / "footage" / "debug.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"frame-stepped-debug")
    monkeypatch.setattr(
        "dlstudio.services.asset_registry._validate_video_artifact",
        lambda path: None,
    )

    with pytest.raises(AssetRegistryError, match="deterministic capture ingest"):
        register_file_asset(
            tmp_path,
            asset_id="debug:scene",
            artifact_path="data/footage/debug.mp4",
            editorial_role="debug_proof",
            source_type="owned",
        )


def test_generic_registration_rejects_relocated_hyperframes_output(
    tmp_path,
):
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        register_file_asset,
    )

    artifact = tmp_path / "data" / "footage" / "motion.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"hyperframes-output")
    artifact.with_suffix(".mp4.render.json").write_text(
        '{"schema":"devlog.hyperframes_render/v2"}',
        encoding="utf-8",
    )

    with pytest.raises(AssetRegistryError, match="render_manifest"):
        register_file_asset(
            tmp_path,
            asset_id="owned:relocated-motion",
            artifact_path="data/footage/motion.mp4",
            editorial_role="presentation",
            source_type="owned",
        )


def test_existing_generic_approval_cannot_resolve_hyperframes_output(
    tmp_path,
    monkeypatch,
):
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        _file_validation_sha256,
        approve_asset,
        register_file_asset,
        resolve_approved_asset,
    )

    original = tmp_path / "data" / "footage" / "motion.mp4"
    original.parent.mkdir(parents=True)
    original.write_bytes(b"legacy-draft-hyperframes-output")
    monkeypatch.setattr(
        "dlstudio.services.asset_registry._validate_video_artifact",
        lambda path: None,
    )
    current = register_file_asset(
        tmp_path,
        asset_id="owned:legacy-motion",
        artifact_path="data/footage/motion.mp4",
        editorial_role="presentation",
        source_type="owned",
    ).assets[0]
    approve_asset(
        tmp_path,
        current.asset_id,
        expected_sha256=current.artifact_sha256,
        expected_revision=current.revision,
        expected_validation_sha256=current.validation_sha256,
        approved_by="legacy",
    )

    moved = tmp_path / "data" / "infographics" / "motion.mp4"
    moved.parent.mkdir(parents=True)
    moved.write_bytes(original.read_bytes())
    registry_path = tmp_path / "data" / "assets" / "registry.json"
    registry = json.loads(registry_path.read_text(encoding="utf-8"))
    row = registry["assets"][0]
    provenance = tmp_path / row["provenance_path"]
    proof = json.loads(provenance.read_text(encoding="utf-8"))
    proof["artifact_path"] = "data/infographics/motion.mp4"
    provenance.write_text(json.dumps(proof), encoding="utf-8")
    provenance_sha = hashlib.sha256(provenance.read_bytes()).hexdigest()
    validation_sha = _file_validation_sha256(
        artifact_path="data/infographics/motion.mp4",
        artifact_sha256=row["artifact_sha256"],
        editorial_role=row["editorial_role"],
        provenance_path=row["provenance_path"],
        provenance_sha256=provenance_sha,
    )
    row["artifact_path"] = "data/infographics/motion.mp4"
    row["provenance_sha256"] = provenance_sha
    row["validation_sha256"] = validation_sha
    row["approved_validation_sha256"] = validation_sha
    registry_path.write_text(json.dumps(registry), encoding="utf-8")

    with pytest.raises(AssetRegistryError, match="render_manifest"):
        resolve_approved_asset(tmp_path, current.asset_id)


def test_existing_generic_approval_rejects_adjacent_hyperframes_manifest(
    tmp_path,
    monkeypatch,
):
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        approve_asset,
        register_file_asset,
        resolve_approved_asset,
    )

    artifact = tmp_path / "data" / "footage" / "motion.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"motion")
    monkeypatch.setattr(
        "dlstudio.services.asset_registry._validate_video_artifact",
        lambda path: None,
    )
    current = register_file_asset(
        tmp_path,
        asset_id="owned:motion",
        artifact_path="data/footage/motion.mp4",
        editorial_role="presentation",
        source_type="owned",
    ).assets[0]
    approve_asset(
        tmp_path,
        current.asset_id,
        expected_sha256=current.artifact_sha256,
        expected_revision=current.revision,
        expected_validation_sha256=current.validation_sha256,
        approved_by="author",
    )
    artifact.with_suffix(".mp4.render.json").write_text(
        '{"schema":"devlog.hyperframes_render/v2"}',
        encoding="utf-8",
    )

    with pytest.raises(AssetRegistryError, match="render_manifest"):
        resolve_approved_asset(tmp_path, current.asset_id)


def test_approved_reference_fails_when_provenance_changes(tmp_path, monkeypatch):
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        approve_asset,
        register_file_asset,
        resolve_approved_asset,
    )

    artifact = tmp_path / "data" / "footage" / "owned.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"owned-video")
    monkeypatch.setattr(
        "dlstudio.services.asset_registry._validate_video_artifact",
        lambda path: None,
    )
    current = register_file_asset(
        tmp_path,
        asset_id="owned:broll",
        artifact_path="data/footage/owned.mp4",
        editorial_role="reference",
        source_type="owned",
    ).assets[0]
    approve_asset(
        tmp_path,
        current.asset_id,
        expected_sha256=current.artifact_sha256,
        expected_revision=current.revision,
        expected_validation_sha256=current.validation_sha256,
        approved_by="author",
    )
    provenance = tmp_path / current.provenance_path
    provenance.write_bytes(b"changed")

    with pytest.raises(AssetRegistryError, match="provenance is stale"):
        resolve_approved_asset(tmp_path, current.asset_id)


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


def test_resolve_approved_gameplay_rechecks_proof_files(tmp_path):
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        approve_asset,
        resolve_approved_asset,
    )

    facts = _facts(tmp_path)
    current = _register(tmp_path, facts).assets[0]
    approve_asset(
        tmp_path,
        current.asset_id,
        expected_sha256=current.artifact_sha256,
        expected_revision=current.revision,
        expected_validation_sha256=current.validation_sha256,
        approved_by="author",
    )
    (tmp_path / facts["game_report_path"]).write_bytes(b"changed")

    with pytest.raises(AssetRegistryError, match="game capture report is stale"):
        resolve_approved_asset(tmp_path, current.asset_id)


def test_legacy_approved_gameplay_without_new_proof_fails_closed(tmp_path):
    import json

    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        approve_asset,
        resolve_approved_asset,
    )

    facts = _facts(tmp_path)
    current = _register(tmp_path, facts).assets[0]
    approve_asset(
        tmp_path,
        current.asset_id,
        expected_sha256=current.artifact_sha256,
        expected_revision=current.revision,
        expected_validation_sha256=current.validation_sha256,
        approved_by="author",
    )
    registry_path = tmp_path / "data" / "assets" / "registry.json"
    payload = json.loads(registry_path.read_text(encoding="utf-8"))
    payload["assets"][0]["game_report_path"] = None
    payload["assets"][0]["game_report_sha256"] = None
    payload["assets"][0]["measured_playback_rate"] = None
    registry_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(AssetRegistryError, match="lacks game capture report"):
        resolve_approved_asset(tmp_path, current.asset_id)


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


def test_concurrent_ingest_cannot_be_overwritten_by_stale_approval(
    tmp_path,
    monkeypatch,
):
    from dlstudio.services import asset_registry

    first = _facts(tmp_path)
    current = _register(tmp_path, first).assets[0]
    entered = threading.Event()
    release = threading.Event()
    original_verify = asset_registry._verify_registered_asset

    def delayed_verify(root, asset):
        entered.set()
        assert release.wait(timeout=5)
        return original_verify(root, asset)

    monkeypatch.setattr(asset_registry, "_verify_registered_asset", delayed_verify)
    errors: list[BaseException] = []

    def approve():
        try:
            asset_registry.approve_asset(
                tmp_path,
                current.asset_id,
                expected_sha256=current.artifact_sha256,
                expected_revision=current.revision,
                expected_validation_sha256=current.validation_sha256,
                approved_by="author",
            )
        except BaseException as exc:  # pragma: no cover - assertion reports below
            errors.append(exc)

    def ingest():
        try:
            _register(tmp_path, dict(first, state_id="day5.station.corrected"))
        except BaseException as exc:  # pragma: no cover - assertion reports below
            errors.append(exc)

    approval_thread = threading.Thread(target=approve)
    approval_thread.start()
    assert entered.wait(timeout=5)
    ingest_thread = threading.Thread(target=ingest)
    ingest_thread.start()
    release.set()
    approval_thread.join(timeout=5)
    ingest_thread.join(timeout=5)

    assert not errors
    final = asset_registry.load_asset_registry(tmp_path).assets[0]
    assert final.revision == current.revision + 1
    assert final.status == "validated"


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("capture_method", "deterministic_devapi", "realtime_window"),
        ("build_id", "legacy-source:unknown", "exe-sha256"),
        ("simulation_rate", 10.0, "simulation_rate"),
        ("continuous", False, "continuous"),
        ("clean_ui", False, "clean_ui"),
        ("client_area", False, "client_area"),
        ("cursor_visible", True, "cursor_visible"),
        ("head_handle_seconds", 0, "head_handle_seconds"),
        ("tail_handle_seconds", 0, "tail_handle_seconds"),
        ("frame_audit_passed", False, "frame_audit"),
        ("measured_playback_rate", 10.0, "real-time playback"),
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
