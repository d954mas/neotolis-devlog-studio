"""Small immutable production-constraint contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping

from dlstudio.assets.api import BlobRef
from dlstudio.foundation.api import DomainId, canonical_bytes, canonical_hash


@dataclass(frozen=True, slots=True)
class Constraint:
    constraint_id: str
    text: str
    level: Literal["blocker", "required", "preference"] = "required"

    def __post_init__(self) -> None:
        DomainId(self.constraint_id)
        if not self.text.strip():
            raise ValueError("constraint text is required")
        if self.level not in {"blocker", "required", "preference"}:
            raise ValueError("unsupported constraint level")

    def as_payload(self) -> dict[str, str]:
        return {
            "constraint_id": self.constraint_id,
            "text": self.text,
            "level": self.level,
        }


@dataclass(frozen=True, slots=True)
class ConstraintSet:
    production_id: str
    source: str
    constraints: tuple[Constraint, ...]
    supersedes: BlobRef | None = None

    DOMAIN = "dlstudio.constraint_set"
    VERSION = 1

    def __post_init__(self) -> None:
        DomainId(self.production_id)
        if not self.source.strip():
            raise ValueError("constraint source is required")
        ordered = tuple(
            sorted(self.constraints, key=lambda item: item.constraint_id)
        )
        identifiers = [item.constraint_id for item in ordered]
        if len(identifiers) != len(set(identifiers)):
            raise ValueError("duplicate constraint id")
        object.__setattr__(self, "constraints", ordered)

    def as_payload(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "source": self.source,
            "supersedes": (
                None if self.supersedes is None else self.supersedes.as_payload()
            ),
            "constraints": [item.as_payload() for item in self.constraints],
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

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "ConstraintSet":
        wrapped: Mapping[str, Any] = json.loads(raw)
        if (
            wrapped.get("$domain") != cls.DOMAIN
            or wrapped.get("$version") != cls.VERSION
        ):
            raise ValueError("invalid constraint set schema")
        payload = wrapped["payload"]
        supersedes = payload["supersedes"]
        result = cls(
            production_id=str(payload["production_id"]),
            source=str(payload["source"]),
            constraints=tuple(
                Constraint(
                    constraint_id=str(item["constraint_id"]),
                    text=str(item["text"]),
                    level=item["level"],
                )
                for item in payload["constraints"]
            ),
            supersedes=(
                None
                if supersedes is None
                else BlobRef.from_payload(supersedes)
            ),
        )
        if result.canonical_bytes() != raw:
            raise ValueError("constraint set is not canonical")
        return result
