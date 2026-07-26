"""Small explicit v3 DSL; no compatibility constructors."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dlstudio.assets.api import AssetRevision
from dlstudio.foundation.api import DomainId


@dataclass(frozen=True, slots=True)
class MediaGeometry:
    """Resolved source-to-output transform captured at compile time."""

    source_width: int
    source_height: int
    scaled_width: int
    scaled_height: int
    crop_x: int | None = None
    crop_y: int | None = None
    pad_x: int | None = None
    pad_y: int | None = None


@dataclass(frozen=True, slots=True)
class Animation:
    """Visual-property keyframe resolved onto the absolute edit timeline."""

    prop: Literal["scale", "x", "y", "opacity", "rotate"]
    start_milli: int
    end_milli: int
    ease: Literal["linear", "in", "out", "in_out", "back_out"]
    start_ns: int
    end_ns: int


@dataclass(frozen=True, slots=True)
class SolidLayer:
    start_ns: int
    duration_ns: int
    z: int
    x: int
    y: int
    width: int
    height: int
    color: str
    opacity_milli: int = 1000


@dataclass(frozen=True, slots=True)
class MediaLayer:
    asset_id: str
    start_ns: int
    duration_ns: int
    z: int
    x: int
    y: int
    width: int
    height: int
    fit: Literal["contain", "cover", "stretch"] = "contain"
    opacity_milli: int = 1000
    source_start_ns: int = 0
    loop: bool = False
    freeze_at_end: bool = False
    ken_burns: bool = False
    transition: Literal[
        "cut", "fade", "dip_black", "slide_left", "slide_right"
    ] = "cut"
    transition_ns: int = 0
    fade_out_ns: int = 0
    geometry: MediaGeometry | None = None
    animations: tuple[Animation, ...] = ()
    transition_intent: Literal[
        "continuous_same_take",
        "motivated_cut",
        "before_after",
        "chapter_boundary",
        "no_cut",
    ] | None = None


@dataclass(frozen=True, slots=True)
class TextLayer:
    text: str
    font_asset_id: str
    start_ns: int
    duration_ns: int
    z: int
    x: int
    y: int
    width: int
    height: int
    font_size: int
    color: str = "white"
    opacity_milli: int = 1000
    role: Literal["overlay", "caption"] = "overlay"
    transition: Literal[
        "cut", "fade"
    ] = "cut"
    transition_ns: int = 0


@dataclass(frozen=True, slots=True)
class AudioClip:
    asset_id: str
    start_ns: int
    duration_ns: int
    source_start_ns: int = 0
    gain_db_milli: int = 0
    fade_in_ns: int = 0
    fade_out_ns: int = 0
    role: Literal["voice", "music", "sfx", "ambient"] = "voice"
    duck: bool = False
    loop: bool = False


@dataclass(frozen=True, slots=True)
class VideoFade:
    direction: Literal["in", "out"]
    start_ns: int
    duration_ns: int
    color: str = "black"


@dataclass(frozen=True, slots=True)
class Edit:
    production_id: str
    width: int
    height: int
    fps_num: int
    fps_den: int
    duration_ns: int
    background: str
    assets: tuple[AssetRevision, ...] = ()
    visuals: tuple[SolidLayer | MediaLayer | TextLayer, ...] = ()
    audio: tuple[AudioClip, ...] = ()
    video_fades: tuple[VideoFade, ...] = ()
    standalone_story: str = ""
    kind: Literal["reel", "devlog", "capture_vo"] = "reel"
    target_lufs_milli: int = -14_000
    true_peak_db_milli: int = -1_000
    duck_amount_db_milli: int = -12_000
    duck_threshold_db_milli: int = -30_000
    duck_attack_ms: int = 120
    duck_release_ms: int = 400

    def __post_init__(self) -> None:
        DomainId(self.production_id)
        object.__setattr__(self, "assets", tuple(self.assets))
        object.__setattr__(self, "visuals", tuple(self.visuals))
        object.__setattr__(self, "audio", tuple(self.audio))
        object.__setattr__(self, "video_fades", tuple(self.video_fades))
        if not self.standalone_story:
            raise ValueError("v3 edit requires standalone_story")
