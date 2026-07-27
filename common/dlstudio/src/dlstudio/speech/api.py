"""Voice-take provenance that binds recorded bytes to exact script text."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass

from dlstudio.assets.api import Provenance
from dlstudio.foundation.api import BlobRef, canonical_bytes


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
