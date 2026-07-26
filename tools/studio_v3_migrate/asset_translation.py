"""Offline v2 asset/capture translator.

The translator is intentionally fail-closed.  It emits a plan; runtime code
never imports or reads these legacy schemas.
"""

from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path
from typing import Any


class AssetTranslationError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _asset_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.casefold()).strip("-")
    if not normalized:
        raise AssetTranslationError(f"cannot canonicalize asset id {value!r}")
    return normalized


def _inside_production(root: Path, raw: str) -> Path:
    path = Path(raw)
    candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AssetTranslationError(
            f"legacy asset escapes production root: {raw}"
        ) from exc
    return candidate


def _inspect_path(root: Path, raw: str, expected_hash: str) -> list[str]:
    blockers: list[str] = []
    try:
        path = _inside_production(root, raw)
    except AssetTranslationError as exc:
        return [str(exc)]
    if not path.is_file():
        return ["source_missing"]
    try:
        actual = _sha256(path)
    except OSError as exc:
        return [f"source_unreadable:{exc.__class__.__name__}"]
    if actual != expected_hash.casefold():
        blockers.append("source_hash_mismatch")
    return blockers


def _verify_proof(root: Path, raw: Any, expected_hash: Any) -> bool:
    if (
        not isinstance(raw, str)
        or not isinstance(expected_hash, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", expected_hash) is None
    ):
        return False
    try:
        path = _inside_production(root, raw)
        return path.is_file() and _sha256(path) == expected_hash.casefold()
    except (AssetTranslationError, OSError):
        return False


def _verified_json_proof(
    root: Path, raw: Any, expected_hash: Any
) -> dict[str, Any] | None:
    if not _verify_proof(root, raw, expected_hash):
        return None
    try:
        path = _inside_production(root, str(raw))
        value = json.loads(path.read_text(encoding="utf-8"))
    except (AssetTranslationError, OSError, UnicodeDecodeError, json.JSONDecodeError):
        return None
    return value if isinstance(value, dict) else None


def _capture_proof_chain_valid(
    root: Path, value: dict[str, Any]
) -> bool:
    metadata = _verified_json_proof(
        root, value.get("metadata_path"), value.get("metadata_sha256")
    )
    results = _verified_json_proof(
        root,
        value.get("capture_results_path"),
        value.get("capture_results_sha256"),
    )
    batch = _verified_json_proof(
        root,
        value.get("capture_batch_path"),
        value.get("capture_batch_sha256"),
    )
    if not all((metadata, results, batch)):
        return False
    request_id = value.get("request_id") or str(value.get("asset_id", "")).removeprefix(
        "capture:"
    )
    identity = {
        "request_id": request_id,
        "artifact_sha256": value.get("artifact_sha256"),
        "capture_method": value.get("capture_method"),
        "state_id": value.get("state_id"),
        "build_id": value.get("build_id"),
    }
    if not (
        metadata.get("schema") == "dlstudio.capture_metadata"
        and metadata.get("version") == 2
        and all(metadata.get(key) == expected for key, expected in identity.items())
    ):
        return False
    if not (
        results.get("schema") == "dlstudio.capture_results"
        and results.get("version") == 2
        and any(
            isinstance(item, dict)
            and all(item.get(key) == expected for key, expected in identity.items())
            for item in results.get("results", [])
        )
    ):
        return False
    return (
        batch.get("schema") == "dlstudio.capture_batch"
        and batch.get("version") == 2
        and any(
            isinstance(item, dict)
            and item.get("request_id") == request_id
            and item.get("capture_method") == value.get("capture_method")
            and item.get("state_id") == value.get("state_id")
            and item.get("build_id") == value.get("build_id")
            for item in batch.get("requests", [])
        )
    )


def _license_evidence_valid(root: Path, legacy_license: Any) -> bool:
    if not isinstance(legacy_license, dict):
        return False
    evidence = _verified_json_proof(
        root,
        legacy_license.get("evidence_path"),
        legacy_license.get("evidence_sha256"),
    )
    if evidence is None:
        return False
    return (
        evidence.get("schema") == "dlstudio.license_evidence"
        and evidence.get("version") == 1
        and evidence.get("license_id") == legacy_license.get("license_id")
        and evidence.get("attribution_required")
        == legacy_license.get("attribution_required")
        and evidence.get("attribution") == legacy_license.get("attribution")
    )


def translate_asset_schemas(production_root: Path) -> dict[str, Any]:
    root = production_root.resolve()
    registry_path = root / "data" / "assets" / "registry.json"
    catalog_path = root / "data" / "assets" / "catalog.json"
    records: list[dict[str, Any]] = []
    seen: dict[str, str] = {}

    if registry_path.is_file():
        payload = json.loads(registry_path.read_text(encoding="utf-8"))
        if payload.get("version") != 1 or not isinstance(payload.get("assets"), list):
            raise AssetTranslationError("unsupported legacy asset registry")
        for value in payload["assets"]:
            legacy_id = str(value["asset_id"])
            asset_id = _asset_id(legacy_id)
            blockers = _inspect_path(
                root,
                str(value["artifact_path"]),
                str(value["artifact_sha256"]).casefold(),
            )
            capture_method = value.get("capture_method")
            if capture_method != "file":
                if not _capture_proof_chain_valid(root, value):
                    blockers.append("capture_proof_chain_incomplete")
            else:
                file_provenance = _verified_json_proof(
                    root,
                    value.get("provenance_path"),
                    value.get("provenance_sha256"),
                )
                if not (
                    file_provenance
                    and file_provenance.get("schema")
                    in {"devlog.video_provenance", "devlog.audio_provenance"}
                    and file_provenance.get("version") == 1
                    and file_provenance.get("artifact_path")
                    == str(value["artifact_path"]).replace("\\", "/")
                    and file_provenance.get("artifact_sha256")
                    == value.get("artifact_sha256")
                ):
                    blockers.append("file_provenance_chain_incomplete")
            if value.get("capture_method") == "realtime_window" and (
                (value.get("head_handle_seconds") or 0) < 5
                or (value.get("tail_handle_seconds") or 0) < 5
            ):
                blockers.append("gameplay_handles_below_contract")
            if value.get("capture_method") == "realtime_window" and not all(
                (
                    value.get("state_id"),
                    value.get("build_id"),
                    value.get("width"),
                    value.get("height"),
                )
            ):
                blockers.append("gameplay_identity_incomplete")
            if value.get("status") == "approved":
                approval_binding_valid = (
                    isinstance(value.get("validation_sha256"), str)
                    and re.fullmatch(
                        r"[0-9a-fA-F]{64}",
                        value["validation_sha256"],
                    )
                    is not None
                    and value.get("approved_sha256")
                    == value.get("artifact_sha256")
                    and value.get("approved_validation_sha256")
                    == value.get("validation_sha256")
                )
                approval_evidence = _verified_json_proof(
                    root,
                    value.get("approval_evidence_path"),
                    value.get("approval_evidence_sha256"),
                )
                approval_evidence_valid = bool(
                    approval_evidence
                    and approval_evidence.get("schema")
                    == "dlstudio.asset_validation"
                    and approval_evidence.get("version") == 1
                    and approval_evidence.get("artifact_sha256")
                    == value.get("artifact_sha256")
                    and approval_evidence.get("validation_sha256")
                    == value.get("validation_sha256")
                )
                if not approval_binding_valid:
                    blockers.append("approval_binding_invalid")
                if not approval_evidence_valid:
                    blockers.append("approval_evidence_missing")
            if value.get("width") is None and value.get("duration") is None:
                blockers.append("media_facts_incomplete")
            legacy_license = value.get("license")
            license_shape_valid = (
                isinstance(legacy_license, dict)
                and isinstance(legacy_license.get("license_id"), str)
                and bool(legacy_license["license_id"])
                and isinstance(
                    legacy_license.get("attribution_required"), bool
                )
                and (
                    legacy_license.get("attribution_required") is False
                    or (
                        isinstance(legacy_license.get("attribution"), str)
                        and bool(legacy_license["attribution"].strip())
                    )
                )
            )
            license_valid = license_shape_valid and _license_evidence_valid(
                root, legacy_license
            )
            if not license_valid:
                blockers.append("license_evidence_incomplete")
            if asset_id in seen and seen[asset_id] != legacy_id:
                blockers.append("canonical_asset_id_collision")
            seen[asset_id] = legacy_id
            records.append(
                {
                    "legacy_schema": "asset_registry.v1",
                    "legacy_asset_id": legacy_id,
                    "asset_id": asset_id,
                    "artifact_path": str(value["artifact_path"]).replace("\\", "/"),
                    "artifact_sha256": str(value["artifact_sha256"]).casefold(),
                    "media": {
                        "width": value.get("width"),
                        "height": value.get("height"),
                        "duration_seconds": value.get("duration"),
                        "fps": value.get("fps"),
                    },
                    "capture": {
                        "method": value.get("capture_method"),
                        "state_id": value.get("state_id"),
                        "build_id": value.get("build_id"),
                    },
                    "legacy_approval": value.get("status"),
                    "legacy_license": legacy_license,
                    "disposition": (
                        "TRANSLATE" if not blockers else "BLOCKED_ARCHIVE_READ_ONLY"
                    ),
                    "blockers": sorted(set(blockers)),
                }
            )

    if catalog_path.is_file():
        payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        if payload.get("version") != 1 or not isinstance(payload.get("assets"), list):
            raise AssetTranslationError("unsupported legacy asset catalog")
        for value in payload["assets"]:
            raw_path = str(value["path"])
            legacy_id = f"catalog:{raw_path}"
            asset_id = _asset_id(
                "catalog-" + hashlib.sha256(raw_path.encode("utf-8")).hexdigest()[:20]
            )
            blockers = _inspect_path(
                root, raw_path, str(value["sha256"]).casefold()
            )
            provenance = str(value.get("provenance") or "unknown")
            if provenance == "unknown":
                blockers.append("provenance_missing")
            blockers.append("license_missing")
            records.append(
                {
                    "legacy_schema": "asset_catalog.v1",
                    "legacy_asset_id": legacy_id,
                    "asset_id": asset_id,
                    "artifact_path": raw_path.replace("\\", "/"),
                    "artifact_sha256": str(value["sha256"]).casefold(),
                    "media": {
                        "kind": value.get("kind"),
                        "width": value.get("width"),
                        "height": value.get("height"),
                        "duration_seconds": value.get("duration"),
                        "fps": value.get("fps"),
                    },
                    "legacy_provenance": provenance,
                    "disposition": (
                        "TRANSLATE" if not blockers else "BLOCKED_ARCHIVE_READ_ONLY"
                    ),
                    "blockers": sorted(set(blockers)),
                }
            )

    records.sort(key=lambda item: (item["asset_id"], item["legacy_asset_id"]))
    collision_ids = {
        asset_id
        for asset_id in {item["asset_id"] for item in records}
        if len(
            {
                item["legacy_asset_id"]
                for item in records
                if item["asset_id"] == asset_id
            }
        )
        > 1
    }
    for item in records:
        if item["asset_id"] in collision_ids:
            item["blockers"] = sorted(
                set(item["blockers"]) | {"canonical_asset_id_collision"}
            )
            item["disposition"] = "BLOCKED_ARCHIVE_READ_ONLY"
    unique_sources: dict[Path, int] = {}
    for item in records:
        try:
            source = _inside_production(root, item["artifact_path"])
            if source.is_file():
                unique_sources[source] = source.stat().st_size
        except (AssetTranslationError, OSError):
            pass
    translatable_sources = {
        _inside_production(root, item["artifact_path"])
        for item in records
        if item["disposition"] == "TRANSLATE"
    }
    return {
        "schema": "studio_v3.asset_translation_plan",
        "version": 1,
        "production_root": root.as_posix(),
        "sources": {
            "registry": registry_path.is_file(),
            "catalog": catalog_path.is_file(),
        },
        "records": records,
        "summary": {
            "total": len(records),
            "translatable": sum(
                item["disposition"] == "TRANSLATE" for item in records
            ),
            "blocked": sum(
                item["disposition"] == "BLOCKED_ARCHIVE_READ_ONLY"
                for item in records
            ),
            "unique_source_files": len(unique_sources),
            "unique_source_bytes": sum(unique_sources.values()),
            "required_copy_bytes": sum(
                unique_sources.get(source, 0)
                for source in translatable_sources
            ),
        },
    }
