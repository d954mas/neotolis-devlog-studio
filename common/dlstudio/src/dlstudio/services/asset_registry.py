"""Hash-bound semantic identity for production assets."""
from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
import threading
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class AssetRegistryError(ValueError):
    """Invalid registry operation or stale artifact identity."""


_REGISTRY_LOCKS: dict[Path, threading.RLock] = {}
_REGISTRY_LOCKS_GUARD = threading.Lock()


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _IngestedCapture(_Model):
    """Facts produced only after the v2 capture-batch audit has passed."""

    request_id: str = Field(min_length=1)
    artifact_path: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    metadata_path: str = Field(min_length=1)
    metadata_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    game_report_path: str | None = None
    game_report_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    capture_batch_path: str = Field(min_length=1)
    capture_batch_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    capture_results_path: str = Field(min_length=1)
    capture_results_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    editorial_role: str
    capture_method: str
    state_id: str
    build_id: str
    action_id: str | None = None
    seed: int | None = Field(default=None, ge=0, le=4294967295)
    parameters: dict[str, float | str] = Field(default_factory=dict)
    initial_semantic_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{8}$",
    )
    action_semantic_hash: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{8}$",
    )
    actual_width: int | None = Field(default=None, gt=0)
    actual_height: int | None = Field(default=None, gt=0)
    actual_fps: float | None = Field(default=None, gt=0)
    actual_duration: float | None = Field(default=None, gt=0)
    actual_orientation: str | None = None
    client_rect: dict | None = None
    simulation_rate: float | None = Field(default=None, gt=0)
    continuous: bool | None = None
    clean_ui: bool | None = None
    client_area: bool | None = None
    cursor_visible: bool | None = None
    content_seconds: float | None = Field(default=None, gt=0)
    head_handle_seconds: float | None = Field(default=None, ge=0)
    tail_handle_seconds: float | None = Field(default=None, ge=0)
    frame_audit_passed: bool | None = None
    frame_audit: dict | None = None
    game_elapsed_seconds: float | None = Field(default=None, gt=0)
    measured_playback_rate: float | None = Field(default=None, gt=0)
    encoded_duration_seconds: float | None = Field(default=None, gt=0)
    action_media_seconds: float | None = Field(default=None, ge=0)
    presentation: dict | None = None

    @model_validator(mode="after")
    def validate_gameplay_contract(self) -> "_IngestedCapture":
        if self.editorial_role == "debug_proof":
            if self.capture_method != "deterministic_devapi":
                raise ValueError(
                    "debug_proof requires capture_method=deterministic_devapi"
                )
            if (
                not self.state_id
                or re.fullmatch(
                    r"exe-sha256:[0-9a-fA-F]{64}",
                    self.build_id,
                ) is None
                or self.seed is None
                or not self.initial_semantic_hash
            ):
                raise ValueError(
                    "debug_proof requires game-owned state/build/seed identity"
                )
            if self.action_id and not self.action_semantic_hash:
                raise ValueError(
                    "debug_proof action requires semantic identity"
                )
            if not self.game_report_path or not self.game_report_sha256:
                raise ValueError(
                    "debug_proof requires a hash-bound game report"
                )
            return self
        if self.editorial_role != "gameplay":
            return self
        if self.capture_method != "realtime_window":
            raise ValueError("gameplay requires capture_method=realtime_window")
        if re.fullmatch(r"exe-sha256:[0-9a-fA-F]{64}", self.build_id) is None:
            raise ValueError("gameplay build_id requires exe-sha256:<64 hex>")
        if not self.state_id:
            raise ValueError("gameplay requires state_id")
        if self.seed is None or not self.initial_semantic_hash:
            raise ValueError("gameplay requires seeded semantic identity")
        if self.action_id and not self.action_semantic_hash:
            raise ValueError("gameplay action requires semantic identity")
        if self.simulation_rate != 1.0:
            raise ValueError("gameplay requires simulation_rate=1.0")
        if self.continuous is not True:
            raise ValueError("gameplay requires continuous=true")
        if self.clean_ui is not True:
            raise ValueError("gameplay requires clean_ui=true")
        if self.client_area is not True:
            raise ValueError("gameplay requires client_area=true")
        if self.cursor_visible is not False:
            raise ValueError("gameplay requires cursor_visible=false")
        if (self.head_handle_seconds or 0.0) < 5.0:
            raise ValueError("gameplay requires head_handle_seconds >= 5")
        if (self.tail_handle_seconds or 0.0) < 5.0:
            raise ValueError("gameplay requires tail_handle_seconds >= 5")
        if self.frame_audit_passed is not True:
            raise ValueError("gameplay requires frame_audit_passed=true")
        if not self.game_report_path or not self.game_report_sha256:
            raise ValueError("gameplay requires a hash-bound game report")
        if self.measured_playback_rate is None or not (
            0.97 <= self.measured_playback_rate <= 1.03
        ):
            raise ValueError("gameplay requires measured real-time playback")
        if not self.presentation:
            raise ValueError("gameplay requires validated presentation geometry")
        return self


