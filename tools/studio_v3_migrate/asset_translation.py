"""Fail-closed, location-independent migration of legacy asset schemas."""

from __future__ import annotations

import hashlib
import json
import re
import subprocess
import tomllib
from collections import Counter
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from dlstudio.adapters.providers import FfprobeMediaInspector
from dlstudio.assets.api import (
    Approval,
    AssetRevision,
    License,
    MediaFacts,
    Provenance,
)
from dlstudio.foundation.api import BlobRef, CasConflict, DomainId
from dlstudio.persistence import ProductionRepository
from dlstudio.persistence.assets import AssetRepository


class AssetTranslationError(ValueError):
    pass


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _json_hash(value: Any) -> str:
    try:
        raw = json.dumps(
            value,
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
            sort_keys=True,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise AssetTranslationError("value is not canonical JSON") from exc
    return hashlib.sha256(raw).hexdigest()


def _asset_id(value: str) -> str:
    normalized = re.sub(r"[^a-z0-9._-]+", "-", value.casefold()).strip("-")
    if not normalized:
        raise AssetTranslationError(f"cannot canonicalize asset id {value!r}")
    return str(DomainId(normalized))


def _production_id(root: Path, explicit: str | None = None) -> str | None:
    manifest = root / "production.toml"
    if not manifest.is_file():
        if explicit is None:
            return None
        try:
            return str(DomainId(explicit))
        except ValueError as exc:
            raise AssetTranslationError("invalid explicit production id") from exc
    try:
        payload = tomllib.loads(manifest.read_text(encoding="utf-8"))
        value = payload["id"]
    except (KeyError, OSError, UnicodeDecodeError, tomllib.TOMLDecodeError) as exc:
        raise AssetTranslationError("invalid production.toml identity") from exc
    if not isinstance(value, str):
        raise AssetTranslationError("production.toml id must be a string")
    try:
        manifest_id = str(DomainId(value))
    except ValueError as exc:
        raise AssetTranslationError("invalid production.toml id") from exc
    if explicit is not None:
        try:
            explicit_id = str(DomainId(explicit))
        except ValueError as exc:
            raise AssetTranslationError("invalid explicit production id") from exc
        if explicit_id != manifest_id:
            raise AssetTranslationError(
                "explicit production id does not match production.toml"
            )
    return manifest_id


def _contained(root: Path, raw: str) -> Path:
    path = Path(raw)
    candidate = path.resolve() if path.is_absolute() else (root / path).resolve()
    try:
        candidate.relative_to(root)
    except ValueError as exc:
        raise AssetTranslationError(f"path escapes production root: {raw}") from exc
    return candidate


def _bind_file(root: Path, raw: str) -> dict[str, Any]:
    path = _contained(root, raw)
    logical = path.relative_to(root).as_posix()
    if not path.exists():
        return {"path": logical, "present": False}
    if not path.is_file():
        raise AssetTranslationError(f"bound path is not a file: {raw}")
    return {
        "path": logical,
        "present": True,
        "sha256": _sha256(path),
        "size": path.stat().st_size,
    }


def _verify_binding(
    root: Path,
    binding: Mapping[str, Any],
    *,
    label: str,
) -> Path | None:
    raw = binding.get("path")
    if not isinstance(raw, str):
        raise AssetTranslationError(f"{label} path is missing")
    path = _contained(root, raw)
    present = binding.get("present")
    if present is False:
        if path.exists():
            raise AssetTranslationError(f"{label} appeared after planning: {raw}")
        return None
    if present is not True:
        raise AssetTranslationError(f"{label} has invalid presence binding")
    if not path.is_file():
        raise AssetTranslationError(f"{label} is missing: {raw}")
    try:
        expected = BlobRef.from_payload(binding)
    except (KeyError, TypeError, ValueError) as exc:
        raise AssetTranslationError(f"{label} has invalid byte binding") from exc
    if path.stat().st_size != expected.size or _sha256(path) != expected.sha256:
        raise AssetTranslationError(f"{label} hash mismatch: {raw}")
    return path


def _binding_ref(binding: Mapping[str, Any]) -> BlobRef:
    if binding.get("present") is not True:
        raise AssetTranslationError("required evidence is absent")
    try:
        return BlobRef.from_payload(binding)
    except (KeyError, TypeError, ValueError) as exc:
        raise AssetTranslationError("invalid evidence byte binding") from exc


def _proof(
    root: Path,
    raw_path: Any,
    raw_sha256: Any,
) -> tuple[dict[str, Any], dict[str, Any]] | None:
    if (
        not isinstance(raw_path, str)
        or not isinstance(raw_sha256, str)
        or re.fullmatch(r"[0-9a-fA-F]{64}", raw_sha256) is None
    ):
        return None
    try:
        binding = _bind_file(root, raw_path)
        if (
            binding.get("present") is not True
            or binding["sha256"] != raw_sha256.casefold()
        ):
            return None
        path = _contained(root, raw_path)
        value = json.loads(path.read_text(encoding="utf-8"))
    except (
        AssetTranslationError,
        OSError,
        UnicodeDecodeError,
        json.JSONDecodeError,
    ):
        return None
    return (binding, value) if isinstance(value, dict) else None


def _capture_proofs(
    root: Path,
    value: Mapping[str, Any],
) -> list[tuple[str, dict[str, Any]]] | None:
    specs = (
        ("capture_metadata", "metadata_path", "metadata_sha256"),
        ("capture_results", "capture_results_path", "capture_results_sha256"),
        ("capture_batch", "capture_batch_path", "capture_batch_sha256"),
    )
    proofs = [
        (role, _proof(root, value.get(path_key), value.get(hash_key)))
        for role, path_key, hash_key in specs
    ]
    if any(proof is None for _role, proof in proofs):
        return None
    loaded = [(role, proof[0], proof[1]) for role, proof in proofs if proof]
    metadata, results, batch = [item[2] for item in loaded]
    request_id = value.get("request_id") or str(
        value.get("asset_id", "")
    ).removeprefix("capture:")
    identity = {
        "request_id": request_id,
        "artifact_sha256": value.get("artifact_sha256"),
        "capture_method": value.get("capture_method"),
        "state_id": value.get("state_id"),
        "build_id": value.get("build_id"),
    }
    valid = (
        metadata.get("schema") == "dlstudio.capture_metadata"
        and metadata.get("version") == 2
        and all(metadata.get(key) == expected for key, expected in identity.items())
        and results.get("schema") == "dlstudio.capture_results"
        and results.get("version") == 2
        and any(
            isinstance(item, dict)
            and all(item.get(key) == expected for key, expected in identity.items())
            for item in results.get("results", [])
        )
        and batch.get("schema") == "dlstudio.capture_batch"
        and batch.get("version") == 2
        and any(
            isinstance(item, dict)
            and item.get("request_id") == request_id
            and all(item.get(key) == value.get(key) for key in (
                "capture_method", "state_id", "build_id"
            ))
            for item in batch.get("requests", [])
        )
    )
    return [(role, binding) for role, binding, _payload in loaded] if valid else None


def _matching_proof(
    root: Path,
    raw_path: Any,
    raw_sha256: Any,
    expected: Mapping[str, Any],
) -> dict[str, Any] | None:
    proof = _proof(root, raw_path, raw_sha256)
    if proof is None:
        return None
    binding, evidence = proof
    return binding if all(evidence.get(key) == value for key, value in expected.items()) else None


def _target(
    value: Mapping[str, Any],
    *,
    asset_id: str,
    source: Mapping[str, Any],
    media: MediaFacts,
    provenance_proofs: list[tuple[str, dict[str, Any]]],
    license_proof: dict[str, Any],
    approval_proof: dict[str, Any] | None,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    evidence = [{"role": role, **binding} for role, binding in provenance_proofs]
    evidence.append({"role": "license", **license_proof})
    if approval_proof is not None:
        evidence.append({"role": "approval", **approval_proof})
    capture_method = str(value.get("capture_method") or "file")
    provenance_refs = [_binding_ref(item[1]) for item in provenance_proofs]
    recorded = capture_method != "file"
    provenance = Provenance(
        origin="recorded" if recorded else "provided",
        capture_method=capture_method,
        logical_source=str(value["artifact_path"]).replace("\\", "/"),
        state_id=value.get("state_id"),
        build_id=value.get("build_id"),
        native_width=(
            int(value["width"]) if recorded and value.get("width") is not None else None
        ),
        native_height=(
            int(value["height"]) if recorded and value.get("height") is not None else None
        ),
        provider_receipt_ref=provenance_refs[0] if recorded else None,
        supporting_evidence=(
            tuple(provenance_refs[1:]) if recorded else tuple(provenance_refs)
        ),
    )
    approval = Approval(
        "approved" if value.get("status") == "approved" else "pending",
        () if approval_proof is None else (_binding_ref(approval_proof),),
    )
    legacy_license = value["license"]
    license_value = License(
        license_id=str(legacy_license["license_id"]),
        attribution_required=bool(legacy_license["attribution_required"]),
        attribution=legacy_license.get("attribution"),
        redistribution_allowed=legacy_license["redistribution_allowed"],
        evidence_ref=_binding_ref(license_proof),
    )
    revision = AssetRevision(
        asset_id, _binding_ref(source), media, provenance, approval, license_value
    )
    target = {**revision.as_payload(), "revision": revision.ref.as_payload()}
    return target, evidence


def _registry_record(
    root: Path,
    value: Mapping[str, Any],
    inspector: Callable[[Path], MediaFacts],
) -> dict[str, Any]:
    legacy_id = str(value["asset_id"])
    asset_id = _asset_id(legacy_id)
    raw_path = str(value["artifact_path"])
    blockers: list[str] = []

    def block(condition: bool, name: str) -> None:
        if condition:
            blockers.append(name)

    try:
        source = _bind_file(root, raw_path)
    except AssetTranslationError:
        source = {
            "path": raw_path.replace("\\", "/"),
            "present": False,
            "unsafe": True,
        }
        blockers.append("source_path_unsafe")
    declared_sha = str(value.get("artifact_sha256", "")).casefold()
    block(source.get("present") is not True, "source_missing")
    block(
        source.get("present") is True and source["sha256"] != declared_sha,
        "source_hash_mismatch",
    )
    media: MediaFacts | None = None
    if not blockers:
        try:
            media = inspector(_contained(root, raw_path))
        except (OSError, subprocess.SubprocessError, ValueError):
            blockers.append("media_inspection_failed")
    block(media is None, "media_facts_incomplete")
    capture_method = value.get("capture_method")
    provenance_proofs: list[tuple[str, dict[str, Any]]] | None
    if capture_method == "file":
        proof = _proof(root, value.get("provenance_path"), value.get("provenance_sha256"))
        provenance_valid = bool(
            proof
            and proof[1].get("schema")
            in {"devlog.video_provenance", "devlog.audio_provenance"}
            and proof[1].get("version") == 1
            and proof[1].get("artifact_path") == raw_path.replace("\\", "/")
            and proof[1].get("artifact_sha256") == value.get("artifact_sha256")
        )
        provenance_proofs = (
            [("provenance", proof[0])] if proof and provenance_valid else None
        )
        block(provenance_proofs is None, "file_provenance_chain_incomplete")
    else:
        provenance_proofs = _capture_proofs(root, value)
        block(provenance_proofs is None, "capture_proof_chain_incomplete")
    if capture_method == "realtime_window":
        block(
            (value.get("head_handle_seconds") or 0) < 5
            or (value.get("tail_handle_seconds") or 0) < 5,
            "gameplay_handles_below_contract",
        )
        block(
            not all(
                (
                    value.get("state_id"),
                    value.get("build_id"),
                    value.get("width"),
                    value.get("height"),
                )
            ),
            "gameplay_identity_incomplete",
        )
    approval = None
    if value.get("status") == "approved":
        binding_valid = (
            isinstance(value.get("validation_sha256"), str)
            and re.fullmatch(r"[0-9a-fA-F]{64}", value["validation_sha256"])
            is not None
            and value.get("approved_sha256") == value.get("artifact_sha256")
            and value.get("approved_validation_sha256")
            == value.get("validation_sha256")
        )
        approval = _matching_proof(
            root,
            value.get("approval_evidence_path"),
            value.get("approval_evidence_sha256"),
            {
                "schema": "dlstudio.asset_validation",
                "version": 1,
                "artifact_sha256": value.get("artifact_sha256"),
                "validation_sha256": value.get("validation_sha256"),
            },
        )
        block(not binding_valid, "approval_binding_invalid")
        block(approval is None, "approval_evidence_missing")
    legacy_license = value.get("license")
    license_shape_valid = (
        isinstance(legacy_license, dict)
        and isinstance(legacy_license.get("license_id"), str)
        and bool(legacy_license["license_id"])
        and isinstance(legacy_license.get("attribution_required"), bool)
        and isinstance(legacy_license.get("redistribution_allowed"), bool)
        and (
            legacy_license.get("attribution_required") is False
            or (
                isinstance(legacy_license.get("attribution"), str)
                and bool(legacy_license["attribution"].strip())
            )
        )
    )
    license_binding = None
    if license_shape_valid:
        license_binding = _matching_proof(
            root,
            legacy_license.get("evidence_path"),
            legacy_license.get("evidence_sha256"),
            {
                "schema": "dlstudio.license_evidence",
                "version": 1,
                "license_id": legacy_license.get("license_id"),
                "attribution_required": legacy_license.get("attribution_required"),
                "attribution": legacy_license.get("attribution"),
                "redistribution_allowed": legacy_license.get(
                    "redistribution_allowed"
                ),
            },
        )
    block(license_binding is None, "license_evidence_incomplete")
    record: dict[str, Any] = {
        "legacy_schema": "asset_registry.v1",
        "legacy_asset_id": legacy_id,
        "asset_id": asset_id,
        "source": source,
        "disposition": (
            "TRANSLATE" if not blockers else "BLOCKED_ARCHIVE_READ_ONLY"
        ),
        "blockers": sorted(set(blockers)),
    }
    if not blockers:
        assert media and provenance_proofs and license_binding
        try:
            target, evidence = _target(
                value,
                asset_id=asset_id,
                source=source,
                media=media,
                provenance_proofs=provenance_proofs,
                license_proof=license_binding,
                approval_proof=approval,
            )
            record.update({"target": target, "evidence": evidence})
        except (AssetTranslationError, TypeError, ValueError):
            record["disposition"] = "BLOCKED_ARCHIVE_READ_ONLY"
            record["blockers"] = ["canonical_target_invalid"]
    return record


def _catalog_record(root: Path, value: Mapping[str, Any]) -> dict[str, Any]:
    raw_path = str(value["path"])
    legacy_id = f"catalog:{raw_path}"
    asset_id = _asset_id(
        "catalog-" + hashlib.sha256(raw_path.encode("utf-8")).hexdigest()[:20]
    )
    blockers = ["license_missing"]
    try:
        source = _bind_file(root, raw_path)
    except AssetTranslationError:
        source = {
            "path": raw_path.replace("\\", "/"),
            "present": False,
            "unsafe": True,
        }
        blockers.append("source_path_unsafe")
    if source.get("present") is not True:
        blockers.append("source_missing")
    elif source["sha256"] != str(value.get("sha256", "")).casefold():
        blockers.append("source_hash_mismatch")
    if str(value.get("provenance") or "unknown") == "unknown":
        blockers.append("provenance_missing")
    return {
        "legacy_schema": "asset_catalog.v1",
        "legacy_asset_id": legacy_id,
        "asset_id": asset_id,
        "source": source,
        "disposition": "BLOCKED_ARCHIVE_READ_ONLY",
        "blockers": sorted(set(blockers)),
    }


def _manifest_bindings(root: Path) -> dict[str, dict[str, Any]]:
    return {
        "registry": _bind_file(root, "data/assets/registry.json"),
        "catalog": _bind_file(root, "data/assets/catalog.json"),
    }


def translate_asset_schemas(
    production_root: Path,
    *,
    production_id: str | None = None,
    inspect_media: Callable[[Path], MediaFacts] | None = None,
) -> dict[str, Any]:
    root = production_root.resolve()
    inspector = inspect_media or FfprobeMediaInspector()
    manifests = _manifest_bindings(root)
    records: list[dict[str, Any]] = []
    registry_path = _verify_binding(root, manifests["registry"], label="legacy registry")
    if registry_path is not None:
        try:
            payload = json.loads(registry_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AssetTranslationError("invalid legacy asset registry") from exc
        if payload.get("version") != 1 or not isinstance(payload.get("assets"), list):
            raise AssetTranslationError("unsupported legacy asset registry")
        records.extend(_registry_record(root, item, inspector) for item in payload["assets"])
    catalog_path = _verify_binding(root, manifests["catalog"], label="legacy catalog")
    if catalog_path is not None:
        try:
            payload = json.loads(catalog_path.read_text(encoding="utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AssetTranslationError("invalid legacy asset catalog") from exc
        if payload.get("version") != 1 or not isinstance(payload.get("assets"), list):
            raise AssetTranslationError("unsupported legacy asset catalog")
        records.extend(_catalog_record(root, value) for value in payload["assets"])
    records.sort(key=lambda item: (item["asset_id"], item["legacy_asset_id"]))
    collisions = {
        asset_id
        for asset_id, count in Counter(r["asset_id"] for r in records).items()
        if count > 1
    }
    for record in records:
        if record["asset_id"] in collisions:
            record["disposition"] = "BLOCKED_ARCHIVE_READ_ONLY"
            record["blockers"] = sorted(
                set(record["blockers"]) | {"canonical_asset_id_collision"}
            )
            record.pop("target", None)
            record.pop("evidence", None)
    present_sources = {
        (record["source"].get("sha256"), record["source"].get("size"))
        for record in records
        if record["source"].get("present") is True
    }
    translatable = sum(r["disposition"] == "TRANSLATE" for r in records)
    plan: dict[str, Any] = {
        "schema": "studio_v3.asset_translation_plan",
        "version": 1,
        "production_id": _production_id(root, production_id),
        "manifests": manifests,
        "source_manifest_sha256": _json_hash(manifests),
        "records": records,
        "summary": {
            "total": len(records),
            "translatable": translatable,
            "blocked": len(records) - translatable,
            "unique_source_files": len(present_sources),
            "unique_source_bytes": sum(size for _sha, size in present_sources),
            "archive_receipts_bound": 0,
        },
    }
    plan["plan_id"] = _plan_id(plan)
    return plan


def _plan_id(plan: Mapping[str, Any]) -> str:
    payload = dict(plan)
    payload.pop("plan_id", None)
    return _json_hash(payload)


def _revision(target: Mapping[str, Any]) -> AssetRevision:
    try:
        revision = AssetRevision(
            asset_id=str(target["asset_id"]),
            blob=BlobRef.from_payload(target["blob"]),
            media=MediaFacts.from_payload(target["media"]),
            provenance=Provenance.from_payload(target["provenance"]),
            approval=Approval.from_payload(target["approval"]),
            license=License.from_payload(target["license"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise AssetTranslationError("invalid canonical asset target") from exc
    if target.get("revision") != revision.ref.as_payload():
        raise AssetTranslationError("canonical target revision mismatch")
    return revision


def _validate_plan(plan: Mapping[str, Any]) -> dict[str, Any]:
    payload = dict(plan)
    if (
        payload.get("schema") != "studio_v3.asset_translation_plan"
        or payload.get("version") != 1
        or not isinstance(payload.get("records"), list)
        or not isinstance(payload.get("manifests"), Mapping)
    ):
        raise AssetTranslationError("unsupported asset migration plan")
    if payload.get("plan_id") != _plan_id(payload):
        raise AssetTranslationError("asset migration plan_id mismatch")
    if payload.get("source_manifest_sha256") != _json_hash(payload["manifests"]):
        raise AssetTranslationError("source manifest binding mismatch")
    if set(payload["manifests"]) != {"registry", "catalog"}:
        raise AssetTranslationError("source manifest set is incomplete")

    for record in payload["records"]:
        if not isinstance(record, Mapping) or not isinstance(
            record.get("source"), Mapping
        ):
            raise AssetTranslationError("asset record lacks source binding")
        if record.get("disposition") != "TRANSLATE":
            if "target" in record or "evidence" in record:
                raise AssetTranslationError("blocked record is executable")
            continue
        if not isinstance(record.get("target"), Mapping) or not isinstance(
            record.get("evidence"), list
        ):
            raise AssetTranslationError("executable record is incomplete")
        revision = _revision(record["target"])
        if revision.asset_id != record.get("asset_id"):
            raise AssetTranslationError("record and target asset ids differ")
        if _binding_ref(record["source"]) != revision.blob:
            raise AssetTranslationError("canonical target source mismatch")
        evidence_refs = {_binding_ref(item) for item in record["evidence"]}
        reachable_evidence = set(revision.reachable_blobs) - {revision.blob}
        if evidence_refs != reachable_evidence:
            raise AssetTranslationError(
                "canonical target evidence binding mismatch"
            )
    return payload


def load_asset_plan(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise AssetTranslationError(f"cannot load asset migration plan: {exc}") from exc
    if not isinstance(value, Mapping):
        raise AssetTranslationError("asset migration plan must be an object")
    return _validate_plan(value)


def _repository_for(root: Path, production_id: str) -> AssetRepository:
    studio = root / "data" / ".studio"
    return AssetRepository(
        ProductionRepository(
            object_root=studio / "objects",
            state_root=studio / "state",
            staging_root=studio / "staging",
            lock_root=studio / "locks",
            production_id=production_id,
        )
    )


def _coerce_plan(plan: Mapping[str, Any] | Path) -> dict[str, Any]:
    return load_asset_plan(plan) if isinstance(plan, Path) else _validate_plan(plan)


def _executable_production_id(
    root: Path,
    plan: Mapping[str, Any],
) -> str:
    raw = plan.get("production_id")
    if not isinstance(raw, str):
        raise AssetTranslationError(
            "manifest-less execution requires a stable explicit production id"
        )
    try:
        plan_id = str(DomainId(raw))
    except ValueError as exc:
        raise AssetTranslationError("invalid plan production id") from exc
    manifest_id = _production_id(root)
    if manifest_id is not None and plan_id != manifest_id:
        raise AssetTranslationError("asset migration production id mismatch")
    return plan_id


def _preflight(
    root: Path,
    plan: Mapping[str, Any] | Path,
    assets: AssetRepository,
) -> tuple[
    dict[str, Any],
    list[tuple[dict[str, Any], Path, list[Path], AssetRevision, bool]],
]:
    payload = _coerce_plan(plan)
    production_id = _executable_production_id(root, payload)
    if assets.repository.production_id != production_id:
        raise AssetTranslationError("repository production id mismatch")
    for name, binding in payload["manifests"].items():
        _verify_binding(root, binding, label=f"legacy {name}")

    counts = Counter(record["asset_id"] for record in payload["records"])
    duplicates = sorted(asset_id for asset_id, count in counts.items() if count > 1)
    if duplicates:
        raise AssetTranslationError(
            "duplicate canonical asset ids: " + ", ".join(duplicates)
        )

    prepared = []
    for record in payload["records"]:
        source = _verify_binding(root, record["source"], label="legacy artifact")
        if record["disposition"] != "TRANSLATE":
            continue
        assert source is not None
        evidence_paths = [
            _verify_binding(
                root,
                descriptor,
                label=f"{descriptor.get('role', 'unknown')} evidence",
            )
            for descriptor in record["evidence"]
        ]
        if any(path is None for path in evidence_paths):
            raise AssetTranslationError("required migration evidence is absent")
        revision = _revision(record["target"])
        prepared.append(
            (
                dict(record),
                source,
                [path for path in evidence_paths if path is not None],
                revision,
                False,
            )
        )

    index = assets.read_index()
    checked = []
    for record, source, evidence, revision, _present in prepared:
        current = index.entries.get(revision.asset_id)
        if current is not None and current != revision.ref:
            raise AssetTranslationError(
                f"canonical asset conflict: {revision.asset_id}"
            )
        present = current == revision.ref
        if present:
            assets.read_revision(revision.ref)
        checked.append((record, source, evidence, revision, present))
    return payload, checked


def _blocked_count(plan: Mapping[str, Any]) -> int:
    return sum(
        record.get("disposition") != "TRANSLATE"
        for record in plan["records"]
    )


def verify_asset_plan(
    production_root: Path,
    plan: Mapping[str, Any] | Path,
    *,
    repository: AssetRepository | None = None,
) -> dict[str, Any]:
    root = production_root.resolve()
    payload = _coerce_plan(plan)
    production_id = _executable_production_id(root, payload)
    assets = repository or _repository_for(root, production_id)
    payload, prepared = _preflight(root, payload, assets)
    missing = [
        revision.asset_id
        for _record, _source, _evidence, revision, present in prepared
        if not present
    ]
    if missing:
        raise AssetTranslationError(
            "canonical assets are missing: " + ", ".join(sorted(missing))
        )
    blocked = _blocked_count(payload)
    if blocked:
        raise AssetTranslationError(
            f"{blocked} blocked artifacts lack verified archive receipts"
        )
    head = assets.repository.read_head()
    return {
        "mode": "verify",
        "status": "verified",
        "plan_id": payload["plan_id"],
        "verified": len(prepared),
        "blocked": 0,
        "head_revision": 0 if head is None else head.revision,
    }


def _stable_current(
    assets: AssetRepository,
    revision: AssetRevision,
) -> tuple[bool, int]:
    before = assets.repository.read_head()
    index = assets.read_index()
    after = assets.repository.read_head()
    if before != after:
        raise CasConflict("canonical head changed during migration pre-commit")
    current = index.entries.get(revision.asset_id)
    if current is not None and current != revision.ref:
        raise AssetTranslationError(
            f"canonical asset conflict: {revision.asset_id}"
        )
    return current == revision.ref, 0 if after is None else after.revision


def apply_asset_plan(
    production_root: Path,
    plan: Mapping[str, Any] | Path,
    *,
    repository: AssetRepository | None = None,
    inspect_media: Callable[[Path], MediaFacts] | None = None,
) -> dict[str, Any]:
    root = production_root.resolve()
    payload = _coerce_plan(plan)
    production_id = _executable_production_id(root, payload)
    assets = repository or _repository_for(root, production_id)
    inspector = inspect_media or FfprobeMediaInspector()
    payload, prepared = _preflight(root, payload, assets)
    created = 0
    already_present = 0
    for record, source, evidence_paths, revision, initially_present in prepared:
        present, expected_revision = _stable_current(assets, revision)
        if initially_present or present:
            already_present += 1
            continue
        for descriptor, evidence_path in zip(
            record["evidence"], evidence_paths, strict=True
        ):
            if assets.repository.objects.ingest_file(evidence_path) != (
                _binding_ref(descriptor)
            ):
                raise AssetTranslationError("evidence changed during migration")

        def inspect_bound(path: Path, expected: AssetRevision = revision) -> MediaFacts:
            if BlobRef(_sha256(path), path.stat().st_size) != expected.blob:
                raise AssetTranslationError("source changed during migration")
            return inspector(path)

        result = assets.ingest(
            source,
            asset_id=revision.asset_id,
            media=revision.media,
            provenance=revision.provenance,
            approval=revision.approval,
            license=revision.license,
            expected_revision=expected_revision,
            inspect_media=inspect_bound,
        )
        if result.revision.ref != revision.ref:
            raise AssetTranslationError(
                f"canonical asset result mismatch: {revision.asset_id}"
            )
        created += int(result.created)
        already_present += int(not result.created)

    blocked = _blocked_count(payload)
    head = assets.repository.read_head()
    return {
        "mode": "apply",
        "status": "blocked" if blocked else "verified",
        "fully_verified": blocked == 0,
        "plan_id": payload["plan_id"],
        "created": created,
        "already_present": already_present,
        "verified": len(prepared),
        "blocked": blocked,
        "head_revision": 0 if head is None else head.revision,
    }
