"""render — the ONLY backend: FFmpeg.

OWNER: render-agent (graph.py, beat.py, assemble.py, this file).
render/raster/ is owned separately by the raster-agent.

- graph.py     typed filter-graph builder (AST: nodes/pads/labels), no
               string templating. Every v1 trap (setpts PTS-shift,
               eof_action=pass, EOF clamps) is an encoded invariant.
- beat.py      one ffmpeg subprocess per beat -> beat MP4 + VO stem wav.
- assemble.py  edit-level pass: concat + beat transitions + music beds
               across beat boundaries + sidechain ducking + SFX + final
               loudness normalization. Phase 1 ships concat + duration
               postcondition; the full mix graph lands in Phase 2.

RenderOpts quality presets mirror v1 (draft/preview/upload/master, CPU +
NVENC variants — port from legacy compose_ffmpeg._codec_args).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dlstudio.ir import IRBeat, Timeline
from dlstudio.model import Design


@dataclass(frozen=True)
class RenderOpts:
    width: int | None = None          # None = design resolution
    quality: str = "standard"         # draft | preview | standard | upload | master
    gpu: bool = False
    workdir: Path = Path("data/finalize")


def render_beat(beat: IRBeat, design: Design, timeline: Timeline, opts: RenderOpts) -> Path:
    """Render one beat to MP4 (+ sibling VO stem wav). Returns MP4 path.
    MUST call check.verify_output() before returning."""
    raise NotImplementedError("render-agent implements this")


def assemble(timeline: Timeline, beat_files: dict[str, Path], opts: RenderOpts) -> Path:
    """Assemble rendered beats into the final output (timeline.output).
    MUST call check.verify_output() before returning."""
    raise NotImplementedError("render-agent implements this")
