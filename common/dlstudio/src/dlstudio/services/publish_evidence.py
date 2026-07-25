"""Regenerate publish facts from the exact post-review delivery candidate."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from PIL import Image

from dlstudio.production import ProductionManifest
from dlstudio.services.delivery import parse_metadata


class PublishEvidenceError(RuntimeError):
    """Publish facts are missing, stale, or not exact-file-bound."""


@dataclass(frozen=True)
class PublishEvidenceResult:
    publish_path: Path
    evidence_path: Path
    publish_video_path: Path
    video_sha256: str
    review_verdict: str


@dataclass(frozen=True)
class ValidatedDeliverySources:
    video_path: Path
    metadata_path: Path
    image_path: Path


def _read_object(path: Path) -> dict:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PublishEvidenceError(f"required publish evidence is missing: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PublishEvidenceError(f"invalid JSON in {path}: {exc}") from exc
    if not isinstance(payload, dict):
        raise PublishEvidenceError(f"expected a JSON object: {path}")
    return payload


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _validate_evidence_file(
    manifest: ProductionManifest,
    *,
    section: dict,
    path_key: str,
    actual_path: str | Path,
    label: str,
) -> Path:
    expected = _production_data_path(manifest, section.get(path_key), label)
    actual = Path(actual_path).resolve()
    if actual != expected:
        raise PublishEvidenceError(
            f"{label} source does not match exact publish evidence: {actual}"
        )
    expected_hash = str(section.get("sha256", "")).casefold()
    if not expected_hash or _sha256(actual) != expected_hash:
        raise PublishEvidenceError(f"{label} SHA-256 is stale in publish evidence")
    return actual


def validate_delivery_sources(
    manifest: ProductionManifest,
    *,
    video_path: str | Path,
    metadata_path: str | Path,
    image_path: str | Path,
) -> ValidatedDeliverySources:
    """Revalidate the exact evidence-bound files immediately before delivery."""

    evidence = _read_object(manifest.publish_dir / "evidence.json")
    if (
        evidence.get("product_id") != manifest.product.id
        or evidence.get("production_id") != manifest.id
    ):
        raise PublishEvidenceError("publish evidence identity does not match production")
    video = evidence.get("video")
    image = evidence.get("image")
    metadata = evidence.get("metadata")
    if not isinstance(video, dict) or not isinstance(image, dict) or not isinstance(metadata, dict):
        raise PublishEvidenceError("publish evidence is incomplete")
    return ValidatedDeliverySources(
        video_path=_validate_evidence_file(
            manifest,
            section=video,
            path_key="publish_path",
            actual_path=video_path,
            label="video",
        ),
        metadata_path=_validate_evidence_file(
            manifest,
            section=metadata,
            path_key="path",
            actual_path=metadata_path,
            label="metadata",
        ),
        image_path=_validate_evidence_file(
            manifest,
            section=image,
            path_key="path",
            actual_path=image_path,
            label="image",
        ),
    )


def _production_data_path(manifest: ProductionManifest, raw: object, label: str) -> Path:
    if not isinstance(raw, str) or not raw:
        raise PublishEvidenceError(f"{label} path is missing")
    value = Path(raw)
    path = value.resolve() if value.is_absolute() else (manifest.root / value).resolve()
    try:
        path.relative_to(manifest.data_dir.resolve())
    except ValueError as exc:
        raise PublishEvidenceError(f"{label} must stay inside production data: {path}") from exc
    if path.is_symlink() or not path.is_file():
        raise PublishEvidenceError(f"{label} is not a regular file: {path}")
    return path


def _probe_video(path: Path) -> tuple[float, int, int]:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_streams", "-show_format", str(path),
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as exc:
        raise PublishEvidenceError("ffprobe is required for publish evidence") from exc
    if result.returncode:
        raise PublishEvidenceError(f"ffprobe failed for {path}: {result.stderr[-500:]}")
    payload = json.loads(result.stdout)
    stream = next(
        (item for item in payload.get("streams", []) if item.get("codec_type") == "video"),
        None,
    )
    if not isinstance(stream, dict):
        raise PublishEvidenceError(f"video stream is missing: {path}")
    try:
        return (
            float(payload["format"]["duration"]),
            int(stream["width"]),
            int(stream["height"]),
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise PublishEvidenceError(f"incomplete ffprobe facts for {path}") from exc


def _resolve_review_artifact(manifest: ProductionManifest, raw: object) -> Path:
    if not isinstance(raw, str) or not raw:
        raise PublishEvidenceError("exact review artifact_path is missing")
    value = Path(raw)
    return value.resolve() if value.is_absolute() else (manifest.root / value).resolve()


def _atomic_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _materialize_publish_video(source: Path, destination: Path, digest: str) -> Path:
    """Place the exact reviewed MP4 beside publish metadata atomically.

    A hardlink avoids duplicating a potentially large final on the normal
    same-volume workspace layout. Filesystems without hardlink support fall
    back to a byte copy. Either path is SHA-verified before it becomes the
    visible ``data/publish/video.mp4``.
    """
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        if destination.is_file() and not destination.is_symlink():
            try:
                if destination.stat().st_size == source.stat().st_size and _sha256(destination) == digest:
                    return destination
            except OSError:
                pass
        if destination.is_dir() and not destination.is_symlink():
            raise PublishEvidenceError(
                f"publish video destination is a directory: {destination}"
            )

    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{destination.name}.", suffix=".tmp", dir=destination.parent
    )
    os.close(handle)
    temporary = Path(temporary_name)
    temporary.unlink(missing_ok=True)
    try:
        try:
            os.link(source, temporary)
        except OSError:
            shutil.copy2(source, temporary)
        if temporary.stat().st_size != source.stat().st_size or _sha256(temporary) != digest:
            raise PublishEvidenceError(
                f"publish video hash verification failed: {destination}"
            )
        os.replace(temporary, destination)
    except OSError as exc:
        raise PublishEvidenceError(
            f"cannot materialize exact publish video at {destination}: {exc}"
        ) from exc
    finally:
        temporary.unlink(missing_ok=True)

    if destination.is_symlink() or not destination.is_file() or _sha256(destination) != digest:
        raise PublishEvidenceError(
            f"publish video destination failed verification: {destination}"
        )
    return destination


def _set_gate(payload: dict, gate: str, evidence: str) -> None:
    checklist = payload.setdefault("upload_checklist", {})
    if not isinstance(checklist, dict):
        raise PublishEvidenceError("upload_checklist must be an object")
    passed = checklist.setdefault("passed", [])
    if not isinstance(passed, list):
        raise PublishEvidenceError("upload_checklist.passed must be an array")
    for item in passed:
        if isinstance(item, dict) and item.get("gate") == gate:
            item["evidence"] = evidence
            return
    passed.append({"gate": gate, "evidence": evidence})


def _license_requires_attribution(entry: dict) -> bool:
    explicit = entry.get("attribution_required")
    if isinstance(explicit, bool):
        return explicit
    license_text = str(entry.get("license") or entry.get("license_name") or "")
    normalized = re.sub(r"[^a-z0-9]+", " ", license_text.casefold()).strip()
    if any(
        phrase in normalized
        for phrase in (
            "cc0",
            "public domain",
            "no attribution required",
            "attribution not required",
            "pexels",
            "pixabay",
        )
    ):
        return False
    return any(
        phrase in normalized
        for phrase in (
            "cc by",
            "creative commons attribution",
            "by attribution",
            "attribution required",
            "requires attribution",
            "must credit",
        )
    )


def _used_asset_obligations(
    manifest: ProductionManifest,
    payload: dict,
) -> list[dict[str, str]]:
    used_paths: set[str] = set()
    used_ids: set[str] = set()
    try:
        from dlstudio.compile import _referenced_paths
        from dlstudio.production import load_production_edit_module

        if (manifest.edit_dir / "__init__.py").is_file():
            module, _loaded_manifest, _module_name = load_production_edit_module(
                manifest.root,
                force_reload=True,
            )
            edit = getattr(module, "EDIT", None)
            if edit is None:
                raise PublishEvidenceError(
                    f"production edit does not expose EDIT: {manifest.edit_dir}"
                )
            for path in _referenced_paths(edit):
                normalized = str(path).replace("\\", "/")
                used_paths.add(normalized)
    except PublishEvidenceError:
        raise
    except Exception as exc:
        raise PublishEvidenceError(
            f"cannot enumerate exact production assets: {exc}"
        ) from exc
    shot_path = manifest.root / "data" / "plan" / "shot_manifest.json"
    if shot_path.is_file():
        try:
            shot_payload = json.loads(shot_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise PublishEvidenceError(f"invalid JSON in {shot_path}: {exc}") from exc
        shots = (
            shot_payload.get("shots", [])
            if isinstance(shot_payload, dict)
            else shot_payload
        )
        if isinstance(shots, list):
            used_paths.update(
                str(shot.get("src")).replace("\\", "/")
                for shot in shots
                if isinstance(shot, dict) and shot.get("src")
            )
    declared = payload.get("used_assets", [])
    if isinstance(declared, list):
        for item in declared:
            if isinstance(item, str):
                used_paths.add(item.replace("\\", "/"))
            elif isinstance(item, dict):
                path = item.get("path") or item.get("artifact_path") or item.get("src")
                asset_id = item.get("asset_id") or item.get("id")
                if path:
                    normalized = str(path).replace("\\", "/")
                    used_paths.add(normalized)
                if asset_id:
                    used_ids.add(str(asset_id))

    registry_path = manifest.root / "data" / "assets" / "registry.json"
    registry = _read_object(registry_path) if registry_path.is_file() else {}
    records = registry.get("assets", [])
    registered_paths = {
        str(record.get("artifact_path") or "").replace("\\", "/")
        for record in records
        if isinstance(record, dict) and record.get("artifact_path")
    } if isinstance(records, list) else set()
    provenance_roots = (
        "data/footage/",
        "data/images/",
        "data/music/",
        "data/sfx/",
    )
    missing_registration = sorted(
        path
        for path in used_paths
        if path.casefold().startswith(provenance_roots)
        and path not in registered_paths
    )
    if missing_registration:
        raise PublishEvidenceError(
            "used external asset is not registered with hash-bound provenance: "
            f"{missing_registration[0]}"
        )
    obligations: list[dict[str, str]] = []
    if isinstance(records, list):
        for record in records:
            if not isinstance(record, dict):
                continue
            artifact_path = str(record.get("artifact_path") or "").replace("\\", "/")
            asset_id = str(record.get("asset_id") or "")
            if artifact_path not in used_paths and asset_id not in used_ids:
                continue
            artifact = _production_data_path(
                manifest, artifact_path, f"registered asset {asset_id or artifact_path}"
            )
            expected_artifact_hash = str(
                record.get("artifact_sha256") or ""
            ).casefold()
            if not expected_artifact_hash or _sha256(artifact) != expected_artifact_hash:
                raise PublishEvidenceError(
                    f"used registered asset is stale: {asset_id or artifact_path}"
                )
            provenance_raw = record.get("provenance_path")
            if not isinstance(provenance_raw, str) or not provenance_raw:
                raise PublishEvidenceError(
                    f"used registered asset has no provenance record: "
                    f"{asset_id or artifact_path}"
                )
            provenance_path = _production_data_path(
                manifest, provenance_raw, f"provenance for {asset_id or artifact_path}"
            )
            expected_provenance_hash = str(
                record.get("provenance_sha256") or ""
            ).casefold()
            if not expected_provenance_hash:
                raise PublishEvidenceError(
                    f"used asset provenance is not hash-bound: "
                    f"{asset_id or artifact_path}"
                )
            if _sha256(provenance_path) != expected_provenance_hash:
                raise PublishEvidenceError(
                    f"asset provenance is stale for {asset_id or artifact_path}"
                )
            provenance = _read_object(provenance_path)
            if not _license_requires_attribution(provenance):
                continue
            obligations.append({
                "asset_id": asset_id or artifact_path,
                "license": str(provenance.get("license") or "").strip(),
                "credit": str(provenance.get("credit") or "").strip(),
            })

    if isinstance(declared, list):
        for item in declared:
            if not isinstance(item, dict) or not _license_requires_attribution(item):
                continue
            obligations.append({
                "asset_id": str(item.get("asset_id") or item.get("id") or item.get("path") or "asset"),
                "license": str(item.get("license") or item.get("license_name") or "").strip(),
                "credit": str(item.get("credit") or "").strip(),
            })
    return [
        dict(zip(("asset_id", "license", "credit"), key))
        for key in dict.fromkeys(
            (item["asset_id"], item["license"], item["credit"])
            for item in obligations
        )
    ]


def _validate_attribution(manifest: ProductionManifest, payload: dict) -> list[dict[str, str]]:
    obligations = _used_asset_obligations(manifest, payload)
    for obligation in obligations:
        missing = [
            field for field in ("credit", "license") if not obligation[field]
        ]
        if missing:
            raise PublishEvidenceError(
                f"attribution provenance is incomplete for {obligation['asset_id']}: "
                + ", ".join(missing)
            )
    attribution = payload.get("attribution")
    package_requires = isinstance(attribution, dict) and attribution.get("required") is True
    if not obligations and not package_requires:
        return []
    if not isinstance(attribution, dict) or attribution.get("required") is not True:
        raise PublishEvidenceError(
            "attribution-required used assets must set publish.json attribution.required=true"
        )
    text = str(attribution.get("text") or "").strip()
    if not text:
        raise PublishEvidenceError(
            "copy-ready attribution text is required for attribution-required used assets"
        )
    folded = text.casefold()
    for obligation in obligations:
        for field in ("credit", "license"):
            expected = obligation[field]
            if expected and expected.casefold() not in folded:
                raise PublishEvidenceError(
                    f"copy-ready attribution is missing {field} for "
                    f"{obligation['asset_id']}: {expected}"
                )
    return obligations


def refresh_publish_evidence(
    manifest: ProductionManifest,
    *,
    publish_path: str | Path | None = None,
) -> PublishEvidenceResult:
    """Patch stale package facts only after exact preflight + blind review pass."""

    path = Path(publish_path) if publish_path else manifest.publish_dir / "publish.json"
    payload = _read_object(path)
    if payload.get("product_id") != manifest.product.id or payload.get("production_id") != manifest.id:
        raise PublishEvidenceError("publish.json identity does not match production")
    video_section = payload.get("video")
    if not isinstance(video_section, dict):
        raise PublishEvidenceError("publish.json video section is missing")
    video = _production_data_path(manifest, video_section.get("path"), "video")
    video_hash = _sha256(video)
    duration, width, height = _probe_video(video)

    image_key = "thumbnail" if manifest.kind == "devlog" else "cover"
    image_section = payload.get(image_key)
    if not isinstance(image_section, dict):
        raise PublishEvidenceError(f"publish.json {image_key} section is missing")
    image = _production_data_path(manifest, image_section.get("path"), image_key)
    with Image.open(image) as opened:
        image_width, image_height = opened.size
    metadata = manifest.publish_dir / "metadata.md"
    metadata_text = metadata.read_text(encoding="utf-8")
    parse_metadata(metadata_text)
    attribution_obligations = _validate_attribution(manifest, payload)
    attribution = payload.get("attribution")
    attribution_text = (
        str(attribution.get("text") or "").strip()
        if isinstance(attribution, dict)
        else ""
    )
    if (
        attribution_obligations
        and attribution_text.casefold() not in metadata_text.casefold()
    ):
        raise PublishEvidenceError(
            "copy-ready attribution must be included verbatim in the "
            "delivered metadata.md"
        )

    preflight_path = manifest.review_dir / "preflight.json"
    preflight = _read_object(preflight_path)
    inputs = preflight.get("inputs")
    artifact_raw = inputs.get("render_artifact") if isinstance(inputs, dict) else None
    if _resolve_review_artifact(manifest, artifact_raw) != video:
        raise PublishEvidenceError("preflight is stale for the exact publish video")
    if str(inputs.get("render_artifact_sha256", "")).casefold() != video_hash:
        raise PublishEvidenceError("preflight SHA-256 is stale for publish video")
    if preflight.get("errors") != 0 or not preflight.get("ok"):
        raise PublishEvidenceError("preflight does not pass for the publish video")

    feedback_path = manifest.review_dir / "feedback.json"
    feedback = _read_object(feedback_path)
    full = feedback.get("full")
    review = full.get("video") if isinstance(full, dict) else None
    if not isinstance(review, dict):
        raise PublishEvidenceError("exact full-video review is missing")
    verdict = str(review.get("verdict", "")).casefold()
    if verdict not in {"ship", "pass"}:
        raise PublishEvidenceError(f"exact review verdict is not shippable: {verdict!r}")
    if _resolve_review_artifact(manifest, review.get("artifact_path")) != video:
        raise PublishEvidenceError("review artifact_path does not match publish video")
    if str(review.get("artifact_sha256", "")).casefold() != video_hash:
        raise PublishEvidenceError("review SHA-256 is stale for publish video")

    publish_video = _materialize_publish_video(
        video, manifest.publish_dir / "video.mp4", video_hash
    )

    video_section.update(
        {
            "sha256": video_hash,
            "duration_seconds": round(duration, 3),
            "resolution": {"width": width, "height": height},
        }
    )
    image_section.update(
        {
            "sha256": _sha256(image),
            "width": image_width,
            "height": image_height,
        }
    )
    warning_count = int(preflight.get("warnings", 0))
    _set_gate(
        payload,
        "preflight_mechanical",
        f"data/review/preflight.json: exact artifact, ok=true, errors=0, warnings={warning_count}",
    )
    _set_gate(
        payload,
        "exact_final_blind_review",
        f"{verdict.upper()} reported for video SHA-256 {video_hash}",
    )
    if attribution_obligations:
        _set_gate(
            payload,
            "attribution_ready",
            "copy-ready attribution present for "
            + ", ".join(item["asset_id"] for item in attribution_obligations),
        )
    generated_at = datetime.now(timezone.utc).isoformat()
    evidence = {
        "version": 1,
        "generated_at": generated_at,
        "product_id": manifest.product.id,
        "production_id": manifest.id,
        "video": {
            "path": str(video), "sha256": video_hash,
            "duration_seconds": round(duration, 3), "width": width, "height": height,
        },
        "image": {"path": str(image), "sha256": _sha256(image)},
        "preflight": {"path": str(preflight_path), "warnings": warning_count},
        "review": {
            "path": str(feedback_path), "verdict": verdict,
            "timestamp": review.get("timestamp"), "artifact_sha256": video_hash,
        },
        "metadata": {
            "path": str(metadata),
            "sha256": _sha256(metadata),
            "validated": True,
        },
        "attribution": {
            "required_assets": attribution_obligations,
            "copy_ready": bool(attribution_obligations),
            "text": attribution_text if attribution_obligations else None,
        },
    }
    payload["evidence_version"] = 1
    payload["evidence_generated_at"] = generated_at
    payload["publish_video"] = {
        "path": "data/publish/video.mp4",
        "sha256": video_hash,
        "size": publish_video.stat().st_size,
    }
    evidence_path = manifest.publish_dir / "evidence.json"
    evidence["video"]["publish_path"] = str(publish_video)
    _atomic_json(evidence_path, evidence)
    _atomic_json(path, payload)
    return PublishEvidenceResult(
        publish_path=path,
        evidence_path=evidence_path,
        publish_video_path=publish_video,
        video_sha256=video_hash,
        review_verdict=verdict,
    )


__all__ = [
    "PublishEvidenceError",
    "PublishEvidenceResult",
    "ValidatedDeliverySources",
    "refresh_publish_evidence",
    "validate_delivery_sources",
]
