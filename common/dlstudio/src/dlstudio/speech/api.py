"""Voice-take provenance that binds recorded bytes to exact script text."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from typing import Any, Mapping

from dlstudio.assets.api import Provenance
from dlstudio.foundation.api import BlobRef, canonical_bytes


@dataclass(frozen=True, slots=True)
class VoiceRecorderReceipt:
    """Canonical browser-recorder facts kept beside every raw voice take."""

    recorded_at: str
    duration_ms: int
    mime_type: str
    recorder: str = "media_recorder"

    DOMAIN = "dlstudio.voice_recorder_receipt"
    VERSION = 1

    def __post_init__(self) -> None:
        if not self.recorded_at.strip():
            raise ValueError("voice recorder receipt requires recorded_at")
        if self.duration_ms <= 0:
            raise ValueError("voice recorder duration must be positive")
        if not self.mime_type.startswith("audio/"):
            raise ValueError("voice recorder receipt requires audio MIME type")
        if self.recorder != "media_recorder":
            raise ValueError("unsupported voice recorder")

    def as_payload(self) -> dict[str, object]:
        return {
            "recorded_at": self.recorded_at,
            "duration_ms": self.duration_ms,
            "mime_type": self.mime_type,
            "recorder": self.recorder,
        }

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "VoiceRecorderReceipt":
        wrapped: Mapping[str, Any] = json.loads(raw)
        if (
            wrapped.get("$domain") != cls.DOMAIN
            or wrapped.get("$version") != cls.VERSION
        ):
            raise ValueError("invalid voice recorder receipt schema")
        receipt = cls(**dict(wrapped["payload"]))
        if receipt.canonical_bytes() != raw:
            raise ValueError("voice recorder receipt is not canonically encoded")
        return receipt


@dataclass(frozen=True, slots=True)
class SpeechTakeReceipt:
    script_text: str
    script_ref: BlobRef
    take_id: str
    recorder_receipt_ref: BlobRef

    @property
    def script_bytes(self) -> bytes:
        return canonical_bytes(
            {"text": self.script_text}, domain="dlstudio.voice_script"
        )

    def __post_init__(self) -> None:
        if not self.script_text.strip() or not self.take_id:
            raise ValueError("voice take requires script text and take id")
        expected = BlobRef(
            hashlib.sha256(self.script_bytes).hexdigest(),
            len(self.script_bytes),
        )
        if self.script_ref != expected:
            raise ValueError("script evidence does not match exact script text")

    def provenance(self) -> Provenance:
        return Provenance(
            origin="recorded",
            capture_method="voice_take",
            state_id=self.take_id,
            script_ref=self.script_ref,
            provider_receipt_ref=self.recorder_receipt_ref,
        )
