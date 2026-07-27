"""Small explicit v3 DSL; no compatibility constructors."""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from typing import Literal

from dlstudio.assets.api import AssetRevision
from dlstudio.foundation.api import DomainId
from dlstudio.timeline.api import (
    AnimationInstruction,
    AssetSnapshot,
    AudioInstruction,
    MediaGeometry,
    TimelineIR,
    VideoFadeInstruction,
    VisualInstruction,
)


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
        object.__setattr__(self, "visuals", tuple(self.visuals))
        object.__setattr__(self, "audio", tuple(self.audio))
        object.__setattr__(self, "video_fades", tuple(self.video_fades))
        if not self.standalone_story:
            raise ValueError("v3 edit requires standalone_story")


def _compile_resolved(
    edit: Edit, assets: Iterable[AssetRevision] = ()
) -> TimelineIR:
    supplied = tuple(assets)
    revisions = {revision.asset_id: revision for revision in supplied}
    if len(revisions) != len(supplied):
        raise ValueError("edit contains duplicate asset ids")
    visuals: list[VisualInstruction] = []
    used_asset_ids: set[str] = set()
    for layer in edit.visuals:
        common = {
            "start_ns": layer.start_ns,
            "duration_ns": layer.duration_ns,
            "z": layer.z,
            "x": layer.x,
            "y": layer.y,
            "width": layer.width,
            "height": layer.height,
            "opacity_milli": layer.opacity_milli,
        }
        if isinstance(layer, SolidLayer):
            visuals.append(
                VisualInstruction(kind="solid", color=layer.color, **common)
            )
        elif isinstance(layer, MediaLayer):
            revision = revisions.get(layer.asset_id)
            if revision is None:
                raise ValueError(f"unknown media asset: {layer.asset_id}")
            used_asset_ids.add(layer.asset_id)
            visuals.append(
                VisualInstruction(
                    kind="media",
                    asset=revision.ref,
                    fit=layer.fit,
                    source_start_ns=layer.source_start_ns,
                    loop=layer.loop,
                    freeze_at_end=layer.freeze_at_end,
                    ken_burns=layer.ken_burns,
                    transition=layer.transition,
                    transition_ns=layer.transition_ns,
                    fade_out_ns=layer.fade_out_ns,
                    geometry=(
                        None
                        if layer.geometry is None
                        else layer.geometry
                    ),
                    animations=tuple(
                        AnimationInstruction(
                            prop=animation.prop,
                            start_milli=animation.start_milli,
                            end_milli=animation.end_milli,
                            ease=animation.ease,
                            start_ns=animation.start_ns,
                            end_ns=animation.end_ns,
                        )
                        for animation in layer.animations
                    ),
                    transition_intent=layer.transition_intent,
                    **common,
                )
            )
        elif isinstance(layer, TextLayer):
            revision = revisions.get(layer.font_asset_id)
            if revision is None or revision.media.kind != "font":
                raise ValueError(f"unknown font asset: {layer.font_asset_id}")
            used_asset_ids.add(layer.font_asset_id)
            visuals.append(
                VisualInstruction(
                    kind="text",
                    text=layer.text,
                    font_asset=revision.ref,
                    font_size=layer.font_size,
                    color=layer.color,
                    role=layer.role,
                    transition=layer.transition,
                    transition_ns=layer.transition_ns,
                    **common,
                )
            )
        else:  # pragma: no cover - closed union.
            raise TypeError(type(layer).__name__)
    audio: list[AudioInstruction] = []
    for clip in edit.audio:
        revision = revisions.get(clip.asset_id)
        if revision is None or revision.media.kind not in {"audio", "video"}:
            raise ValueError(f"unknown audio asset: {clip.asset_id}")
        used_asset_ids.add(clip.asset_id)
        audio.append(
            AudioInstruction(
                revision.ref,
                clip.start_ns,
                clip.duration_ns,
                clip.source_start_ns,
                clip.gain_db_milli,
                clip.fade_in_ns,
                clip.fade_out_ns,
                clip.role,
                clip.duck,
                clip.loop,
            )
        )
    return TimelineIR(
        production_id=edit.production_id,
        width=edit.width,
        height=edit.height,
        fps_num=edit.fps_num,
        fps_den=edit.fps_den,
        duration_ns=edit.duration_ns,
        background=edit.background,
        assets=tuple(
            AssetSnapshot.from_revision(revisions[asset_id])
            for asset_id in sorted(used_asset_ids)
        ),
        visuals=tuple(visuals),
        audio=tuple(audio),
        video_fades=tuple(
            VideoFadeInstruction(
                direction=fade.direction,
                start_ns=fade.start_ns,
                duration_ns=fade.duration_ns,
                color=fade.color,
            )
            for fade in edit.video_fades
        ),
        target_lufs_milli=edit.target_lufs_milli,
        true_peak_db_milli=edit.true_peak_db_milli,
        duck_amount_db_milli=edit.duck_amount_db_milli,
        duck_threshold_db_milli=edit.duck_threshold_db_milli,
        duck_attack_ms=edit.duck_attack_ms,
        duck_release_ms=edit.duck_release_ms,
        metadata={
            "kind": edit.kind,
            "standalone_story": edit.standalone_story,
        },
    )
