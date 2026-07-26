"""Hash-bound requests/receipts for externally recorded capture."""

from __future__ import annotations

from dataclasses import dataclass

from dlstudio.assets.api import Provenance
from dlstudio.foundation.api import DomainId, canonical_hash


@dataclass(frozen=True, slots=True)
class CaptureRequest:
    production_id: str
    asset_id: str
    editorial_role: str
    capture_method: str
    state_id: str
    build_id: str
    width: int
    height: int
    minimum_head_ns: int
    minimum_tail_ns: int

    def __post_init__(self) -> None:
        DomainId(self.production_id)
        DomainId(self.asset_id)
        if self.capture_method not in {
            "realtime_window",
            "deterministic_devapi",
        }:
            raise ValueError("unsupported capture method")
        if self.editorial_role == "gameplay" and (
            self.capture_method != "realtime_window"
        ):
            raise ValueError("gameplay requires realtime_window capture")
        if min(
            self.width,
            self.height,
            self.minimum_head_ns,
            self.minimum_tail_ns,
        ) <= 0:
            raise ValueError("capture geometry and handles must be positive")

    @property
    def request_id(self) -> str:
        return canonical_hash(
            {
                "production_id": self.production_id,
                "asset_id": self.asset_id,
                "editorial_role": self.editorial_role,
                "capture_method": self.capture_method,
                "state_id": self.state_id,
                "build_id": self.build_id,
                "width": self.width,
                "height": self.height,
                "minimum_head_ns": self.minimum_head_ns,
                "minimum_tail_ns": self.minimum_tail_ns,
            },
            domain="dlstudio.capture_request",
        )


@dataclass(frozen=True, slots=True)
class CaptureReceipt:
    request_id: str
    capture_method: str
    state_id: str
    build_id: str
    width: int
    height: int
    head_ns: int
    tail_ns: int
    audit_sha256: str

    def provenance_for(self, request: CaptureRequest) -> Provenance:
        if self.request_id != request.request_id:
            raise ValueError("capture receipt does not match request")
        if (
            self.capture_method != request.capture_method
            or self.state_id != request.state_id
            or self.build_id != request.build_id
            or self.width != request.width
            or self.height != request.height
        ):
            raise ValueError("capture receipt facts differ from request")
        if (
            self.head_ns < request.minimum_head_ns
            or self.tail_ns < request.minimum_tail_ns
        ):
            raise ValueError("capture receipt lacks required edit handles")
        return Provenance(
            origin="recorded",
            capture_method=self.capture_method,
            state_id=self.state_id,
            build_id=self.build_id,
            native_width=self.width,
            native_height=self.height,
            provider_receipt_sha256=self.audit_sha256,
        )
