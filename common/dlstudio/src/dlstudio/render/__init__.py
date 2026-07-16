"""render — the ONLY backend: FFmpeg.

OWNER: render-agent (graph.py, beat.py, assemble.py, this file).
render/raster/ is owned separately by the raster-agent.

- graph.py     typed filter-graph builder (AST: nodes/pads/labels), no
               string templating. Every v1 trap (setpts PTS-shift,
               eof_action=pass, EOF clamps) is an encoded invariant.
- beat.py      one ffmpeg subprocess per beat -> beat MP4 + VO stem wav.
               render_beat(beat, design, _timeline, opts): the third
               positional param is ACCEPTED BUT IGNORED (a single beat
               render never needs the whole Timeline). Kept only so
               Phase-1 call sites that still pass a real Timeline
               positionally don't break; pass None. Do NOT ship the whole
               Timeline to render workers under -j N -- that was the actual
               bug (N workers each pickling all N beats == O(N^2) IPC); cli's
               _compose_worker/_render_targets carry no timeline argument at
               all for this reason.
- assemble.py  edit-level pass: concat + beat transitions + music beds
               across beat boundaries + sidechain ducking + SFX + final
               loudness normalization. Phase 2 ships the full mix graph: a
               fast stream-copy path when there's no music/SFX/transition, and
               otherwise a VO+music+SFX filter-graph mix (ducking keyed by the
               `*_vo_stem.wav` stems), two-pass loudnorm, and dip-to-black
               transitions re-encoded only at boundaries. `measure_loudness()`
               exposes a loudnorm measure pass for VQ-AUDIO checks/tests.

RenderOpts quality presets mirror v1 (draft/preview/upload/master, CPU +
NVENC variants — port from legacy compose_ffmpeg._codec_args).
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class RenderOpts:
    width: int | None = None          # None = design resolution
    quality: str = "standard"         # draft | preview | standard | upload | master
    gpu: bool = False
    workdir: Path = Path("data/finalize")


# Implementations live in the submodules (re-exported here so the public
# render_beat/assemble/RenderOpts surface is stable). Imported AFTER RenderOpts
# is defined so the submodules can type-hint against it without a cycle.
from .beat import render_beat            # noqa: E402
from .assemble import assemble, measure_loudness  # noqa: E402

__all__ = ["RenderOpts", "render_beat", "assemble", "measure_loudness"]
