"""Chunk-level DSL: content variants, decorations, animation, transitions.

Design rules (the v2 contract):
- Word indices into the beat's Whisper transcript are the master clock.
  A chunk's on-screen window is derived from `words=(start_idx, end_idx)`;
  compile resolves indices to absolute seconds.
- Composition over flags: what v1 expressed as 30+ booleans on one god
  dataclass is expressed here as a typed `content` variant plus an open
  `decorations` list. A new visual treatment is a new Decoration class,
  never a new field on Chunk.
- Brand styling lives in the project's style registry (Design.styles);
  content types reference styles by name ("plate.climax"). Engine code
  must not hardcode colors/sizes.
"""
from __future__ import annotations

from typing import Annotated, Literal, Union

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


Ease = Literal["linear", "in", "out", "in_out", "back_out"]


class Anim(_Model):
    """Keyframed property animation over a chunk's visible window.

    `t` is normalized (0..1) within the chunk window; compile resolves it
    to absolute seconds. Example — v1's plate punch-in, now expressible:
    Anim(prop="scale", start=1.04, end=1.0, ease="out", t=(0, 0.4)).
    """

    prop: Literal["scale", "x", "y", "opacity", "rotate"]
    start: float
    end: float
    ease: Ease = "out"
    t: tuple[float, float] = (0.0, 1.0)


class Transition(_Model):
    """Boundary transition. On a Chunk: transition INTO the chunk.
    On a Beat (`transition_out`): transition to the next beat, applied by
    assemble. kind="cut" means a deliberate hard cut."""

    kind: Literal["cut", "fade", "dip_black", "slide_left", "slide_right"] = "fade"
    dur: float = 0.3


# ─── Decorations (open, composable; discriminated union) ───────────────────

class Underline(_Model):
    type: Literal["underline"] = "underline"
    color: str = "accent"          # palette token
    width_ratio: float = 0.25      # of frame width


class Badge(_Model):
    """Named branded badge, e.g. "trophy", "silver". Look is defined by the
    project style registry / raster renderer, not by the engine."""

    type: Literal["badge"] = "badge"
    name: str


class FramedCard(_Model):
    type: Literal["framed_card"] = "framed_card"
    pad_ratio: float = 0.04


class Vignette(_Model):
    type: Literal["vignette"] = "vignette"
    strength: float = 0.5


class Label(_Model):
    type: Literal["label"] = "label"
    text: str
    variant: str = "branded"


class CaptionPill(_Model):
    type: Literal["caption"] = "caption"
    text: str


Decoration = Annotated[
    Union[Underline, Badge, FramedCard, Vignette, Label, CaptionPill],
    Field(discriminator="type"),
]


# ─── Content variants (exactly one per chunk; discriminated union) ─────────

class Plate(_Model):
    """Full-screen centered text."""

    type: Literal["plate"] = "plate"
    text: str
    style: str = "plate.default"       # key into Design.styles
    size: int | None = None            # explicit override of style size
    bg_image: str | None = None
    bg_opacity: float | None = None
    line_gap_ratio: float | None = None


class Overlay(_Model):
    """Text band/card/hero over a scene."""

    type: Literal["overlay"] = "overlay"
    text: str
    subtitle: str | None = None
    variant: Literal["band", "card", "hero"] = "band"
    position: Literal["bottom", "top", "middle"] = "bottom"
    style: str = "overlay.default"
    sub_ratio: float | None = None
    subtitle_color: str | None = None  # palette token
    # Center of the band as a fraction of frame height; None = legacy
    # position-based placement (bottom/top/middle).
    y_ratio: float | None = Field(default=None, ge=0.0, le=1.0)


class ImageShot(_Model):
    """Full-bleed image as the chunk's own visual."""

    type: Literal["image"] = "image"
    src: str
    asset_id: str | None = None
    editorial_role: Literal[
        "gameplay",
        "debug_proof",
        "presentation",
        "reference",
    ] | None = None
    fit: Literal["cover", "contain"] = "cover"
    anchor_x: float = Field(default=0.5, ge=0.0, le=1.0)
    anchor_y: float = Field(default=0.5, ge=0.0, le=1.0)
    ken_burns: bool = False


class VideoShot(_Model):
    """Video segment as the chunk's own visual."""

    type: Literal["video"] = "video"
    src: str
    asset_id: str | None = None
    render_manifest: str | None = None
    editorial_role: Literal[
        "gameplay",
        "debug_proof",
        "presentation",
        "reference",
    ] | None = None
    expected_state_id: str | None = None
    expected_build_id: str | None = None
    expected_action_id: str | None = None
    offset: float = 0.0
    fit: Literal["cover", "contain"] = "cover"
    anchor_x: float = Field(default=0.5, ge=0.0, le=1.0)
    anchor_y: float = Field(default=0.5, ge=0.0, le=1.0)


Content = Annotated[
    Union[Plate, Overlay, ImageShot, VideoShot],
    Field(discriminator="type"),
]


class Scene(_Model):
    """Background behind overlay/plate chunks. Beat-level scene is inherited
    by chunks without their own. Consecutive chunks sharing the same scene
    `src` merge into one continuous segment (v1 semantics preserved:
    first chunk's offset wins, later offsets are ignored)."""

    kind: Literal["image", "video"]
    src: str
    asset_id: str | None = None
    render_manifest: str | None = None
    editorial_role: Literal[
        "gameplay",
        "debug_proof",
        "presentation",
        "reference",
    ] | None = None
    expected_state_id: str | None = None
    expected_build_id: str | None = None
    expected_action_id: str | None = None
    offset: float = 0.0
    ken_burns: bool = False
    loop: bool = False
    fit: Literal["cover", "contain"] = "cover"
    anchor_x: float = Field(default=0.5, ge=0.0, le=1.0)
    anchor_y: float = Field(default=0.5, ge=0.0, le=1.0)


class Chunk(_Model):
    words: tuple[int, int]
    content: Content
    scene: Scene | None = None
    decorations: list[Decoration] = Field(default_factory=list)
    anims: list[Anim] = Field(default_factory=list)
    transition: Transition | None = None
    transition_intent: Literal[
        "continuous_same_take",
        "motivated_cut",
        "before_after",
        "chapter_boundary",
        "no_cut",
    ] | None = None
    pad_before: float = 0.0
    pad_after: float = 0.0
