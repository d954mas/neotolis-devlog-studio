"""Dependency-free primitives shared by Studio v3 domains.

This module deliberately contains no filesystem, process, or domain imports.
Semantic identities are hashes of a schema/domain-separated canonical payload;
host paths and timestamps belong in operation metadata, never in those payloads.
"""

from __future__ import annotations

import dataclasses
import hashlib
import json
import math
import re
import unicodedata
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from enum import Enum
from pathlib import PurePosixPath
from types import MappingProxyType
from typing import Any, Generic, TypeVar


class StudioError(Exception):
    """Base class for expected Studio v3 failures."""


class CanonicalEncodingError(StudioError):
    """A payload cannot participate in a semantic identity."""


class CasConflict(StudioError):
    """The production head changed since a caller read it."""


class CorruptObject(StudioError):
    """Stored bytes do not match their immutable reference."""


_SCHEMA_RE = re.compile(r"^[a-z][a-z0-9]*(?:[._-][a-z0-9]+)*$")
_DOMAIN_ID_RE = re.compile(r"^[a-z0-9]+(?:[._-][a-z0-9]+)*$")
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
T = TypeVar("T")


@dataclass(frozen=True, slots=True)
class BlobRef:
    """Exact identity of immutable bytes in an object store."""

    sha256: str
    size: int

    def __post_init__(self) -> None:
        if _SHA256_RE.fullmatch(self.sha256) is None:
            raise ValueError("invalid blob sha256")
        if self.size < 0:
            raise ValueError("negative blob size")

    def as_payload(self) -> dict[str, object]:
        return {"sha256": self.sha256, "size": self.size}

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "BlobRef":
        return cls(sha256=str(value["sha256"]), size=int(value["size"]))


@dataclass(frozen=True, slots=True)
class DomainId(Generic[T]):
    """Validated semantic identifier; the type parameter is a static marker."""

    value: str

    def __post_init__(self) -> None:
        normalized = unicodedata.normalize("NFC", self.value)
        if normalized != self.value or not _DOMAIN_ID_RE.fullmatch(normalized):
            raise ValueError(f"invalid domain id: {self.value!r}")

    def __str__(self) -> str:
        return self.value


@dataclass(frozen=True, slots=True)
class SchemaEnvelope:
    schema: str
    version: int
    payload: Mapping[str, Any]

    def __post_init__(self) -> None:
        if not _SCHEMA_RE.fullmatch(self.schema):
            raise ValueError(f"invalid schema name: {self.schema!r}")
        if self.version < 1:
            raise ValueError("schema version must be positive")
        object.__setattr__(self, "payload", _freeze_mapping(self.payload))

    def as_payload(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "version": self.version,
            "payload": dict(self.payload),
        }


def normalize_logical_path(value: str) -> str:
    """Return a portable relative path and reject host-specific bindings."""

    text = unicodedata.normalize("NFC", value.replace("\\", "/"))
    if not text or text.startswith("/") or re.match(r"^[A-Za-z]:", text):
        raise CanonicalEncodingError(f"logical path must be relative: {value!r}")
    path = PurePosixPath(text)
    if any(part in {"", ".", ".."} for part in path.parts):
        raise CanonicalEncodingError(f"unsafe logical path: {value!r}")
    return path.as_posix()


def _freeze_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        return _freeze_mapping(value)
    if isinstance(value, Sequence) and not isinstance(
        value, (str, bytes, bytearray)
    ):
        return tuple(_freeze_value(item) for item in value)
    return value


def _freeze_mapping(value: Mapping[str, Any]) -> Mapping[str, Any]:
    return MappingProxyType(
        {key: _freeze_value(item) for key, item in value.items()}
    )


def _canonicalize(value: Any) -> Any:
    if isinstance(value, DomainId):
        return value.value
    if dataclasses.is_dataclass(value):
        value = {
            field.name: getattr(value, field.name)
            for field in dataclasses.fields(value)
        }
    if isinstance(value, Enum):
        value = value.value
    if value is None or isinstance(value, (bool, int)):
        return value
    if isinstance(value, float):
        if not math.isfinite(value):
            raise CanonicalEncodingError("non-finite floats are forbidden")
        # JSON's shortest round-trippable representation is stable in Python
        # 3.12, the only supported v3 runtime.
        return 0.0 if value == 0 else value
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    if isinstance(value, Mapping):
        result: dict[str, Any] = {}
        for raw_key, raw_value in value.items():
            if not isinstance(raw_key, str):
                raise CanonicalEncodingError("canonical object keys must be strings")
            key = unicodedata.normalize("NFC", raw_key)
            if key in result:
                raise CanonicalEncodingError(f"duplicate normalized key: {key!r}")
            result[key] = _canonicalize(raw_value)
        return result
    if isinstance(value, Sequence) and not isinstance(value, (bytes, bytearray)):
        return [_canonicalize(item) for item in value]
    raise CanonicalEncodingError(
        f"unsupported canonical value: {type(value).__name__}"
    )


def canonical_bytes(
    payload: Any,
    *,
    domain: str,
    version: int = 1,
) -> bytes:
    """Encode semantic data with an explicit domain and schema version."""

    if not _SCHEMA_RE.fullmatch(domain):
        raise CanonicalEncodingError(f"invalid canonical domain: {domain!r}")
    if version < 1:
        raise CanonicalEncodingError("canonical version must be positive")
    wrapped = {
        "$domain": domain,
        "$version": version,
        "payload": _canonicalize(payload),
    }
    return json.dumps(
        wrapped,
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_hash(
    payload: Any,
    *,
    domain: str,
    version: int = 1,
) -> str:
    return hashlib.sha256(
        canonical_bytes(payload, domain=domain, version=version)
    ).hexdigest()
