"""Voice-take provenance that binds recorded bytes to exact script text."""

from __future__ import annotations

from dataclasses import dataclass

from dlstudio.assets.api import Provenance
from dlstudio.foundation.api import canonical_hash


@dataclass(frozen=True, slots=True)
class SpeechTakeReceipt:
    script_text: str
    take_id: str
    recorder_receipt_sha256: str

    @property
    def script_sha256(self) -> str:
        return canonical_hash(
            {"text": self.script_text},
            domain="dlstudio.voice_script",
        )

    def provenance(self) -> Provenance:
        if not self.script_text.strip() or not self.take_id:
            raise ValueError("voice take requires script text and take id")
        return Provenance(
            origin="recorded",
            capture_method="voice_take",
            state_id=self.take_id,
            script_sha256=self.script_sha256,
            provider_receipt_sha256=self.recorder_receipt_sha256,
        )
