"""A frozen package is the only thing Studio v3 can deliver."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any

from dlstudio.foundation.api import (
    BlobRef,
    DomainId,
    canonical_bytes,
    canonical_hash,
    normalize_logical_path,
)


@dataclass(frozen=True, slots=True)
class PackageFile:
    path: str
    blob: BlobRef

    def __post_init__(self) -> None:
        object.__setattr__(self, "path", normalize_logical_path(self.path))

    def as_payload(self) -> dict[str, object]:
        return {"path": self.path, "blob": self.blob.as_payload()}


@dataclass(frozen=True, slots=True)
class ReleaseCandidate:
    production_id: str
    timeline: BlobRef
    check_policy: BlobRef
    execution: BlobRef
    render_options: BlobRef
    execution_key: str
    final_output: BlobRef
    check_report: BlobRef
    review_verdict: BlobRef
    constraints: BlobRef
    asset_revisions: tuple[BlobRef, ...]
    license_bundle: BlobRef
    package: tuple[PackageFile, ...]

    DOMAIN = "dlstudio.release_candidate"
    VERSION = 2

    def __post_init__(self) -> None:
        DomainId(self.production_id)
        package = tuple(sorted(self.package, key=lambda item: item.path))
        paths = [item.path for item in package]
        if not package:
            raise ValueError("release package cannot be empty")
        if len(paths) != len(set(paths)):
            raise ValueError("duplicate release package path")
        if self.final_output not in {item.blob for item in package}:
            raise ValueError("release package must contain the exact final output")
        if self.license_bundle not in {item.blob for item in package}:
            raise ValueError("release package must contain the exact license bundle")
        if len(self.execution_key) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.execution_key
        ):
            raise ValueError("invalid release execution key")
        revisions = tuple(
            sorted(
                set(self.asset_revisions),
                key=lambda item: (item.sha256, item.size),
            )
        )
        object.__setattr__(self, "package", package)
        object.__setattr__(self, "asset_revisions", revisions)

    def as_payload(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "timeline": self.timeline.as_payload(),
            "check_policy": self.check_policy.as_payload(),
            "execution": self.execution.as_payload(),
            "render_options": self.render_options.as_payload(),
            "execution_key": self.execution_key,
            "final_output": self.final_output.as_payload(),
            "check_report": self.check_report.as_payload(),
            "review_verdict": self.review_verdict.as_payload(),
            "constraints": self.constraints.as_payload(),
            "asset_revisions": [
                item.as_payload() for item in self.asset_revisions
            ],
            "license_bundle": self.license_bundle.as_payload(),
            "package": [item.as_payload() for item in self.package],
        }

    @property
    def candidate_id(self) -> str:
        return canonical_hash(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @property
    def ref(self) -> BlobRef:
        raw = self.canonical_bytes()
        return BlobRef(self.candidate_id, len(raw))

    @property
    def reachable_blobs(self) -> tuple[BlobRef, ...]:
        refs = {
            self.timeline,
            self.check_policy,
            self.execution,
            self.render_options,
            self.final_output,
            self.check_report,
            self.review_verdict,
            self.constraints,
            self.license_bundle,
            *self.asset_revisions,
            *(item.blob for item in self.package),
        }
        return tuple(sorted(refs, key=lambda item: (item.sha256, item.size)))

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "ReleaseCandidate":
        wrapped = json.loads(raw)
        if (
            wrapped.get("$domain") != cls.DOMAIN
            or wrapped.get("$version") != cls.VERSION
        ):
            raise ValueError("invalid release candidate schema")
        value = wrapped["payload"]
        result = cls(
            production_id=str(value["production_id"]),
            timeline=BlobRef.from_payload(value["timeline"]),
            check_policy=BlobRef.from_payload(value["check_policy"]),
            execution=BlobRef.from_payload(value["execution"]),
            render_options=BlobRef.from_payload(value["render_options"]),
            execution_key=str(value["execution_key"]),
            final_output=BlobRef.from_payload(value["final_output"]),
            check_report=BlobRef.from_payload(value["check_report"]),
            review_verdict=BlobRef.from_payload(value["review_verdict"]),
            constraints=BlobRef.from_payload(value["constraints"]),
            asset_revisions=tuple(
                BlobRef.from_payload(item) for item in value["asset_revisions"]
            ),
            license_bundle=BlobRef.from_payload(value["license_bundle"]),
            package=tuple(
                PackageFile(
                    str(item["path"]), BlobRef.from_payload(item["blob"])
                )
                for item in value["package"]
            ),
        )
        if result.canonical_bytes() != raw:
            raise ValueError("release candidate is not canonical")
        return result


@dataclass(frozen=True, slots=True)
class DeliveryReceipt:
    candidate_id: str
    destination_id: str
    delivered_at: str
    manifest: tuple[PackageFile, ...]

    DOMAIN = "dlstudio.delivery_receipt"
    VERSION = 1

    def __post_init__(self) -> None:
        if len(self.candidate_id) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.candidate_id
        ):
            raise ValueError("invalid delivered candidate id")
        DomainId(self.destination_id)
        if not self.delivered_at.strip():
            raise ValueError("delivery timestamp is required")
        manifest = tuple(sorted(self.manifest, key=lambda item: item.path))
        if not manifest or len({item.path for item in manifest}) != len(manifest):
            raise ValueError("delivery manifest must be complete and unique")
        object.__setattr__(self, "manifest", manifest)

    def as_payload(self) -> dict[str, Any]:
        return {
            "candidate_id": self.candidate_id,
            "destination_id": self.destination_id,
            "delivered_at": self.delivered_at,
            "manifest": [item.as_payload() for item in self.manifest],
        }

    @property
    def receipt_id(self) -> str:
        return canonical_hash(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @property
    def ref(self) -> BlobRef:
        raw = self.canonical_bytes()
        return BlobRef(self.receipt_id, len(raw))

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "DeliveryReceipt":
        wrapped = json.loads(raw)
        if (
            wrapped.get("$domain") != cls.DOMAIN
            or wrapped.get("$version") != cls.VERSION
        ):
            raise ValueError("invalid delivery receipt schema")
        value = wrapped["payload"]
        result = cls(
            candidate_id=str(value["candidate_id"]),
            destination_id=str(value["destination_id"]),
            delivered_at=str(value["delivered_at"]),
            manifest=tuple(
                PackageFile(
                    str(item["path"]), BlobRef.from_payload(item["blob"])
                )
                for item in value["manifest"]
            ),
        )
        if result.canonical_bytes() != raw:
            raise ValueError("delivery receipt is not canonical")
        return result
