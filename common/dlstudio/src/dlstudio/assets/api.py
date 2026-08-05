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
    BlobRef,
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
class AssetRevisionRef:
    asset_id: str
    object: BlobRef

    def __post_init__(self) -> None:
        DomainId(self.asset_id)

    @property
    def revision_hash(self) -> str:
        return self.object.sha256

    def as_payload(self) -> dict[str, object]:
        return {
            "asset_id": self.asset_id,
            "object": self.object.as_payload(),
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
        if (self.sample_rate is None) != (self.channels is None):
            raise ValueError("audio facts require sample_rate and channels")
        if self.kind == "video":
            if (
                self.width is None
                or self.duration_ns is None
                or self.fps_num is None
            ):
                raise ValueError("video requires geometry, duration and fps")
        elif self.kind == "audio":
            if self.duration_ns is None or self.sample_rate is None:
                raise ValueError("audio requires duration, sample_rate and channels")
            if self.width is not None or self.fps_num is not None:
                raise ValueError("audio media cannot contain geometry or fps")
        elif self.kind == "image":
            if self.width is None:
                raise ValueError("image requires geometry")
            if (
                self.duration_ns is not None
                or self.fps_num is not None
                or self.sample_rate is not None
            ):
                raise ValueError("image media cannot contain timing or audio facts")
        elif any(
            value is not None
            for value in (
                self.duration_ns,
                self.width,
                self.fps_num,
                self.sample_rate,
            )
        ):
            raise ValueError(f"{self.kind} media cannot contain stream facts")

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
    script_ref: BlobRef | None = None
    provider_receipt_ref: BlobRef | None = None
    supporting_evidence: tuple[BlobRef, ...] = ()

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
        if (self.native_width is None) != (self.native_height is None):
            raise ValueError("native geometry must include width and height")
        if self.native_width is not None and (
            self.native_width <= 0 or self.native_height <= 0  # type: ignore[operator]
        ):
            raise ValueError("native geometry must be positive")
        for ref, label in (
            (self.script_ref, "script evidence"),
            (self.provider_receipt_ref, "provider receipt"),
        ):
            if ref is not None and ref.size == 0:
                raise ValueError(f"{label} must be non-empty")
        evidence = tuple(
            sorted(
                set(self.supporting_evidence),
                key=lambda ref: (ref.sha256, ref.size),
            )
        )
        if any(ref.size == 0 for ref in evidence):
            raise ValueError("provenance evidence must be non-empty")
        object.__setattr__(self, "supporting_evidence", evidence)
        recorded_methods = {
            "realtime_window",
            "deterministic_devapi",
            "voice_take",
        }
        if self.origin == "recorded" and self.capture_method not in recorded_methods:
            raise ValueError("recorded provenance requires a supported capture method")
        if self.capture_method in recorded_methods and self.origin != "recorded":
            raise ValueError("capture method requires recorded provenance")
        if self.capture_method == "realtime_window":
            if not all(
                (
                    self.state_id,
                    self.build_id,
                    self.native_width,
                    self.native_height,
                    self.provider_receipt_ref,
                )
            ):
                raise ValueError(
                    "realtime gameplay requires state/build/native geometry "
                    "and provider receipt"
                )
        if self.capture_method == "deterministic_devapi" and not all(
            (self.state_id, self.build_id, self.provider_receipt_ref)
        ):
            raise ValueError(
                "deterministic capture requires state/build/provider receipt"
            )
        if self.capture_method == "voice_take":
            if not all((self.state_id, self.script_ref, self.provider_receipt_ref)):
                raise ValueError(
                    "voice take requires take id, script evidence and provider receipt"
                )
            if self.build_id is not None or self.native_width is not None:
                raise ValueError("voice take cannot contain build or geometry")
        elif self.script_ref is not None:
            raise ValueError("script evidence belongs only to a voice take")

    def as_payload(self) -> dict[str, Any]:
        return {
            "origin": self.origin,
            "capture_method": self.capture_method,
            "logical_source": self.logical_source,
            "state_id": self.state_id,
            "build_id": self.build_id,
            "native_width": self.native_width,
            "native_height": self.native_height,
            "script_ref": (
                None if self.script_ref is None else self.script_ref.as_payload()
            ),
            "provider_receipt_ref": (
                None
                if self.provider_receipt_ref is None
                else self.provider_receipt_ref.as_payload()
            ),
            "supporting_evidence": [
                ref.as_payload() for ref in self.supporting_evidence
            ],
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "Provenance":
        payload = dict(value)
        payload["script_ref"] = (
            None
            if value.get("script_ref") is None
            else BlobRef.from_payload(value["script_ref"])
        )
        payload["provider_receipt_ref"] = (
            None
            if value.get("provider_receipt_ref") is None
            else BlobRef.from_payload(value["provider_receipt_ref"])
        )
        payload["supporting_evidence"] = tuple(
            BlobRef.from_payload(item)
            for item in value.get("supporting_evidence", ())
        )
        return cls(**payload)

    @property
    def evidence_refs(self) -> tuple[BlobRef, ...]:
        return tuple(
            ref
            for ref in (
                self.script_ref,
                self.provider_receipt_ref,
                *self.supporting_evidence,
            )
            if ref is not None
        )


@dataclass(frozen=True, slots=True)
class Approval:
    status: Literal["pending", "validated", "approved", "rejected"]
    evidence_refs: tuple[BlobRef, ...] = ()
    reason: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {
            "pending",
            "validated",
            "approved",
            "rejected",
        }:
            raise ValueError("unsupported approval status")
        refs = tuple(
            sorted(
                set(self.evidence_refs),
                key=lambda ref: (ref.sha256, ref.size),
            )
        )
        if any(ref.size == 0 for ref in refs):
            raise ValueError("approval evidence must be non-empty")
        object.__setattr__(self, "evidence_refs", refs)
        if self.status in {"validated", "approved"} and not refs:
            raise ValueError(f"{self.status} asset requires evidence")
        if self.status == "rejected" and not self.reason:
            raise ValueError("rejected asset requires a reason")

    def as_payload(self) -> dict[str, Any]:
        return {
            "status": self.status,
            "evidence_refs": [ref.as_payload() for ref in self.evidence_refs],
            "reason": self.reason,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "Approval":
        return cls(
            status=value["status"],
            evidence_refs=tuple(
                BlobRef.from_payload(item)
                for item in value.get("evidence_refs", ())
            ),
            reason=value.get("reason"),
        )


@dataclass(frozen=True, slots=True)
class License:
    license_id: str
    attribution_required: bool
    attribution: str | None = None
    redistribution_allowed: bool = True
    evidence_ref: BlobRef | None = None

    def __post_init__(self) -> None:
        if not self.license_id:
            raise ValueError("license_id is required")
        if self.attribution_required and not self.attribution:
            raise ValueError("attribution-required license needs copy text")
        if self.evidence_ref is not None and self.evidence_ref.size == 0:
            raise ValueError("license evidence must be non-empty")

    def as_payload(self) -> dict[str, Any]:
        return {
            "license_id": self.license_id,
            "attribution_required": self.attribution_required,
            "attribution": self.attribution,
            "redistribution_allowed": self.redistribution_allowed,
            "evidence_ref": (
                None
                if self.evidence_ref is None
                else self.evidence_ref.as_payload()
            ),
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "License":
        payload = dict(value)
        payload["evidence_ref"] = (
            None
            if value.get("evidence_ref") is None
            else BlobRef.from_payload(value["evidence_ref"])
        )
        return cls(**payload)


@dataclass(frozen=True, slots=True)
class AssetRevision:
    asset_id: str
    blob: BlobRef
    media: MediaFacts
    provenance: Provenance
    approval: Approval
    license: License

    DOMAIN = "dlstudio.asset_revision"
    VERSION = 4

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

    @property
    def reachable_blobs(self) -> tuple[BlobRef, ...]:
        return (
            self.blob,
            *self.provenance.evidence_refs,
            *self.approval.evidence_refs,
            *((self.license.evidence_ref,) if self.license.evidence_ref else ()),
        )

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
        raw = self.canonical_bytes()
        return AssetRevisionRef(
            self.asset_id, BlobRef(self.revision_hash, len(raw))
        )

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
    VERSION = 2

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
                    object=BlobRef.from_payload(value["object"]),
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
    ) -> AssetIngestResult: ...


class AssetReadPort(Protocol):
    def current(self, asset_id: str) -> AssetRevision: ...

    def list_current(self) -> tuple[AssetRevision, ...]: ...
