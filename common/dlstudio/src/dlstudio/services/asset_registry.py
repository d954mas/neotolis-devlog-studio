"""Hash-bound semantic identity for production assets."""
from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class AssetRegistryError(ValueError):
    """Invalid registry operation or stale artifact identity."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class _IngestedCapture(_Model):
    """Facts produced only after the v2 capture-batch audit has passed."""

    request_id: str = Field(min_length=1)
    artifact_path: str = Field(min_length=1)
    artifact_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    metadata_path: str = Field(min_length=1)
    metadata_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    capture_batch_path: str = Field(min_length=1)
    capture_batch_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    capture_results_path: str = Field(min_length=1)
    capture_results_sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    editorial_role: str
    capture_method: str
    state_id: str
    build_id: str
    action_id: str | None = None
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

    @model_validator(mode="after")
    def validate_gameplay_contract(self) -> "_IngestedCapture":
        if self.editorial_role != "gameplay":
            return self
        if self.capture_method != "realtime_window":
            raise ValueError("gameplay requires capture_method=realtime_window")
        if re.fullmatch(r"exe-sha256:[0-9a-fA-F]{64}", self.build_id) is None:
            raise ValueError("gameplay build_id requires exe-sha256:<64 hex>")
        if not self.state_id:
            raise ValueError("gameplay requires state_id")
        if not self.action_id:
            raise ValueError("gameplay requires action_id")
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
    metadata_path: str | None = None
    metadata_sha256: str | None = None
    capture_batch_path: str | None = None
    capture_batch_sha256: str | None = None
    capture_results_path: str | None = None
    capture_results_sha256: str | None = None
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
        "metadata_path": facts["metadata_path"],
        "metadata_sha256": facts["metadata_sha256"],
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
    }
    payload = json.dumps(
        proof,
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
    path.write_text(
        json.dumps(registry.model_dump(mode="json"), ensure_ascii=False, indent=2)
        + "\n",
        encoding="utf-8",
    )
    return registry


def _register_ingested_captures(
    production_root: str | Path,
    captures: list[dict],
) -> AssetRegistry:
    root = Path(production_root).resolve()
    registry = load_asset_registry(root).model_copy(deep=True)
    try:
        validated = [_IngestedCapture.model_validate(item) for item in captures]
    except ValidationError as exc:
        raise AssetRegistryError(f"invalid trusted capture ingest: {exc}") from exc
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
        metadata_path=str(facts["metadata_path"]).replace("\\", "/"),
        metadata_sha256=str(facts["metadata_sha256"]).lower(),
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
    artifact = _artifact_path(root, asset.artifact_path)
    if not artifact.is_file() or _sha256(artifact) != asset.artifact_sha256:
        raise AssetRegistryError(f"asset file changed before approval: {asset_id}")
    for path_value, expected_hash in (
        (asset.metadata_path, asset.metadata_sha256),
        (asset.capture_batch_path, asset.capture_batch_sha256),
        (asset.capture_results_path, asset.capture_results_sha256),
    ):
        if not path_value or not expected_hash:
            raise AssetRegistryError(
                f"asset lacks trusted capture ingest proof: {asset_id}"
            )
        proof_path = _artifact_path(root, path_value)
        if not proof_path.is_file() or _sha256(proof_path) != expected_hash:
            raise AssetRegistryError(
                f"asset capture ingest proof is stale: {asset_id}"
            )
    if asset.editorial_role == "gameplay":
        gameplay_contract = {
            "capture_method": asset.capture_method == "realtime_window",
            "build_id": re.fullmatch(
                r"exe-sha256:[0-9a-fA-F]{64}", asset.build_id
            ) is not None,
            "simulation_rate": asset.simulation_rate == 1.0,
            "continuous": asset.continuous is True,
            "clean_ui": asset.clean_ui is True,
            "client_area": asset.client_area is True,
            "cursor_visible": asset.cursor_visible is False,
            "head_handle_seconds": (asset.head_handle_seconds or 0.0) >= 5.0,
            "tail_handle_seconds": (asset.tail_handle_seconds or 0.0) >= 5.0,
            "frame_audit": asset.frame_audit_passed is True,
        }
        failed = [name for name, passed in gameplay_contract.items() if not passed]
        if failed:
            raise AssetRegistryError(
                f"gameplay asset fails trusted contract ({', '.join(failed)}): "
                f"{asset_id}"
            )
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
    artifact = _artifact_path(root, asset.artifact_path)
    if not artifact.is_file() or _sha256(artifact) != asset.artifact_sha256:
        raise AssetRegistryError(f"approved asset is stale: {asset_id}")
    return artifact


__all__ = [
    "AssetRegistry",
    "AssetRegistryError",
    "RegisteredAsset",
    "approve_asset",
    "load_asset_registry",
    "resolve_approved_asset",
]
