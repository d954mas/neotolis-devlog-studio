"""Compatibility-free local import convenience for timeline-owned checks."""

from .api import CheckFinding, CheckReport, check_timeline

__all__ = ["CheckFinding", "CheckReport", "check_timeline"]
