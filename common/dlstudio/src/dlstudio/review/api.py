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


@dataclass(frozen=True, slots=True)
class ReviewFinding:
    finding_id: str
    text: str
    requires_change: bool = False

    def __post_init__(self) -> None:
        DomainId(self.finding_id)
        if not self.text.strip():
            raise ValueError("review finding text is required")

    def as_payload(self) -> dict[str, object]:
        return {
            "finding_id": self.finding_id,
            "text": self.text,
            "requires_change": self.requires_change,
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
    VERSION = 2

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
