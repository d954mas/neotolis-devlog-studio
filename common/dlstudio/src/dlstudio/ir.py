"""Timeline IR — the boundary between model and backend.

compile() resolves the DSL into this: absolute times, explicit z-ordered
overlay items, merged scene segments, probed asset facts, and the mix
resolved onto the edit timeline. Properties the whole system relies on:

- JSON-serializable (pydantic) -> cacheable, diffable, dumpable (`dl2 ir`).
- check/ gates and reviewer agents consume the IR + probe facts as ground
  truth (kills the hallucinated-offset failure class at the source).
- render/ consumes ONLY the IR (+ Design for raster styling). Nothing in
  render re-derives timing from words.

CONTRACT FREEZE: existing fields must not be renamed or retyped by
implementing agents; adding new optional fields is allowed.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .model.content import Anim, Transition
from .model.design import Design
from .model.edit import Duck


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class WordSpan(_Model):
    """One transcript word with absolute beat-relative times (seconds)."""

    t0: float
    t1: float
    text: str


class AssetProbe(_Model):
    """ffprobe facts for one referenced asset. duration/width/height are
    None for kinds where they don't apply or when probing was skipped."""

    path: str
    kind: Literal["image", "video", "audio", "font", "other"]
    exists: bool
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    has_audio: bool | None = None


class IRAnim(_Model):
    """Anim with `t` resolved to beat-relative absolute seconds."""

    prop: str
    start: float
    end: float
    ease: str
    t0: float
    t1: float


class IROverlayItem(_Model):
    """One raster overlay (rendered chunk visual) on the beat timeline.
    The PNG itself is produced at render time by render.raster; the IR
    carries the chunk reference and placement."""

    chunk_index: int
    z: int
    t0: float
    t1: float
    anims: list[IRAnim] = Field(default_factory=list)
    transition_in: Transition | None = None


class IRSegment(_Model):
    """One background segment (post same-source merge) on the beat timeline.
    `xfade` is the transition to the NEXT segment, if any."""

    kind: Literal["image", "video"]
    src: str
    offset: float
    t0: float
    t1: float
    ken_burns: bool = False
    loop: bool = False
    fit: Literal["cover", "contain"] = "cover"
    xfade: Transition | None = None


class IRSfx(_Model):
    src: str
    t: float                # beat-relative seconds (resolved from word anchor)
    gain_db: float = 0.0


class IRBeat(_Model):
    id: str
    duration: float         # authoritative: VO audio duration
    audio: str              # processed VO wav path
    words_path: str
    words: list[WordSpan]
    segments: list[IRSegment]
    overlays: list[IROverlayItem]
    face: Literal["full", "pip", "none"] = "none"
    sfx: list[IRSfx] = Field(default_factory=list)
    transition_out: Transition | None = None


class BeatPlacement(_Model):
    """Absolute position of a beat on the edit timeline."""

    beat_id: str
    t0: float


class IRMusicSpan(_Model):
    """Music region resolved to absolute edit-timeline seconds."""

    src: str
    t0: float
    t1: float
    offset: float = 0.0
    gain_db: float = -18.0
    fade_in: float = 1.0
    fade_out: float = 1.5
    duck: bool = True


class IRMix(_Model):
    music: list[IRMusicSpan] = Field(default_factory=list)
    duck: Duck = Field(default_factory=Duck)
    target_lufs: float = -14.0
    true_peak_db: float = -1.0


class CheckIssue(_Model):
    severity: Literal["error", "warn"]
    code: str               # VQ-* code, e.g. "VQ-SYNC", "VQ-ASSET"
    message: str
    where: str = ""         # "beat:chunk" or path, best-effort locator


class CheckReport(_Model):
    issues: list[CheckIssue] = Field(default_factory=list)

    @property
    def errors(self) -> list[CheckIssue]:
        return [i for i in self.issues if i.severity == "error"]

    @property
    def ok(self) -> bool:
        return not self.errors


class Timeline(_Model):
    """The compiled edit. Root object of the IR."""

    edit_name: str
    design: Design
    beats: list[IRBeat]                      # in concat order
    placements: list[BeatPlacement]
    mix: IRMix
    assets: dict[str, AssetProbe]            # path -> probe facts
    output: str
    warnings: list[str] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        if not self.beats:
            return 0.0
        last = self.placements[-1]
        return last.t0 + self.beats[-1].duration
