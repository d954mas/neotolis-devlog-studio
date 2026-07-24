"""Hash-bound semantic identity for production assets."""
from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError


class AssetRegistryError(ValueError):
    """Invalid registry operation or stale artifact identity."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


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
    width: int | None = None
    height: int | None = None
    fps: float | None = None
    duration: float | None = None
    head_handle_seconds: float | None = None
    tail_handle_seconds: float | None = None
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
        "width": facts.get("actual_width"),
        "height": facts.get("actual_height"),
        "fps": facts.get("actual_fps"),
        "duration": facts.get("actual_duration"),
        "head_handle_seconds": facts.get("head_handle_seconds"),
        "tail_handle_seconds": facts.get("tail_handle_seconds"),
        "metadata_sha256": facts.get("metadata_sha256"),
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


def register_validated_capture(
    production_root: str | Path,
    facts: dict,
) -> AssetRegistry:
    return register_validated_captures(production_root, [facts])


def register_validated_captures(
    production_root: str | Path,
    captures: list[dict],
) -> AssetRegistry:
    root = Path(production_root).resolve()
    registry = load_asset_registry(root).model_copy(deep=True)
    for facts in captures:
        _upsert_validated_capture(root, registry, facts)
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
        width=facts.get("actual_width"),
        height=facts.get("actual_height"),
        fps=facts.get("actual_fps"),
        duration=facts.get("actual_duration"),
        head_handle_seconds=facts.get("head_handle_seconds"),
        tail_handle_seconds=facts.get("tail_handle_seconds"),
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
    artifact = _artifact_path(root, asset.artifact_path)
    if not artifact.is_file() or _sha256(artifact) != asset.artifact_sha256:
        raise AssetRegistryError(f"asset file changed before approval: {asset_id}")
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
    "register_validated_capture",
    "register_validated_captures",
    "resolve_approved_asset",
]
