from __future__ import annotations

import hashlib
import json
from pathlib import Path

from tools.studio_v3_migrate.asset_translation import translate_asset_schemas


def test_legacy_asset_translation_is_fail_closed_and_deterministic(
    tmp_path: Path,
) -> None:
    production = tmp_path / "production"
    artifact = production / "data" / "footage" / "clip.mp4"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"clip")
    registry = production / "data" / "assets" / "registry.json"
    registry.parent.mkdir(parents=True)
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "assets": [
                    {
                        "asset_id": "capture:main",
                        "artifact_path": "data/footage/clip.mp4",
                        "artifact_sha256": hashlib.sha256(b"clip").hexdigest(),
                        "status": "approved",
                        "capture_method": "realtime_window",
                        "state_id": "state",
                        "build_id": "build",
                        "width": 1080,
                        "height": 1920,
                        "duration": 5.0,
                        "fps": 30.0,
                        "head_handle_seconds": 0,
                        "tail_handle_seconds": 0,
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    first = translate_asset_schemas(production)
    second = translate_asset_schemas(production)
    assert first == second
    record = first["records"][0]
    assert record["asset_id"] == "capture-main"
    assert record["disposition"] == "BLOCKED_ARCHIVE_READ_ONLY"
    assert "capture_proof_chain_incomplete" in record["blockers"]
    assert "gameplay_handles_below_contract" in record["blockers"]
    assert "license_evidence_incomplete" in record["blockers"]


def test_every_canonical_id_collision_member_is_blocked(tmp_path: Path) -> None:
    production = tmp_path / "production"
    artifact = production / "data" / "clip.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"clip")
    sha = hashlib.sha256(b"clip").hexdigest()
    registry = production / "data" / "assets" / "registry.json"
    registry.parent.mkdir(parents=True)
    base = {
        "artifact_path": "data/clip.bin",
        "artifact_sha256": sha,
        "status": "pending",
        "capture_method": "file",
        "width": 1,
        "duration": None,
        "license": "owned",
    }
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "assets": [
                    {**base, "asset_id": "same:id"},
                    {**base, "asset_id": "same id"},
                ],
            }
        ),
        encoding="utf-8",
    )
    records = translate_asset_schemas(production)["records"]
    assert len(records) == 2
    assert all(
        record["disposition"] == "BLOCKED_ARCHIVE_READ_ONLY"
        and "canonical_asset_id_collision" in record["blockers"]
        for record in records
    )


def test_known_hash_bound_file_provenance_and_license_can_translate(
    tmp_path: Path,
) -> None:
    production = tmp_path / "production"
    artifact = production / "data" / "clip.bin"
    artifact.parent.mkdir(parents=True)
    artifact.write_bytes(b"clip")
    artifact_sha = hashlib.sha256(b"clip").hexdigest()
    proof_dir = production / "data" / "assets" / "proof"
    proof_dir.mkdir(parents=True)

    provenance = {
        "schema": "devlog.video_provenance",
        "version": 1,
        "artifact_path": "data/clip.bin",
        "artifact_sha256": artifact_sha,
    }
    provenance_path = proof_dir / "provenance.json"
    provenance_path.write_text(json.dumps(provenance), encoding="utf-8")
    license_proof = {
        "schema": "dlstudio.license_evidence",
        "version": 1,
        "license_id": "owned",
        "attribution_required": False,
        "attribution": None,
    }
    license_path = proof_dir / "license.json"
    license_path.write_text(json.dumps(license_proof), encoding="utf-8")
    registry = production / "data" / "assets" / "registry.json"
    registry.write_text(
        json.dumps(
            {
                "version": 1,
                "assets": [
                    {
                        "asset_id": "clip.main",
                        "artifact_path": "data/clip.bin",
                        "artifact_sha256": artifact_sha,
                        "status": "pending",
                        "capture_method": "file",
                        "width": 1,
                        "duration": None,
                        "provenance_path": "data/assets/proof/provenance.json",
                        "provenance_sha256": hashlib.sha256(
                            provenance_path.read_bytes()
                        ).hexdigest(),
                        "license": {
                            "license_id": "owned",
                            "attribution_required": False,
                            "attribution": None,
                            "evidence_path": "data/assets/proof/license.json",
                            "evidence_sha256": hashlib.sha256(
                                license_path.read_bytes()
                            ).hexdigest(),
                        },
                    }
                ],
            }
        ),
        encoding="utf-8",
    )
    record = translate_asset_schemas(production)["records"][0]
    assert record["disposition"] == "TRANSLATE"
    assert record["blockers"] == []