class RegisteredAsset(_Model):
    asset_id: str
    revision: int = Field(default=1, ge=1)
    status: Literal[
        "unverified",
        "candidate",
        "validated",
        "approved",
        "rejected",
        "archived",
    ]
    artifact_path: str
    artifact_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    validation_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    editorial_role: str
    capture_method: str
    state_id: str
    build_id: str
    action_id: str | None = None
    seed: int | None = None
    parameters: dict[str, float | str] = Field(default_factory=dict)
    initial_semantic_hash: str | None = None
    action_semantic_hash: str | None = None
    metadata_path: str | None = None
    metadata_sha256: str | None = None
    game_report_path: str | None = None
    game_report_sha256: str | None = None
    capture_batch_path: str | None = None
    capture_batch_sha256: str | None = None
    capture_results_path: str | None = None
    capture_results_sha256: str | None = None
    provenance_path: str | None = None
    provenance_sha256: str | None = None
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    duration: float | None = None
    orientation: str | None = None
    client_rect: dict | None = None
    simulation_rate: float | None = None
    continuous: bool | None = None
    clean_ui: bool | None = None
    client_area: bool | None = None
    cursor_visible: bool | None = None
    content_seconds: float | None = None
    head_handle_seconds: float | None = None
    tail_handle_seconds: float | None = None
    frame_audit_passed: bool | None = None
    frame_audit: dict | None = None
    game_elapsed_seconds: float | None = None
    measured_playback_rate: float | None = None
    encoded_duration_seconds: float | None = None
    action_media_seconds: float | None = None
    presentation: dict | None = None
    validated_at: str
    approved_sha256: str | None = None
    approved_validation_sha256: str | None = None
    approved_at: str | None = None
    approved_by: str | None = None


class AssetRegistry(_Model):
    version: Literal[1] = 1
    root: str
    updated_at: str = ""
    assets: list[RegisteredAsset] = Field(default_factory=list)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _registry_path(root: Path) -> Path:
    return root / "data" / "assets" / "registry.json"


@contextmanager
def _registry_write_lock(root: Path):
    """Serialize registry read/modify/write across ingest and approval."""

    lock = root / "data" / "assets" / ".registry.lock"
    lock.parent.mkdir(parents=True, exist_ok=True)
    resolved = lock.resolve()
    with _REGISTRY_LOCKS_GUARD:
        process_lock = _REGISTRY_LOCKS.setdefault(resolved, threading.RLock())
    with process_lock:
        with lock.open("a+b") as handle:
            handle.seek(0, os.SEEK_END)
            if handle.tell() == 0:
                handle.write(b"\0")
                handle.flush()
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                try:
                    msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
                except OSError as exc:
                    raise AssetRegistryError(
                        "timed out waiting for asset registry lock"
                    ) from exc
                try:
                    yield
                finally:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:  # pragma: no cover - Windows is the production platform
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


