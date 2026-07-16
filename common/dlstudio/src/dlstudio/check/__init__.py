"""check — gates as code, run on the Timeline IR.

OWNER: compile-agent.

Every gate has a VQ code (see docs/ARCHITECTURE_V2.md). Baseline set:
- VQ-ASSET  missing/unreadable referenced assets (error)
- VQ-WORDS  word indices out of transcript range / overlapping chunks (error)
- VQ-SYNC   rendered output duration vs VO duration mismatch (error) —
            exposed as `verify_output()` for renderers to call as a
            POSTCONDITION (the v1 bug class that cost 22 blind iterations)
- VQ-RES    resolution sanity: absurd upscales / dims beyond encoder
            limits (the 3840x6826 x264 OOM class) (error)
- VQ-OFFSET scene offset at/past source EOF (warn, compile clamps)
"""
from __future__ import annotations

from dlstudio.ir import CheckReport, Timeline


def run_checks(timeline: Timeline) -> CheckReport:
    raise NotImplementedError("compile-agent implements this")


def verify_output(video_path: str, expected_duration: float, *, tolerance: float = 0.25) -> None:
    """ffprobe the rendered file; raise RuntimeError on duration mismatch.
    Called by render/assemble as a mandatory postcondition."""
    raise NotImplementedError("compile-agent implements this")
