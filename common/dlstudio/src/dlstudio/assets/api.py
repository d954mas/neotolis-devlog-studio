"""Immutable asset identity and trust contracts.

This module is the sole owner of blob identity, media facts, provenance,
approval, and licensing.  It has no filesystem or process dependencies.
"""

from __future__ import annotations

import re
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, Literal, Protocol

from dlstudio.foundation.api import (
    DomainId,
    canonical_bytes,
    canonical_hash,
    normalize_logical_path,
)

_SHA256_RE = re.compile(r"[0-9a-f]{64}")


def _sha256(value: str | None, label: str) -> None:
    if value is not None and _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"invalid {label} sha256")


@dataclass(frozen=True, slots=True)
class BlobRef:
    sha256: str
    size: int

    def __post_init__(self) -> None:
        _sha256(self.sha256, "blob")
        if self.size < 0:
            raise ValueError("negative blob size")

    def as_payload(self) -> dict[str, object]:
        return {"sha256": self.sha256, "size": self.size}

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "BlobRef":
        return cls(sha256=str(value["sha256"]), size=int(value["size"]))


@dataclass(frozen=True, slots=True)
class AssetRevisionRef:
    asset_id: str
    revision_hash: str

    def __post_init__(self) -> None:
        DomainId(self.asset_id)
        _sha256(self.revision_hash, "asset revision")

    def as_payload(self) -> dict[str, str]:
        return {
            "asset_id": self.asset_id,
            "revision_hash": self.revision_hash,
        }


