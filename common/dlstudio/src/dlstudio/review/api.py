"""Immutable review verdict bound to exact artifact bytes."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from dlstudio.foundation.api import (
    BlobRef,
    DomainId,
    canonical_bytes,
    canonical_hash,
)

REVIEW_PACK_MAX_ITEMS = 12
REVIEW_PACK_MAX_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ReviewRegion:
    """Normalized 0..1000 rectangle inside the reviewed frame."""

    x_milli: int
    y_milli: int
    width_milli: int
    height_milli: int

    def __post_init__(self) -> None:
        if min(
            self.x_milli,
            self.y_milli,
            self.width_milli,
            self.height_milli,
        ) < 0:
            raise ValueError("review region cannot be negative")
        if self.width_milli == 0 or self.height_milli == 0:
            raise ValueError("review region must have positive area")
        if (
            self.x_milli + self.width_milli > 1000
            or self.y_milli + self.height_milli > 1000
        ):
            raise ValueError("review region exceeds the frame")

    def as_payload(self) -> dict[str, int]:
        return {
            "x_milli": self.x_milli,
            "y_milli": self.y_milli,
            "width_milli": self.width_milli,
            "height_milli": self.height_milli,
        }

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> "ReviewRegion":
        return cls(
            x_milli=int(value["x_milli"]),
            y_milli=int(value["y_milli"]),
            width_milli=int(value["width_milli"]),
            height_milli=int(value["height_milli"]),
        )


@dataclass(frozen=True, slots=True)
class ReviewLocator:
    """Frame-accurate location plus optional spatial and timeline targets."""

    start_frame: int
    end_frame_exclusive: int
    region: ReviewRegion | None = None
    target_ids: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        if (
            self.start_frame < 0
            or self.end_frame_exclusive <= self.start_frame
        ):
            raise ValueError("review frame range is invalid")
        targets = tuple(sorted(set(self.target_ids)))
        for target_id in targets:
            DomainId(target_id)
        object.__setattr__(self, "target_ids", targets)

    @property
    def is_frame(self) -> bool:
        return self.end_frame_exclusive == self.start_frame + 1

    def as_payload(self) -> dict[str, Any]:
        return {
            "start_frame": self.start_frame,
            "end_frame_exclusive": self.end_frame_exclusive,
            "region": (
                None if self.region is None else self.region.as_payload()
            ),
            "target_ids": list(self.target_ids),
        }

    @classmethod
    def from_payload(cls, value: dict[str, Any]) -> "ReviewLocator":
        region = value.get("region")
        return cls(
            start_frame=int(value["start_frame"]),
            end_frame_exclusive=int(value["end_frame_exclusive"]),
            region=(
                None
                if region is None
                else ReviewRegion.from_payload(region)
            ),
            target_ids=tuple(str(item) for item in value.get("target_ids", ())),
        )


def build_review_pack(
    artifact: BlobRef,
    evidence: tuple[BlobRef, ...],
) -> bytes:
    """Build a deterministic compact evidence manifest with hard size caps."""

    selected: list[BlobRef] = []
    total = 0
    for ref in sorted(set(evidence), key=lambda item: (item.sha256, item.size)):
        if len(selected) == REVIEW_PACK_MAX_ITEMS:
            break
        if total + ref.size > REVIEW_PACK_MAX_BYTES:
            continue
        selected.append(ref)
        total += ref.size
    return canonical_bytes(
        {
            "artifact": artifact.as_payload(),
            "evidence": [ref.as_payload() for ref in selected],
            "evidence_bytes": total,
        },
        domain="dlstudio.review_pack",
        version=1,
    )


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    finding_id: str
    text: str
    requires_change: bool = False
    locator: ReviewLocator | None = None

    def __post_init__(self) -> None:
        DomainId(self.finding_id)
        if not self.text.strip():
            raise ValueError("review finding text is required")

    def as_payload(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "text": self.text,
            "requires_change": self.requires_change,
            "locator": (
                None if self.locator is None else self.locator.as_payload()
            ),
        }


@dataclass(frozen=True, slots=True)
class ReviewVerdict:
    artifact: BlobRef
    outcome: Literal["pass", "changes_requested", "block"]
    check_report: BlobRef
    constraints: BlobRef
    scope: tuple[str, ...]
    reviewer: str
    reviewed_at: str
    findings: tuple[ReviewFinding, ...] = ()
    review_pack: BlobRef | None = None
    evidence: tuple[BlobRef, ...] = ()

    DOMAIN = "dlstudio.review_verdict"
    VERSION = 3

    def __post_init__(self) -> None:
        DomainId(self.reviewer)
        scope = tuple(sorted(set(self.scope)))
        if not scope:
            raise ValueError("review scope is required")
        for item in scope:
            DomainId(item)
        if self.artifact.size <= 0:
            raise ValueError("reviewed artifact must be non-empty")
        if not self.reviewed_at.strip():
            raise ValueError("review timestamp is required")
        findings = tuple(sorted(self.findings, key=lambda item: item.finding_id))
        identifiers = [item.finding_id for item in findings]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate review finding")
        evidence = tuple(
            sorted(set(self.evidence), key=lambda item: (item.sha256, item.size))
        )
        if self.outcome not in {"pass", "changes_requested", "block"}:
            raise ValueError("unsupported review outcome")
        required = any(item.requires_change for item in findings)
        if self.outcome == "pass" and required:
            raise ValueError("passing review cannot require changes")
        if self.outcome == "changes_requested" and not required:
            raise ValueError("changes_requested needs a required finding")
        object.__setattr__(self, "findings", findings)
        object.__setattr__(self, "evidence", evidence)
        object.__setattr__(self, "scope", scope)

    def as_payload(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact.as_payload(),
            "outcome": self.outcome,
            "check_report": self.check_report.as_payload(),
            "constraints": self.constraints.as_payload(),
            "scope": list(self.scope),
            "reviewer": self.reviewer,
            "reviewed_at": self.reviewed_at,
            "findings": [item.as_payload() for item in self.findings],
            "review_pack": (
                None if self.review_pack is None else self.review_pack.as_payload()
            ),
            "evidence": [item.as_payload() for item in self.evidence],
        }

    @property
    def ref(self) -> BlobRef:
        raw = self.canonical_bytes()
        return BlobRef(
            canonical_hash(
                self.as_payload(), domain=self.DOMAIN, version=self.VERSION
            ),
            len(raw),
        )

    @property
    def reachable_blobs(self) -> tuple[BlobRef, ...]:
        return (
            self.artifact,
            self.check_report,
            self.constraints,
            *((self.review_pack,) if self.review_pack is not None else ()),
            *self.evidence,
        )

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    def require_artifact(self, artifact: BlobRef) -> None:
        if artifact != self.artifact:
            raise ValueError("review verdict is stale for this artifact")

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "ReviewVerdict":
        wrapped = json.loads(raw)
        if (
            wrapped.get("$domain") != cls.DOMAIN
            or wrapped.get("$version") != cls.VERSION
        ):
            raise ValueError("invalid review verdict schema")
        payload = wrapped["payload"]
        result = cls(
            artifact=BlobRef.from_payload(payload["artifact"]),
            outcome=payload["outcome"],
            check_report=BlobRef.from_payload(payload["check_report"]),
            constraints=BlobRef.from_payload(payload["constraints"]),
            scope=tuple(str(item) for item in payload["scope"]),
            reviewer=str(payload["reviewer"]),
            reviewed_at=str(payload["reviewed_at"]),
            findings=tuple(
                ReviewFinding(
                    str(item["finding_id"]),
                    str(item["text"]),
                    bool(item["requires_change"]),
                    (
                        None
                        if item["locator"] is None
                        else ReviewLocator.from_payload(item["locator"])
                    ),
                )
                for item in payload["findings"]
            ),
            review_pack=(
                None
                if payload["review_pack"] is None
                else BlobRef.from_payload(payload["review_pack"])
            ),
            evidence=tuple(
                BlobRef.from_payload(item) for item in payload["evidence"]
            ),
        )
        if result.canonical_bytes() != raw:
            raise ValueError("review verdict is not canonical")
        return result
