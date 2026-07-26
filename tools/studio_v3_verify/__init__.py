"""Studio v3 verification harness.

This package intentionally lives under ``tools/``.  Runtime modules must never
import it; CI and local verification invoke it as ``python -m
tools.studio_v3_verify``.
"""

from .gates import GateResult, GateStatus

__all__ = ["GateResult", "GateStatus"]