def _artifact_path(root: Path, raw: str) -> Path:
    path = Path(raw)
    if path.is_absolute() or path.drive or ".." in path.parts:
        raise AssetRegistryError(f"asset path must stay inside production data: {raw}")
    resolved = (root / path).resolve()
    try:
        resolved.relative_to((root / "data").resolve())
    except ValueError as exc:
        raise AssetRegistryError(
            f"asset path must stay inside production data: {raw}"
        ) from exc
    return resolved


def _validate_video_artifact(path: Path) -> None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "v:0",
                "-show_entries",
                "stream=codec_type,width,height:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise AssetRegistryError(
            "ffprobe is required to register a file video asset"
        ) from exc
    if result.returncode != 0:
        raise AssetRegistryError(
            f"file asset is not a readable video: {path}: {result.stderr[-300:]}"
        )
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        duration = float(payload["format"]["duration"])
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AssetRegistryError(
            f"file asset has incomplete video metadata: {path}"
        ) from exc
    if stream.get("codec_type") != "video" or duration <= 0 or width <= 0 or height <= 0:
        raise AssetRegistryError(f"file asset has no usable video stream: {path}")


def _validate_audio_artifact(path: Path) -> None:
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "stream=codec_type:format=duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            check=False,
        )
    except FileNotFoundError as exc:
        raise AssetRegistryError(
            "ffprobe is required to register a file audio asset"
        ) from exc
    if result.returncode != 0:
        raise AssetRegistryError(
            f"file asset is not readable audio: {path}: {result.stderr[-300:]}"
        )
    try:
        payload = json.loads(result.stdout)
        stream = payload["streams"][0]
        duration = float(payload["format"]["duration"])
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise AssetRegistryError(
            f"file asset has incomplete audio metadata: {path}"
        ) from exc
    if stream.get("codec_type") != "audio" or duration <= 0:
        raise AssetRegistryError(f"file asset has no usable audio stream: {path}")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validation_sha256(facts: dict, artifact_sha256: str) -> str:
    proof = {
        "artifact_path": str(facts["artifact_path"]).replace("\\", "/"),
        "artifact_sha256": artifact_sha256,
        "editorial_role": facts["editorial_role"],
        "capture_method": facts["capture_method"],
        "state_id": facts["state_id"],
        "build_id": facts["build_id"],
        "action_id": facts.get("action_id"),
        "seed": facts.get("seed"),
        "parameters": facts.get("parameters"),
        "initial_semantic_hash": facts.get("initial_semantic_hash"),
        "action_semantic_hash": facts.get("action_semantic_hash"),
        "metadata_path": facts["metadata_path"],
        "metadata_sha256": facts["metadata_sha256"],
        "game_report_path": facts.get("game_report_path"),
        "game_report_sha256": facts.get("game_report_sha256"),
        "capture_batch_path": facts["capture_batch_path"],
        "capture_batch_sha256": facts["capture_batch_sha256"],
        "capture_results_path": facts["capture_results_path"],
        "capture_results_sha256": facts["capture_results_sha256"],
        "width": facts.get("actual_width"),
        "height": facts.get("actual_height"),
        "fps": facts.get("actual_fps"),
        "duration": facts.get("actual_duration"),
        "orientation": facts.get("actual_orientation"),
        "client_rect": facts.get("client_rect"),
        "simulation_rate": facts.get("simulation_rate"),
        "continuous": facts.get("continuous"),
        "clean_ui": facts.get("clean_ui"),
        "client_area": facts.get("client_area"),
        "cursor_visible": facts.get("cursor_visible"),
        "content_seconds": facts.get("content_seconds"),
        "head_handle_seconds": facts.get("head_handle_seconds"),
        "tail_handle_seconds": facts.get("tail_handle_seconds"),
        "frame_audit_passed": facts.get("frame_audit_passed"),
        "frame_audit": facts.get("frame_audit"),
        "game_elapsed_seconds": facts.get("game_elapsed_seconds"),
        "measured_playback_rate": facts.get("measured_playback_rate"),
        "encoded_duration_seconds": facts.get("encoded_duration_seconds"),
        "action_media_seconds": facts.get("action_media_seconds"),
        "presentation": facts.get("presentation"),
    }
    payload = json.dumps(
        proof,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _file_validation_sha256(
    *,
    artifact_path: str,
    artifact_sha256: str,
    editorial_role: str,
    provenance_path: str,
    provenance_sha256: str,
) -> str:
    payload = json.dumps(
        {
            "artifact_path": artifact_path.replace("\\", "/"),
            "artifact_sha256": artifact_sha256,
            "editorial_role": editorial_role,
            "capture_method": "file",
            "provenance_path": provenance_path.replace("\\", "/"),
            "provenance_sha256": provenance_sha256,
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def load_asset_registry(production_root: str | Path) -> AssetRegistry:
    root = Path(production_root).resolve()
    path = _registry_path(root)
    if not path.is_file():
        return AssetRegistry(root=str(root))
    try:
        return AssetRegistry.model_validate_json(path.read_text(encoding="utf-8"))
    except (OSError, ValidationError) as exc:
        raise AssetRegistryError(f"invalid asset registry {path}: {exc}") from exc


def _save(root: Path, registry: AssetRegistry) -> AssetRegistry:
    registry.updated_at = _now()
    path = _registry_path(root)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    temporary.write_text(
        json.dumps(registry.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    os.replace(temporary, path)
    return registry


def _register_ingested_captures(
    production_root: str | Path,
    captures: list[dict],
) -> AssetRegistry:
    root = Path(production_root).resolve()
    try:
        validated = [_IngestedCapture.model_validate(item) for item in captures]
    except ValidationError as exc:
        raise AssetRegistryError(f"invalid trusted capture ingest: {exc}") from exc
    with _registry_write_lock(root):
        registry = load_asset_registry(root).model_copy(deep=True)
        for facts in validated:
            _upsert_validated_capture(root, registry, facts.model_dump())
        return _save(root, registry)


def _upsert_validated_capture(
    root: Path,
    registry: AssetRegistry,
    facts: dict,
) -> None:
    artifact_path = _artifact_path(root, str(facts["artifact_path"]))
    if not artifact_path.is_file():
        raise AssetRegistryError(f"captured asset is missing: {artifact_path}")
    actual_sha = _sha256(artifact_path)
    if actual_sha.casefold() != str(facts["artifact_sha256"]).casefold():
        raise AssetRegistryError("captured asset SHA mismatch")
    for path_field, hash_field in (
        ("metadata_path", "metadata_sha256"),
        ("capture_batch_path", "capture_batch_sha256"),
        ("capture_results_path", "capture_results_sha256"),
    ):
        proof_path = _artifact_path(root, str(facts[path_field]))
        if not proof_path.is_file():
            raise AssetRegistryError(f"capture proof is missing: {proof_path}")
        if _sha256(proof_path).casefold() != str(facts[hash_field]).casefold():
            raise AssetRegistryError(f"capture proof SHA mismatch: {path_field}")
    if facts["editorial_role"] in {"gameplay", "debug_proof"}:
        game_report_path = _artifact_path(root, str(facts["game_report_path"]))
        if not game_report_path.is_file():
            raise AssetRegistryError(
                f"game capture report is missing: {game_report_path}"
            )
        if _sha256(game_report_path).casefold() != str(
            facts["game_report_sha256"]
        ).casefold():
            raise AssetRegistryError("game capture report SHA mismatch")

    validation_sha = _validation_sha256(facts, actual_sha)
    asset_id = f"capture:{facts['request_id']}"
    existing = next(
        (asset for asset in registry.assets if asset.asset_id == asset_id),
        None,
    )
    same_revision = (
        existing is not None
        and existing.artifact_sha256.casefold() == actual_sha.casefold()
        and existing.validation_sha256 == validation_sha
    )
    record = RegisteredAsset(
        asset_id=asset_id,
        revision=existing.revision if same_revision else (existing.revision + 1 if existing else 1),
        status=existing.status if same_revision else "validated",
        artifact_path=str(facts["artifact_path"]).replace("\\", "/"),
        artifact_sha256=actual_sha,
        validation_sha256=validation_sha,
        editorial_role=str(facts["editorial_role"]),
        capture_method=str(facts["capture_method"]),
        state_id=str(facts["state_id"]),
        build_id=str(facts["build_id"]),
        action_id=facts.get("action_id"),
        seed=facts.get("seed"),
        parameters=facts.get("parameters") or {},
        initial_semantic_hash=facts.get("initial_semantic_hash"),
        action_semantic_hash=facts.get("action_semantic_hash"),
        metadata_path=str(facts["metadata_path"]).replace("\\", "/"),
        metadata_sha256=str(facts["metadata_sha256"]).lower(),
        game_report_path=(
            str(facts["game_report_path"]).replace("\\", "/")
            if facts.get("game_report_path")
            else None
        ),
        game_report_sha256=(
            str(facts["game_report_sha256"]).lower()
            if facts.get("game_report_sha256")
            else None
        ),
        capture_batch_path=str(facts["capture_batch_path"]).replace("\\", "/"),
        capture_batch_sha256=str(facts["capture_batch_sha256"]).lower(),
        capture_results_path=str(facts["capture_results_path"]).replace("\\", "/"),
        capture_results_sha256=str(facts["capture_results_sha256"]).lower(),
        width=facts.get("actual_width"),
        height=facts.get("actual_height"),
        fps=facts.get("actual_fps"),
        duration=facts.get("actual_duration"),
        orientation=facts.get("actual_orientation"),
        client_rect=facts.get("client_rect"),
        simulation_rate=facts.get("simulation_rate"),
        continuous=facts.get("continuous"),
        clean_ui=facts.get("clean_ui"),
        client_area=facts.get("client_area"),
        cursor_visible=facts.get("cursor_visible"),
        content_seconds=facts.get("content_seconds"),
        head_handle_seconds=facts.get("head_handle_seconds"),
        tail_handle_seconds=facts.get("tail_handle_seconds"),
        frame_audit_passed=facts.get("frame_audit_passed"),
        frame_audit=facts.get("frame_audit"),
        game_elapsed_seconds=facts.get("game_elapsed_seconds"),
        measured_playback_rate=facts.get("measured_playback_rate"),
        encoded_duration_seconds=facts.get("encoded_duration_seconds"),
        action_media_seconds=facts.get("action_media_seconds"),
        presentation=facts.get("presentation"),
        validated_at=_now(),
        approved_sha256=existing.approved_sha256 if same_revision else None,
        approved_validation_sha256=(
            existing.approved_validation_sha256 if same_revision else None
        ),
        approved_at=existing.approved_at if same_revision else None,
        approved_by=existing.approved_by if same_revision else None,
    )
    registry.assets = [
        asset for asset in registry.assets if asset.asset_id != asset_id
    ] + [record]
    registry.assets.sort(key=lambda asset: asset.asset_id)


def register_file_asset(
    production_root: str | Path,
    *,
    asset_id: str,
    artifact_path: str,
    editorial_role: str,
    source_type: str,
    source_url: str = "",
    license_name: str = "",
    credit: str = "",
) -> AssetRegistry:
    """Register non-gameplay video or audio with hash-bound provenance."""

    if re.fullmatch(r"[A-Za-z0-9_.:-]{1,160}", asset_id) is None:
        raise AssetRegistryError("file asset id contains unsafe characters")
    if editorial_role not in {"reference", "presentation"}:
        raise AssetRegistryError(
            "file assets require reference/presentation role; debug_proof "
            "must use deterministic capture ingest"
        )
    if source_type not in {"stock", "purchased", "licensed", "owned", "reference"}:
        raise AssetRegistryError("unsupported file asset source_type")
    root = Path(production_root).resolve()
    artifact = _artifact_path(root, artifact_path)
    if not artifact.is_file():
        raise AssetRegistryError(f"file asset is missing: {artifact}")
    normalized_artifact = artifact.relative_to(root).as_posix()
    render_manifest = artifact.with_suffix(artifact.suffix + ".render.json")
    if (
        normalized_artifact.startswith("data/infographics/")
        or render_manifest.is_file()
    ):
        raise AssetRegistryError(
            "HyperFrames outputs cannot use generic asset registration; "
            "wire the render_manifest so final-quality evidence is enforced"
        )
    audio_extensions = {".aac", ".flac", ".m4a", ".mp3", ".ogg", ".opus", ".wav"}
    media_kind = "audio" if artifact.suffix.casefold() in audio_extensions else "video"
    if media_kind == "audio":
        _validate_audio_artifact(artifact)
    else:
        _validate_video_artifact(artifact)
    artifact_sha = _sha256(artifact)
    provenance_name = hashlib.sha256(asset_id.encode("utf-8")).hexdigest()
    provenance = (
        root / "data" / "assets" / "provenance" / f"{provenance_name}.json"
    )
    provenance_payload = {
        "schema": (
            "devlog.audio_provenance"
            if media_kind == "audio"
            else "devlog.video_provenance"
        ),
        "version": 1,
        "asset_id": asset_id,
        "artifact_path": normalized_artifact,
        "artifact_sha256": artifact_sha,
        "editorial_role": editorial_role,
        "source_type": source_type,
        "source_url": source_url,
        "license": license_name,
        "credit": credit,
    }
    with _registry_write_lock(root):
        provenance.parent.mkdir(parents=True, exist_ok=True)
        provenance_temp = provenance.with_name(
            f".{provenance.name}.{os.getpid()}.tmp"
        )
        provenance_temp.write_text(
            json.dumps(provenance_payload, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        os.replace(provenance_temp, provenance)
        provenance_sha = _sha256(provenance)
        provenance_rel = provenance.relative_to(root).as_posix()
        validation_sha = _file_validation_sha256(
            artifact_path=normalized_artifact,
            artifact_sha256=artifact_sha,
            editorial_role=editorial_role,
            provenance_path=provenance_rel,
            provenance_sha256=provenance_sha,
        )
        registry = load_asset_registry(root).model_copy(deep=True)
        existing = next(
            (asset for asset in registry.assets if asset.asset_id == asset_id),
            None,
        )
        same_revision = (
            existing is not None
            and existing.artifact_sha256 == artifact_sha
            and existing.validation_sha256 == validation_sha
        )
        record = RegisteredAsset(
            asset_id=asset_id,
            revision=(
                existing.revision
                if same_revision
                else existing.revision + 1
                if existing
                else 1
            ),
            status=existing.status if same_revision else "validated",
            artifact_path=normalized_artifact,
            artifact_sha256=artifact_sha,
            validation_sha256=validation_sha,
            editorial_role=editorial_role,
            capture_method="file",
            state_id="",
            build_id="",
            provenance_path=provenance_rel,
            provenance_sha256=provenance_sha,
            validated_at=_now(),
            approved_sha256=existing.approved_sha256 if same_revision else None,
            approved_validation_sha256=(
                existing.approved_validation_sha256 if same_revision else None
            ),
            approved_at=existing.approved_at if same_revision else None,
            approved_by=existing.approved_by if same_revision else None,
        )
        registry.assets = [
            asset for asset in registry.assets if asset.asset_id != asset_id
        ] + [record]
        registry.assets.sort(key=lambda asset: asset.asset_id)
        return _save(root, registry)


def _verify_registered_asset(root: Path, asset: RegisteredAsset) -> Path:
    """Revalidate mutable files and the current role contract on every use."""

    artifact = _artifact_path(root, asset.artifact_path)
    if not artifact.is_file() or _sha256(artifact) != asset.artifact_sha256:
        raise AssetRegistryError(f"approved asset is stale: {asset.asset_id}")
    if asset.capture_method != "file":
        for path_value, expected_hash in (
            (asset.metadata_path, asset.metadata_sha256),
            (asset.capture_batch_path, asset.capture_batch_sha256),
            (asset.capture_results_path, asset.capture_results_sha256),
        ):
            if not path_value or not expected_hash:
                raise AssetRegistryError(
                    f"asset lacks trusted capture ingest proof: {asset.asset_id}"
                )
            proof_path = _artifact_path(root, path_value)
            if not proof_path.is_file() or _sha256(proof_path) != expected_hash:
                raise AssetRegistryError(
                    f"asset capture ingest proof is stale: {asset.asset_id}"
                )
    else:
        render_manifest = artifact.with_suffix(artifact.suffix + ".render.json")
        if (
            asset.artifact_path.replace("\\", "/").startswith(
                "data/infographics/"
            )
            or render_manifest.is_file()
        ):
            raise AssetRegistryError(
                "HyperFrames outputs require a final-quality render_manifest; "
                f"generic approval is invalid: {asset.asset_id}"
            )
        if not asset.provenance_path or not asset.provenance_sha256:
            raise AssetRegistryError(
                f"file asset lacks provenance proof: {asset.asset_id}"
            )
        provenance = _artifact_path(root, asset.provenance_path)
        if (
            not provenance.is_file()
            or _sha256(provenance) != asset.provenance_sha256
        ):
            raise AssetRegistryError(
                f"file asset provenance is stale: {asset.asset_id}"
            )
        try:
            payload = json.loads(provenance.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise AssetRegistryError(
                f"invalid file asset provenance: {asset.asset_id}"
            ) from exc
        if (
            not isinstance(payload, dict)
            or payload.get("schema")
            not in {"devlog.video_provenance", "devlog.audio_provenance"}
            or payload.get("version") != 1
            or payload.get("artifact_path") != asset.artifact_path
            or payload.get("artifact_sha256") != asset.artifact_sha256
            or payload.get("editorial_role") != asset.editorial_role
        ):
            raise AssetRegistryError(
                f"file asset provenance identity mismatch: {asset.asset_id}"
            )
        if asset.editorial_role == "debug_proof":
            raise AssetRegistryError(
                "debug_proof requires deterministic capture ingest: "
                f"{asset.asset_id}"
            )
    if asset.editorial_role == "debug_proof":
        if not asset.game_report_path or not asset.game_report_sha256:
            raise AssetRegistryError(
                f"asset lacks game capture report: {asset.asset_id}"
            )
        game_report_path = _artifact_path(root, asset.game_report_path)
        if (
            not game_report_path.is_file()
            or _sha256(game_report_path) != asset.game_report_sha256
        ):
            raise AssetRegistryError(
                f"asset game capture report is stale: {asset.asset_id}"
            )
        debug_contract = {
            "capture_method": asset.capture_method == "deterministic_devapi",
            "state_id": bool(asset.state_id),
            "build_id": re.fullmatch(
                r"exe-sha256:[0-9a-fA-F]{64}",
                asset.build_id,
            ) is not None,
            "seeded_state": (
                asset.seed is not None
                and bool(asset.initial_semantic_hash)
            ),
            "action_state": (
                not asset.action_id or bool(asset.action_semantic_hash)
            ),
        }
        failed = [name for name, passed in debug_contract.items() if not passed]
        if failed:
            raise AssetRegistryError(
                f"debug_proof asset fails trusted contract "
                f"({', '.join(failed)}): {asset.asset_id}"
            )
    if asset.editorial_role == "gameplay":
        if not asset.game_report_path or not asset.game_report_sha256:
            raise AssetRegistryError(
                f"asset lacks game capture report: {asset.asset_id}"
            )
        game_report_path = _artifact_path(root, asset.game_report_path)
        if (
            not game_report_path.is_file()
            or _sha256(game_report_path) != asset.game_report_sha256
        ):
            raise AssetRegistryError(
                f"asset game capture report is stale: {asset.asset_id}"
            )
        gameplay_contract = {
            "capture_method": asset.capture_method == "realtime_window",
            "build_id": re.fullmatch(
                r"exe-sha256:[0-9a-fA-F]{64}", asset.build_id
            ) is not None,
            "seeded_state": (
                asset.seed is not None
                and bool(asset.initial_semantic_hash)
            ),
            "action_state": (
                not asset.action_id or bool(asset.action_semantic_hash)
            ),
            "simulation_rate": asset.simulation_rate == 1.0,
            "continuous": asset.continuous is True,
            "clean_ui": asset.clean_ui is True,
            "client_area": asset.client_area is True,
            "cursor_visible": asset.cursor_visible is False,
            "head_handle_seconds": (asset.head_handle_seconds or 0.0) >= 5.0,
            "tail_handle_seconds": (asset.tail_handle_seconds or 0.0) >= 5.0,
            "frame_audit": asset.frame_audit_passed is True,
            "game_report": bool(
                asset.game_report_path and asset.game_report_sha256
            ),
            "playback_rate": (
                asset.measured_playback_rate is not None
                and 0.97 <= asset.measured_playback_rate <= 1.03
            ),
        }
        failed = [name for name, passed in gameplay_contract.items() if not passed]
        if failed:
            raise AssetRegistryError(
                f"gameplay asset fails trusted contract ({', '.join(failed)}): "
                f"{asset.asset_id}"
            )
    return artifact


def approve_asset(
    production_root: str | Path,
    asset_id: str,
    *,
    expected_sha256: str,
    expected_revision: int,
    expected_validation_sha256: str,
    approved_by: str,
) -> AssetRegistry:
    root = Path(production_root).resolve()
    with _registry_write_lock(root):
        registry = load_asset_registry(root)
        asset = next(
            (item for item in registry.assets if item.asset_id == asset_id),
            None,
        )
        if asset is None:
            raise AssetRegistryError(f"unknown asset: {asset_id}")
        if asset.artifact_sha256.casefold() != expected_sha256.casefold():
            raise AssetRegistryError(f"asset SHA mismatch: {asset_id}")
        if asset.revision != expected_revision:
            raise AssetRegistryError(f"asset revision mismatch: {asset_id}")
        if (
            asset.validation_sha256.casefold()
            != expected_validation_sha256.casefold()
        ):
            raise AssetRegistryError(f"asset validation SHA mismatch: {asset_id}")
        _verify_registered_asset(root, asset)
        asset.status = "approved"
        asset.approved_sha256 = asset.artifact_sha256
        asset.approved_validation_sha256 = asset.validation_sha256
        asset.approved_at = _now()
        asset.approved_by = approved_by
        return _save(root, registry)


def resolve_approved_asset(
    production_root: str | Path,
    asset_id: str,
) -> Path:
    root = Path(production_root).resolve()
    registry = load_asset_registry(root)
    asset = next(
        (item for item in registry.assets if item.asset_id == asset_id),
        None,
    )
    if asset is None:
        raise AssetRegistryError(f"unknown asset: {asset_id}")
    if (
        asset.status != "approved"
        or asset.approved_sha256 != asset.artifact_sha256
        or asset.approved_validation_sha256 != asset.validation_sha256
    ):
        raise AssetRegistryError(f"asset is not approved: {asset_id}")
    return _verify_registered_asset(root, asset)


__all__ = [
    "AssetRegistry",
    "AssetRegistryError",
    "RegisteredAsset",
    "approve_asset",
    "load_asset_registry",
    "register_file_asset",
    "resolve_approved_asset",
]
