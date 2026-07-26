"""Small immutable production-constraint contract."""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal, Mapping

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
class ConstraintSetRef:
    production_id: str
    sha256: str

    def __post_init__(self) -> None:
        DomainId(self.production_id)
        if len(self.sha256) != 64 or any(
            character not in "0123456789abcdef" for character in self.sha256
        ):
            raise ValueError("invalid constraint set hash")

    def as_payload(self) -> dict[str, str]:
        return {
            "production_id": self.production_id,
            "sha256": self.sha256,
        }


@dataclass(frozen=True, slots=True)
class ConstraintSet:
    production_id: str
    source: str
    constraints: tuple[Constraint, ...]
    supersedes: ConstraintSetRef | None = None

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
        if (
            self.supersedes is not None
            and self.supersedes.production_id != self.production_id
        ):
            raise ValueError("superseded constraints belong to another production")
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
    def ref(self) -> ConstraintSetRef:
        return ConstraintSetRef(
            self.production_id,
            canonical_hash(
                self.as_payload(), domain=self.DOMAIN, version=self.VERSION
            ),
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
                else ConstraintSetRef(
                    str(supersedes["production_id"]),
                    str(supersedes["sha256"]),
                )
            ),
        )
        if result.canonical_bytes() != raw:
            raise ValueError("constraint set is not canonical")
        return result
