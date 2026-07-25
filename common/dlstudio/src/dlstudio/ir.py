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

import math
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
    None for kinds where they don't apply or when probing was skipped.
    `readable` distinguishes present-but-broken files from healthy ones:
    None = not determined, False = exists but ffprobe failed on it."""

    path: str
    kind: Literal["image", "video", "audio", "font", "other"]
    exists: bool
    duration: float | None = None
    width: int | None = None
    height: int | None = None
    has_audio: bool | None = None
    readable: bool | None = None


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
    carries the chunk reference and placement.

    `content_hash` is a stable digest of the SOURCE Chunk (model_dump_json)
    stamped by compile. It exists so the beat cache key — which hashes the
    IRBeat — changes whenever rasterized content (text, style, decorations,
    bg) changes, even though the Chunk itself travels to the rasterizer
    out-of-band via the chunk resolver. `asset_paths` lists file paths the
    raster pass reads (e.g. Plate.bg_image) so the cache can include their
    identity (size+mtime)."""

    chunk_index: int
    z: int
    t0: float
    t1: float
    anims: list[IRAnim] = Field(default_factory=list)
    transition_in: Transition | None = None
    content_hash: str | None = None
    asset_paths: list[str] = Field(default_factory=list)


class IRSegmentGeometry(_Model):
    """Resolved source-to-output transform.

    All coordinates are integer pixels.  A compiled segment therefore carries
    enough information for checks and reviewers to reproduce the exact crop or
    pad without relying on FFmpeg's implicit centering defaults.
    """

    fit: Literal["cover", "contain"]
    anchor_x: float = Field(ge=0.0, le=1.0)
    anchor_y: float = Field(ge=0.0, le=1.0)
    source_width: int | None = None
    source_height: int | None = None
    scaled_width: int | None = None
    scaled_height: int | None = None
    output_width: int
    output_height: int
    crop_x: int | None = None
    crop_y: int | None = None
    crop_width: int | None = None
    crop_height: int | None = None
    pad_x: int | None = None
    pad_y: int | None = None

    @staticmethod
    def _even_ceil(value: float) -> int:
        rounded = int(math.ceil(value - 1e-9))
        return rounded if rounded % 2 == 0 else rounded + 1

    @classmethod
    def resolve(
        cls,
        *,
        fit: Literal["cover", "contain"],
        anchor_x: float,
        anchor_y: float,
        source_width: int | None,
        source_height: int | None,
        output_width: int,
        output_height: int,
    ) -> "IRSegmentGeometry":
        base = {
            "fit": fit,
            "anchor_x": anchor_x,
            "anchor_y": anchor_y,
            "source_width": source_width,
            "source_height": source_height,
            "output_width": output_width,
            "output_height": output_height,
        }
        if not source_width or not source_height:
            return cls(**base)

        if fit == "cover":
            scale = max(
                output_width / source_width,
                output_height / source_height,
            )
            scaled_width = cls._even_ceil(source_width * scale)
            scaled_height = cls._even_ceil(source_height * scale)
            excess_x = max(0, scaled_width - output_width)
            excess_y = max(0, scaled_height - output_height)
            crop_x = min(excess_x, max(0, int(round(excess_x * anchor_x))))
            crop_y = min(excess_y, max(0, int(round(excess_y * anchor_y))))
            return cls(
                **base,
                scaled_width=scaled_width,
                scaled_height=scaled_height,
                crop_x=crop_x,
                crop_y=crop_y,
                crop_width=output_width,
                crop_height=output_height,
            )

        scale = min(
            output_width / source_width,
            output_height / source_height,
        )
        scaled_width = min(
            output_width,
            max(2, cls._even_ceil(source_width * scale)),
        )
        scaled_height = min(
            output_height,
            max(2, cls._even_ceil(source_height * scale)),
        )
        free_x = max(0, output_width - scaled_width)
        free_y = max(0, output_height - scaled_height)
        pad_x = min(free_x, max(0, int(round(free_x * anchor_x))))
        pad_y = min(free_y, max(0, int(round(free_y * anchor_y))))
        return cls(
            **base,
            scaled_width=scaled_width,
            scaled_height=scaled_height,
            pad_x=pad_x,
            pad_y=pad_y,
        )

    def for_output(self, width: int, height: int) -> "IRSegmentGeometry":
        return self.resolve(
            fit=self.fit,
            anchor_x=self.anchor_x,
            anchor_y=self.anchor_y,
            source_width=self.source_width,
            source_height=self.source_height,
            output_width=width,
            output_height=height,
        )


class IRSegment(_Model):
    """One background segment (post same-source merge) on the beat timeline.
    `xfade` is the transition to the NEXT segment, if any."""

    kind: Literal["image", "video"]
    src: str
    asset_id: str | None = None
    editorial_role: Literal[
        "gameplay",
        "debug_proof",
        "presentation",
        "reference",
    ] | None = None
    expected_state_id: str | None = None
    expected_build_id: str | None = None
    expected_action_id: str | None = None
    offset: float
    t0: float
    t1: float
    ken_burns: bool = False
    loop: bool = False
    fit: Literal["cover", "contain"] = "cover"
    geometry: IRSegmentGeometry | None = None
    transition_intent: Literal[
        "continuous_same_take",
        "motivated_cut",
        "before_after",
        "chapter_boundary",
        "no_cut",
    ] | None = None
    xfade: Transition | None = None


class IRSfx(_Model):
    src: str
    t: float                # beat-relative seconds (resolved from word anchor)
    gain_db: float = 0.0


class IRCaption(_Model):
    """One phrase-level subtitle window (compiled from `beat.words` when the
    beat sets `subtitles=True`). Rendered by render.beat as a full-frame
    raster overlay above all chunk overlays; styling comes from
    `Design.captions`. Text rides in the IR so the beat cache key changes
    whenever the transcript (and thus the captions) changes."""

    text: str
    t0: float               # beat-relative seconds
    t1: float


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
    captions: list[IRCaption] = Field(default_factory=list)


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
    asset_policy: Literal["compatibility", "production"] = "compatibility"
    warnings: list[str] = Field(default_factory=list)
    # Structured compile-time diagnostics. Preferred over string-tagged
    # warnings: compile appends CheckIssue objects here and check merges
    # them without regex parsing. `warnings` stays for human display.
    diagnostics: list[CheckIssue] = Field(default_factory=list)

    @property
    def duration(self) -> float:
        if not self.beats:
            return 0.0
        last = self.placements[-1]
        return last.t0 + self.beats[-1].duration