@dataclass(frozen=True, slots=True)
class MediaFacts:
    kind: Literal["video", "audio", "image", "font", "data"]
    format_name: str
    duration_ns: int | None = None
    width: int | None = None
    height: int | None = None
    fps_num: int | None = None
    fps_den: int | None = None
    sample_rate: int | None = None
    channels: int | None = None
    codec: str | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"video", "audio", "image", "font", "data"}:
            raise ValueError("unsupported media kind")
        if not self.format_name:
            raise ValueError("media format_name is required")
        for name in (
            "duration_ns",
            "width",
            "height",
            "fps_num",
            "fps_den",
            "sample_rate",
            "channels",
        ):
            value = getattr(self, name)
            if value is not None and value <= 0:
                raise ValueError(f"{name} must be positive")
        if (self.width is None) != (self.height is None):
            raise ValueError("media geometry must include width and height")
        if (self.fps_num is None) != (self.fps_den is None):
            raise ValueError("fps requires numerator and denominator")
        if self.kind in {"video", "image"} and self.width is None:
            raise ValueError(f"{self.kind} requires geometry")
        if self.kind == "audio" and self.sample_rate is None:
            raise ValueError("audio requires sample_rate")

    def as_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "format_name": self.format_name,
            "duration_ns": self.duration_ns,
            "width": self.width,
            "height": self.height,
            "fps_num": self.fps_num,
            "fps_den": self.fps_den,
            "sample_rate": self.sample_rate,
            "channels": self.channels,
            "codec": self.codec,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "MediaFacts":
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class Provenance:
    origin: Literal[
        "generated", "recorded", "stock", "provided", "migrated", "derived"
    ]
    capture_method: str
    logical_source: str | None = None
    state_id: str | None = None
    build_id: str | None = None
    native_width: int | None = None
    native_height: int | None = None
    script_sha256: str | None = None
    provider_receipt_sha256: str | None = None
    parent_revision_hash: str | None = None

    def __post_init__(self) -> None:
        if self.origin not in {
            "generated",
            "recorded",
            "stock",
            "provided",
            "migrated",
            "derived",
        }:
            raise ValueError("unsupported asset origin")
        if not self.capture_method:
            raise ValueError("capture_method is required")
        if self.logical_source is not None:
            object.__setattr__(
                self,
                "logical_source",
                normalize_logical_path(self.logical_source),
            )
        for value, label in (
            (self.script_sha256, "script"),
            (self.provider_receipt_sha256, "provider receipt"),
            (self.parent_revision_hash, "parent revision"),
        ):
            _sha256(value, label)
        if (self.native_width is None) != (self.native_height is None):
            raise ValueError("native geometry must include width and height")
        if self.native_width is not None and (
            self.native_width <= 0 or self.native_height <= 0  # type: ignore[operator]
        ):
            raise ValueError("native geometry must be positive")
        if self.capture_method == "realtime_window":
            if not all(
                (
                    self.state_id,
                    self.build_id,
                    self.native_width,
                    self.native_height,
                    self.provider_receipt_sha256,
                )
            ):
                raise ValueError(
                    "realtime gameplay requires state/build/native geometry "
                    "and provider receipt"
                )
        if self.capture_method == "deterministic_devapi" and not all(
            (self.state_id, self.build_id, self.provider_receipt_sha256)
        ):
            raise ValueError(
                "deterministic capture requires state/build/provider receipt"
            )
        if self.capture_method == "voice_take" and self.script_sha256 is None:
            raise ValueError("voice take requires script hash")

    def as_payload(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "capture_method": self.capture_method,
            "logical_source": self.logical_source,
            "state_id": self.state_id,
            "build_id": self.build_id,
            "native_width": self.native_width,
            "native_height": self.native_height,
            "script_sha256": self.script_sha256,
            "provider_receipt_sha256": self.provider_receipt_sha256,
            "parent_revision_hash": self.parent_revision_hash,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "Provenance":
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class Approval:
    status: Literal["pending", "validated", "approved", "rejected"]
    evidence_sha256: tuple[str, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            "pending",
            "validated",
            "approved",
            "rejected",
        }:
            raise ValueError("unsupported approval status")
        for value in self.evidence_sha256:
            _sha256(value, "approval evidence")
        if self.status in {"validated", "approved"} and not self.evidence_sha256:
            raise ValueError(f"{self.status} asset requires evidence")
        if self.status == "rejected" and not self.reason:
            raise ValueError("rejected asset requires a reason")

    def as_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "evidence_sha256": list(self.evidence_sha256),
            "reason": self.reason,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "Approval":
        return cls(
            status=value["status"],
            evidence_sha256=tuple(value.get("evidence_sha256", ())),
            reason=value.get("reason"),
        )


@dataclass(frozen=True, slots=True)
class License:
    license_id: str
    attribution_required: bool
    attribution: str | None = None
    redistribution_allowed: bool = True

    def __post_init__(self) -> None:
        if not self.license_id:
            raise ValueError("license_id is required")
        if self.attribution_required and not self.attribution:
            raise ValueError("attribution-required license needs copy text")

    def as_payload(self) -> dict[str, Any]:
        return {
            "license_id": self.license_id,
            "attribution_required": self.attribution_required,
            "attribution": self.attribution,
            "redistribution_allowed": self.redistribution_allowed,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "License":
        return cls(**dict(value))


@dataclass(frozen=True, slots=True)
class AssetRevision:
    asset_id: str
    blob: BlobRef
    media: MediaFacts
    provenance: Provenance
    approval: Approval
    license: License

    DOMAIN = "dlstudio.asset_revision"
    VERSION = 1

    def __post_init__(self) -> None:
        DomainId(self.asset_id)
        if (
            self.provenance.native_width is not None
            and self.media.width is not None
            and (
                self.provenance.native_width != self.media.width
                or self.provenance.native_height != self.media.height
            )
        ):
            raise ValueError("native geometry does not match probed media")

    def as_payload(self) -> dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "blob": self.blob.as_payload(),
            "media": self.media.as_payload(),
            "provenance": self.provenance.as_payload(),
            "approval": self.approval.as_payload(),
            "license": self.license.as_payload(),
        }

    @property
    def revision_hash(self) -> str:
        return canonical_hash(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @property
    def ref(self) -> AssetRevisionRef:
        return AssetRevisionRef(self.asset_id, self.revision_hash)

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "AssetRevision":
        import json

        wrapped = json.loads(raw)
        if (
            wrapped.get("$domain") != cls.DOMAIN
            or wrapped.get("$version") != cls.VERSION
        ):
            raise ValueError("invalid asset revision schema")
        value = wrapped["payload"]
        revision = cls(
            asset_id=str(value["asset_id"]),
            blob=BlobRef.from_payload(value["blob"]),
            media=MediaFacts.from_payload(value["media"]),
            provenance=Provenance.from_payload(value["provenance"]),
            approval=Approval.from_payload(value["approval"]),
            license=License.from_payload(value["license"]),
        )
        if revision.canonical_bytes() != raw:
            raise ValueError("asset revision is not canonically encoded")
        return revision


@dataclass(frozen=True, slots=True)
class AssetIndexRevision:
    entries: Mapping[str, AssetRevisionRef] = field(default_factory=dict)

    DOMAIN = "dlstudio.asset_index"
    VERSION = 1

    def __post_init__(self) -> None:
        snapshot = dict(self.entries)
        for asset_id, ref in snapshot.items():
            DomainId(asset_id)
            if ref.asset_id != asset_id:
                raise ValueError("asset index key/ref mismatch")
        object.__setattr__(self, "entries", MappingProxyType(snapshot))

    def as_payload(self) -> dict[str, Any]:
        return {
            "entries": {
                key: ref.as_payload()
                for key, ref in sorted(self.entries.items())
            }
        }

    @property
    def revision_hash(self) -> str:
        return canonical_hash(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "AssetIndexRevision":
        import json

        wrapped = json.loads(raw)
        if (
            wrapped.get("$domain") != cls.DOMAIN
            or wrapped.get("$version") != cls.VERSION
        ):
            raise ValueError("invalid asset index schema")
        index = cls(
            {
                key: AssetRevisionRef(
                    asset_id=str(value["asset_id"]),
                    revision_hash=str(value["revision_hash"]),
                )
                for key, value in wrapped["payload"]["entries"].items()
            }
        )
        if index.canonical_bytes() != raw:
            raise ValueError("asset index is not canonically encoded")
        return index


@dataclass(frozen=True, slots=True)
class AssetIngestResult:
    revision: AssetRevision
    state_root_hash: str
    state_revision: int
    created: bool

    def __post_init__(self) -> None:
        _sha256(self.state_root_hash, "state root")
        if self.state_revision < 1:
            raise ValueError("state revision must be positive")


class AssetIngestPort(Protocol):
    def ingest(
        self,
        source: Path,
        *,
        asset_id: str,
        media: MediaFacts,
        provenance: Provenance,
        approval: Approval,
        license: License,
        expected_revision: int,
        inspect_media: Callable[[Path], MediaFacts],
        implementation: str = "assets.ingest.v1",
        toolchain: str = "python-3.12",
    ) -> AssetIngestResult: ...
