"""Deterministic FFmpeg render kernel for Studio v3."""

from .api import (
    ExecutionFingerprint,
    PresentationCacheLimits,
    PresentationFileResult,
    PresentationWaveformResult,
    RenderOptions,
    RenderResult,
    extract_presentation_frame,
    extract_presentation_waveform,
    render,
)

__all__ = [
    "ExecutionFingerprint",
    "PresentationCacheLimits",
    "PresentationFileResult",
    "PresentationWaveformResult",
    "RenderOptions",
    "RenderResult",
    "extract_presentation_frame",
    "extract_presentation_waveform",
    "render",
]
