"""Replayable, versioned TimelineIR with no DSL or runtime callbacks."""

from __future__ import annotations

import json
from collections.abc import Mapping
from dataclasses import dataclass, field
from types import MappingProxyType
from typing import Any, Literal

from dlstudio.assets.api import (
    Approval,
    AssetRevision,
    AssetRevisionRef,
    License,
    MediaFacts,
    Provenance,
)
from dlstudio.foundation.api import (
    BlobRef,
    CorruptObject,
    DomainId,
    canonical_bytes,
    canonical_hash,
)


@dataclass(frozen=True, slots=True)
class MediaGeometry:
    """Exact resolved raster transform; no implicit renderer centering."""

    source_width: int
    source_height: int
    scaled_width: int
    scaled_height: int
    crop_x: int | None = None
    crop_y: int | None = None
    pad_x: int | None = None
    pad_y: int | None = None

    def __post_init__(self) -> None:
        if min(
            self.source_width,
            self.source_height,
            self.scaled_width,
            self.scaled_height,
        ) <= 0:
            raise ValueError("media geometry dimensions must be positive")
        if any(
            value is not None and value < 0
            for value in (self.crop_x, self.crop_y, self.pad_x, self.pad_y)
        ):
            raise ValueError("media geometry offsets must be non-negative")
        if (self.crop_x is None) != (self.crop_y is None):
            raise ValueError("crop geometry must provide both axes")
        if (self.pad_x is None) != (self.pad_y is None):
            raise ValueError("pad geometry must provide both axes")
        if self.crop_x is not None and self.pad_x is not None:
            raise ValueError("media geometry cannot crop and pad")

    def as_payload(self) -> dict[str, int | None]:
        return {
            "source_width": self.source_width,
            "source_height": self.source_height,
            "scaled_width": self.scaled_width,
            "scaled_height": self.scaled_height,
            "crop_x": self.crop_x,
            "crop_y": self.crop_y,
            "pad_x": self.pad_x,
            "pad_y": self.pad_y,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "MediaGeometry":
        optional = lambda name: (
            None if value.get(name) is None else int(value[name])
        )
        return cls(
            source_width=int(value["source_width"]),
            source_height=int(value["source_height"]),
            scaled_width=int(value["scaled_width"]),
            scaled_height=int(value["scaled_height"]),
            crop_x=optional("crop_x"),
            crop_y=optional("crop_y"),
            pad_x=optional("pad_x"),
            pad_y=optional("pad_y"),
        )


@dataclass(frozen=True, slots=True)
class AnimationInstruction:
    """One resolved, replayable visual-property animation."""

    prop: Literal["scale", "x", "y", "opacity", "rotate"]
    start_milli: int
    end_milli: int
    ease: Literal["linear", "in", "out", "in_out", "back_out"]
    start_ns: int
    end_ns: int

    def __post_init__(self) -> None:
        if self.prop not in {"scale", "x", "y", "opacity", "rotate"}:
            raise ValueError("unsupported animation property")
        if self.ease not in {"linear", "in", "out", "in_out", "back_out"}:
            raise ValueError("unsupported animation easing")
        if self.start_ns < 0 or self.end_ns <= self.start_ns:
            raise ValueError("animation timing is invalid")
        if self.prop == "scale" and min(self.start_milli, self.end_milli) <= 0:
            raise ValueError("animation scale must stay positive")
        if self.prop == "opacity" and not (
            0 <= self.start_milli <= 1000 and 0 <= self.end_milli <= 1000
        ):
            raise ValueError("animation opacity must be 0..1000")

    def as_payload(self) -> dict[str, Any]:
        return {
            "prop": self.prop,
            "start_milli": self.start_milli,
            "end_milli": self.end_milli,
            "ease": self.ease,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "AnimationInstruction":
        return cls(
            prop=value["prop"],
            start_milli=int(value["start_milli"]),
            end_milli=int(value["end_milli"]),
            ease=value["ease"],
            start_ns=int(value["start_ns"]),
            end_ns=int(value["end_ns"]),
        )


@dataclass(frozen=True, slots=True)
class AssetSnapshot:
    """A complete hash-verifiable asset revision embedded in replayable IR."""

    revision: AssetRevision

    @property
    def ref(self) -> AssetRevisionRef:
        return self.revision.ref

    @property
    def blob(self) -> BlobRef:
        return self.revision.blob

    @property
    def media(self) -> MediaFacts:
        return self.revision.media

    @classmethod
    def from_revision(cls, revision: AssetRevision) -> "AssetSnapshot":
        return cls(revision)

    def as_payload(self) -> dict[str, Any]:
        return {"revision": self.revision.as_payload()}

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "AssetSnapshot":
        revision = value["revision"]
        return cls(
            AssetRevision(
                asset_id=str(revision["asset_id"]),
                blob=BlobRef.from_payload(revision["blob"]),
                media=MediaFacts.from_payload(revision["media"]),
                provenance=Provenance.from_payload(revision["provenance"]),
                approval=Approval.from_payload(revision["approval"]),
                license=License.from_payload(revision["license"]),
            )
        )


@dataclass(frozen=True, slots=True)
class VisualInstruction:
    kind: Literal["solid", "media", "text"]
    start_ns: int
    duration_ns: int
    z: int
    x: int
    y: int
    width: int
    height: int
    color: str | None = None
    asset: AssetRevisionRef | None = None
    text: str | None = None
    font_asset: AssetRevisionRef | None = None
    font_size: int | None = None
    opacity_milli: int = 1000
    fit: Literal["contain", "cover", "stretch"] = "contain"
    source_start_ns: int = 0
    loop: bool = False
    freeze_at_end: bool = False
    ken_burns: bool = False
    role: Literal["overlay", "caption"] = "overlay"
    transition: Literal[
        "cut", "fade", "dip_black", "slide_left", "slide_right"
    ] = "cut"
    transition_ns: int = 0
    fade_out_ns: int = 0
    geometry: MediaGeometry | None = None
    animations: tuple[AnimationInstruction, ...] = ()
    transition_intent: Literal[
        "continuous_same_take",
        "motivated_cut",
        "before_after",
        "chapter_boundary",
        "no_cut",
    ] | None = None

    def __post_init__(self) -> None:
        if self.kind not in {"solid", "media", "text"}:
            raise ValueError("unsupported visual kind")
        if self.fit not in {"contain", "cover", "stretch"}:
            raise ValueError("unsupported visual fit")
        if self.role not in {"overlay", "caption"}:
            raise ValueError("unsupported visual role")
        if self.transition not in {
            "cut",
            "fade",
            "dip_black",
            "slide_left",
            "slide_right",
        }:
            raise ValueError("unsupported visual transition")
        if min(self.start_ns, self.source_start_ns) < 0 or self.duration_ns <= 0:
            raise ValueError("visual timing must be positive")
        if min(self.width, self.height) <= 0:
            raise ValueError("visual geometry must be positive")
        if not 0 <= self.opacity_milli <= 1000:
            raise ValueError("opacity_milli must be 0..1000")
        if self.transition_ns < 0 or self.transition_ns > self.duration_ns:
            raise ValueError("transition duration is outside visual")
        if self.transition == "cut" and self.transition_ns != 0:
            raise ValueError("cut transition cannot have duration")
        if self.kind == "solid" and self.transition != "cut":
            raise ValueError("solid instructions do not support transitions")
        if self.kind == "text" and self.transition not in {"cut", "fade"}:
            raise ValueError("text instructions support only cut/fade")
        if self.fade_out_ns < 0 or self.fade_out_ns > self.duration_ns:
            raise ValueError("fade-out duration is outside visual")
        if self.transition_intent not in {
            None,
            "continuous_same_take",
            "motivated_cut",
            "before_after",
            "chapter_boundary",
            "no_cut",
        }:
            raise ValueError("unsupported transition intent")
        if self.geometry is not None and self.kind != "media":
            raise ValueError("resolved media geometry requires media")
        object.__setattr__(self, "animations", tuple(self.animations))
        if self.animations and (self.kind != "media" or self.z <= 0):
            raise ValueError("animations require a non-base media layer")
        seen_animation_props: set[str] = set()
        for animation in self.animations:
            if animation.prop in seen_animation_props:
                raise ValueError("visual has duplicate animation property")
            seen_animation_props.add(animation.prop)
            if (
                animation.start_ns < self.start_ns
                or animation.end_ns > self.end_ns
            ):
                raise ValueError("animation exceeds visual timing")
        if self.kind == "solid":
            if self.color is None or self.asset is not None or self.text is not None:
                raise ValueError("solid instruction requires only color")
        elif self.kind == "media":
            if self.asset is None or self.text is not None:
                raise ValueError("media instruction requires exact asset")
        elif self.kind == "text":
            if (
                not self.text
                or self.font_asset is None
                or self.font_size is None
                or self.font_size <= 0
                or self.color is None
            ):
                raise ValueError("text requires text/font/size/color")
        else:
            raise ValueError("unsupported visual instruction")

    @property
    def end_ns(self) -> int:
        return self.start_ns + self.duration_ns

    def as_payload(self) -> dict[str, Any]:
        return {
            "kind": self.kind,
            "start_ns": self.start_ns,
            "duration_ns": self.duration_ns,
            "z": self.z,
            "x": self.x,
            "y": self.y,
            "width": self.width,
            "height": self.height,
            "color": self.color,
            "asset": None if self.asset is None else self.asset.as_payload(),
            "text": self.text,
            "font_asset": (
                None if self.font_asset is None else self.font_asset.as_payload()
            ),
            "font_size": self.font_size,
            "opacity_milli": self.opacity_milli,
            "fit": self.fit,
            "source_start_ns": self.source_start_ns,
            "loop": self.loop,
            "freeze_at_end": self.freeze_at_end,
            "ken_burns": self.ken_burns,
            "role": self.role,
            "transition": self.transition,
            "transition_ns": self.transition_ns,
            "fade_out_ns": self.fade_out_ns,
            "geometry": (
                None if self.geometry is None else self.geometry.as_payload()
            ),
            "animations": [
                animation.as_payload() for animation in self.animations
            ],
            "transition_intent": self.transition_intent,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "VisualInstruction":
        def ref(name: str) -> AssetRevisionRef | None:
            raw = value.get(name)
            if raw is None:
                return None
            return AssetRevisionRef(str(raw["asset_id"]), str(raw["revision_hash"]))

        return cls(
            kind=value["kind"],
            start_ns=int(value["start_ns"]),
            duration_ns=int(value["duration_ns"]),
            z=int(value["z"]),
            x=int(value["x"]),
            y=int(value["y"]),
            width=int(value["width"]),
            height=int(value["height"]),
            color=value.get("color"),
            asset=ref("asset"),
            text=value.get("text"),
            font_asset=ref("font_asset"),
            font_size=(
                None if value.get("font_size") is None else int(value["font_size"])
            ),
            opacity_milli=int(value.get("opacity_milli", 1000)),
            fit=value.get("fit", "contain"),
            source_start_ns=int(value.get("source_start_ns", 0)),
            loop=bool(value.get("loop", False)),
            freeze_at_end=bool(value.get("freeze_at_end", False)),
            ken_burns=bool(value.get("ken_burns", False)),
            role=value.get("role", "overlay"),
            transition=value.get("transition", "cut"),
            transition_ns=int(value.get("transition_ns", 0)),
            fade_out_ns=int(value.get("fade_out_ns", 0)),
            geometry=(
                None
                if value.get("geometry") is None
                else MediaGeometry.from_payload(value["geometry"])
            ),
            animations=tuple(
                AnimationInstruction.from_payload(item)
                for item in value.get("animations", ())
            ),
            transition_intent=value.get("transition_intent"),
        )


@dataclass(frozen=True, slots=True)
class AudioInstruction:
    asset: AssetRevisionRef
    start_ns: int
    duration_ns: int
    source_start_ns: int = 0
    gain_db_milli: int = 0
    fade_in_ns: int = 0
    fade_out_ns: int = 0
    role: Literal["voice", "music", "sfx", "ambient"] = "voice"
    duck: bool = False
    loop: bool = False

    def __post_init__(self) -> None:
        if self.role not in {"voice", "music", "sfx", "ambient"}:
            raise ValueError("unsupported audio role")
        if (
            min(
                self.start_ns,
                self.source_start_ns,
                self.fade_in_ns,
                self.fade_out_ns,
            )
            < 0
            or self.duration_ns <= 0
        ):
            raise ValueError("audio timing is invalid")
        if self.fade_in_ns + self.fade_out_ns > self.duration_ns:
            raise ValueError("audio fades exceed clip duration")
        if not -96_000 <= self.gain_db_milli <= 24_000:
            raise ValueError("audio gain is outside -96..24 dB")

    @property
    def end_ns(self) -> int:
        return self.start_ns + self.duration_ns

    def as_payload(self) -> dict[str, Any]:
        return {
            "asset": self.asset.as_payload(),
            "start_ns": self.start_ns,
            "duration_ns": self.duration_ns,
            "source_start_ns": self.source_start_ns,
            "gain_db_milli": self.gain_db_milli,
            "fade_in_ns": self.fade_in_ns,
            "fade_out_ns": self.fade_out_ns,
            "role": self.role,
            "duck": self.duck,
            "loop": self.loop,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "AudioInstruction":
        asset = value["asset"]
        return cls(
            asset=AssetRevisionRef(
                str(asset["asset_id"]), str(asset["revision_hash"])
            ),
            start_ns=int(value["start_ns"]),
            duration_ns=int(value["duration_ns"]),
            source_start_ns=int(value.get("source_start_ns", 0)),
            gain_db_milli=int(value.get("gain_db_milli", 0)),
            fade_in_ns=int(value.get("fade_in_ns", 0)),
            fade_out_ns=int(value.get("fade_out_ns", 0)),
            role=value.get("role", "voice"),
            duck=bool(value.get("duck", False)),
            loop=bool(value.get("loop", False)),
        )


@dataclass(frozen=True, slots=True)
class VideoFadeInstruction:
    """Non-overlapping fade of the fully composited video track."""

    direction: Literal["in", "out"]
    start_ns: int
    duration_ns: int
    color: str = "black"

    def __post_init__(self) -> None:
        if self.direction not in {"in", "out"}:
            raise ValueError("unsupported video fade direction")
        if self.start_ns < 0 or self.duration_ns <= 0:
            raise ValueError("video fade timing is invalid")

    @property
    def end_ns(self) -> int:
        return self.start_ns + self.duration_ns

    def as_payload(self) -> dict[str, Any]:
        return {
            "direction": self.direction,
            "start_ns": self.start_ns,
            "duration_ns": self.duration_ns,
            "color": self.color,
        }

    @classmethod
    def from_payload(cls, value: Mapping[str, Any]) -> "VideoFadeInstruction":
        return cls(
            direction=value["direction"],
            start_ns=int(value["start_ns"]),
            duration_ns=int(value["duration_ns"]),
            color=str(value.get("color", "black")),
        )


@dataclass(frozen=True, slots=True)
class TimelineIR:
    production_id: str
    width: int
    height: int
    fps_num: int
    fps_den: int
    duration_ns: int
    background: str
    assets: tuple[AssetSnapshot, ...] = ()
    visuals: tuple[VisualInstruction, ...] = ()
    audio: tuple[AudioInstruction, ...] = ()
    video_fades: tuple[VideoFadeInstruction, ...] = ()
    target_lufs_milli: int = -14_000
    true_peak_db_milli: int = -1_000
    duck_amount_db_milli: int = -12_000
    duck_threshold_db_milli: int = -30_000
    duck_attack_ms: int = 120
    duck_release_ms: int = 400
    metadata: Mapping[str, str] = field(default_factory=dict)

    DOMAIN = "dlstudio.timeline_ir"
    VERSION = 2

    def __post_init__(self) -> None:
        DomainId(self.production_id)
        if min(
            self.width,
            self.height,
            self.fps_num,
            self.fps_den,
            self.duration_ns,
        ) <= 0:
            raise ValueError("timeline canvas/timing must be positive")
        object.__setattr__(
            self,
            "assets",
            tuple(
                sorted(
                    self.assets,
                    key=lambda item: (
                        item.ref.asset_id,
                        item.ref.revision_hash,
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "visuals",
            tuple(
                sorted(
                    self.visuals,
                    key=lambda item: (item.z, item.start_ns, item.kind),
                )
            ),
        )
        object.__setattr__(
            self,
            "audio",
            tuple(
                sorted(
                    self.audio,
                    key=lambda item: (
                        item.start_ns,
                        item.asset.asset_id,
                        item.asset.revision_hash,
                    ),
                )
            ),
        )
        object.__setattr__(
            self,
            "video_fades",
            tuple(
                sorted(
                    self.video_fades,
                    key=lambda item: (item.start_ns, item.direction),
                )
            ),
        )
        object.__setattr__(self, "metadata", MappingProxyType(dict(self.metadata)))
        if not -70_000 <= self.target_lufs_milli <= -5_000:
            raise ValueError("target loudness is outside supported range")
        if not -9_000 <= self.true_peak_db_milli <= 0:
            raise ValueError("true peak is outside supported range")
        if min(self.duck_attack_ms, self.duck_release_ms) <= 0:
            raise ValueError("duck timing must be positive")
        snapshots = {snapshot.ref: snapshot for snapshot in self.assets}
        if len(snapshots) != len(self.assets):
            raise ValueError("duplicate asset snapshot")
        referenced = {
            ref
            for visual in self.visuals
            for ref in (visual.asset, visual.font_asset)
            if ref is not None
        } | {audio.asset for audio in self.audio}
        missing = referenced - snapshots.keys()
        if missing:
            raise ValueError(f"timeline references missing snapshots: {missing}")
        surplus = snapshots.keys() - referenced
        if surplus:
            raise ValueError(f"timeline contains unreachable snapshots: {surplus}")
        for visual in self.visuals:
            if visual.end_ns > self.duration_ns:
                raise ValueError("visual exceeds timeline duration")
            if (
                visual.x < 0
                or visual.y < 0
                or visual.x + visual.width > self.width
                or visual.y + visual.height > self.height
            ):
                raise ValueError("visual exceeds canvas")
            if visual.geometry is not None:
                geometry = visual.geometry
                assert visual.asset is not None
                snapshot = snapshots[visual.asset]
                if (
                    snapshot.media.width is not None
                    and snapshot.media.width != geometry.source_width
                ) or (
                    snapshot.media.height is not None
                    and snapshot.media.height != geometry.source_height
                ):
                    raise ValueError("resolved geometry source facts mismatch")
                if geometry.crop_x is not None and (
                    geometry.scaled_width < visual.width
                    or geometry.scaled_height < visual.height
                    or geometry.crop_x + visual.width > geometry.scaled_width
                    or geometry.crop_y + visual.height > geometry.scaled_height
                ):
                    raise ValueError("resolved crop is outside scaled media")
                if geometry.pad_x is not None and (
                    geometry.scaled_width > visual.width
                    or geometry.scaled_height > visual.height
                    or geometry.pad_x + geometry.scaled_width > visual.width
                    or geometry.pad_y + geometry.scaled_height > visual.height
                ):
                    raise ValueError("resolved pad is outside output media")
        special = {
            visual
            for visual in self.visuals
            if visual.transition in {"dip_black", "slide_left", "slide_right"}
        }
        if special:
            base_media = sorted(
                (
                    visual
                    for visual in self.visuals
                    if visual.kind == "media" and visual.z == 0
                ),
                key=lambda visual: visual.start_ns,
            )
            valid_base = bool(base_media) and base_media[0].start_ns == 0
            valid_base = valid_base and all(
                visual.x == 0
                and visual.y == 0
                and visual.width == self.width
                and visual.height == self.height
                and visual.opacity_milli == 1000
                and not visual.animations
                for visual in base_media
            )
            valid_base = valid_base and all(
                left.end_ns
                - (right.transition_ns if right.transition != "cut" else 0)
                == right.start_ns
                for left, right in zip(base_media, base_media[1:])
            )
            valid_base = valid_base and base_media[-1].end_ns == self.duration_ns
            valid_base = valid_base and special.issubset(set(base_media))
            if not valid_base:
                raise ValueError(
                    "special transitions require a contiguous full-canvas base track"
                )
        for item in self.audio:
            if item.end_ns > self.duration_ns:
                raise ValueError("audio exceeds timeline duration")
        for fade in self.video_fades:
            if fade.end_ns > self.duration_ns:
                raise ValueError("video fade exceeds timeline duration")

    def as_payload(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "width": self.width,
            "height": self.height,
            "fps_num": self.fps_num,
            "fps_den": self.fps_den,
            "duration_ns": self.duration_ns,
            "background": self.background,
            "assets": [
                value.as_payload()
                for value in sorted(
                    self.assets,
                    key=lambda item: (
                        item.ref.asset_id,
                        item.ref.revision_hash,
                    ),
                )
            ],
            "visuals": [
                value.as_payload()
                for value in sorted(
                    self.visuals,
                    key=lambda item: (item.z, item.start_ns, item.kind),
                )
            ],
            "audio": [
                value.as_payload()
                for value in sorted(
                    self.audio,
                    key=lambda item: (
                        item.start_ns,
                        item.asset.asset_id,
                        item.asset.revision_hash,
                    ),
                )
            ],
            "video_fades": [
                value.as_payload()
                for value in sorted(
                    self.video_fades,
                    key=lambda item: (item.start_ns, item.direction),
                )
            ],
            "mix": {
                "target_lufs_milli": self.target_lufs_milli,
                "true_peak_db_milli": self.true_peak_db_milli,
                "duck_amount_db_milli": self.duck_amount_db_milli,
                "duck_threshold_db_milli": self.duck_threshold_db_milli,
                "duck_attack_ms": self.duck_attack_ms,
                "duck_release_ms": self.duck_release_ms,
            },
            "metadata": dict(sorted(self.metadata.items())),
        }

    @property
    def timeline_id(self) -> str:
        return canonical_hash(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "TimelineIR":
        try:
            wrapped = json.loads(raw)
            if (
                wrapped.get("$domain") != cls.DOMAIN
                or wrapped.get("$version") != cls.VERSION
            ):
                raise ValueError("schema")
            value = wrapped["payload"]
            mix = value.get("mix", {})
            timeline = cls(
                production_id=str(value["production_id"]),
                width=int(value["width"]),
                height=int(value["height"]),
                fps_num=int(value["fps_num"]),
                fps_den=int(value["fps_den"]),
                duration_ns=int(value["duration_ns"]),
                background=str(value["background"]),
                assets=tuple(
                    AssetSnapshot.from_payload(item) for item in value["assets"]
                ),
                visuals=tuple(
                    VisualInstruction.from_payload(item)
                    for item in value["visuals"]
                ),
                audio=tuple(
                    AudioInstruction.from_payload(item) for item in value["audio"]
                ),
                video_fades=tuple(
                    VideoFadeInstruction.from_payload(item)
                    for item in value.get("video_fades", ())
                ),
                target_lufs_milli=int(
                    mix.get("target_lufs_milli", -14_000)
                ),
                true_peak_db_milli=int(
                    mix.get("true_peak_db_milli", -1_000)
                ),
                duck_amount_db_milli=int(
                    mix.get("duck_amount_db_milli", -12_000)
                ),
                duck_threshold_db_milli=int(
                    mix.get("duck_threshold_db_milli", -30_000)
                ),
                duck_attack_ms=int(mix.get("duck_attack_ms", 120)),
                duck_release_ms=int(mix.get("duck_release_ms", 400)),
                metadata=dict(value.get("metadata", {})),
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CorruptObject("invalid TimelineIR") from exc
        if timeline.canonical_bytes() != raw:
            raise CorruptObject("TimelineIR is not canonically encoded")
        return timeline


@dataclass(frozen=True, slots=True)
class CheckFinding:
    rule: str
    severity: Literal["warning", "error"]
    message: str


@dataclass(frozen=True, slots=True)
class CheckPolicy:
    """Explicit versioned inputs for deterministic, pure TimelineIR checks."""

    policy_id: str = "studio_v3.draft"
    ruleset_revision: str = "studio-v3-foundation"
    platform: Literal["generic", "vertical", "landscape"] = "generic"
    constraint_revision: str = "unconstrained"
    require_approved_assets: bool = False
    require_redistributable_assets: bool = False

    def __post_init__(self) -> None:
        DomainId(self.policy_id)
        if self.platform not in {"generic", "vertical", "landscape"}:
            raise ValueError("unsupported check platform")
        if not self.ruleset_revision or not self.constraint_revision:
            raise ValueError("check policy revisions are required")

    def as_payload(self) -> dict[str, Any]:
        return {
            "policy_id": self.policy_id,
            "ruleset_revision": self.ruleset_revision,
            "platform": self.platform,
            "constraint_revision": self.constraint_revision,
            "require_approved_assets": self.require_approved_assets,
            "require_redistributable_assets": self.require_redistributable_assets,
        }


@dataclass(frozen=True, slots=True)
class CheckReport:
    timeline_id: str
    policy_hash: str
    findings: tuple[CheckFinding, ...]

    @property
    def blocking(self) -> bool:
        return any(item.severity == "error" for item in self.findings)


def check_timeline(
    timeline: TimelineIR,
    policy: CheckPolicy = CheckPolicy(),
) -> CheckReport:
    findings: list[CheckFinding] = []
    if not timeline.visuals:
        findings.append(
            CheckFinding("VQ-MOTION", "warning", "timeline has no visuals")
        )
    snapshots = {snapshot.ref: snapshot for snapshot in timeline.assets}
    for snapshot in timeline.assets:
        if snapshot.media.kind == "video" and snapshot.media.duration_ns is None:
            findings.append(
                CheckFinding(
                    "VQ-ASSET",
                    "error",
                    f"video duration missing: {snapshot.ref.asset_id}",
                )
            )
        if snapshot.revision.approval.status == "rejected":
            findings.append(
                CheckFinding(
                    "VQ-ASSET",
                    "error",
                    f"rejected asset: {snapshot.ref.asset_id}",
                )
            )
        if (
            policy.require_approved_assets
            and snapshot.revision.approval.status != "approved"
        ):
            findings.append(
                CheckFinding(
                    "VQ-ASSET",
                    "error",
                    f"asset is not approved: {snapshot.ref.asset_id}",
                )
            )
        if (
            policy.require_redistributable_assets
            and not snapshot.revision.license.redistribution_allowed
        ):
            findings.append(
                CheckFinding(
                    "VQ-LICENSE",
                    "error",
                    f"asset is not redistributable: {snapshot.ref.asset_id}",
                )
            )
    for visual in timeline.visuals:
        if visual.kind == "media":
            assert visual.asset is not None
            snapshot = snapshots[visual.asset]
            if snapshot.media.kind not in {"video", "image"}:
                findings.append(
                    CheckFinding(
                        "VQ-ASSET",
                        "error",
                        f"visual uses nonvisual asset: {visual.asset.asset_id}",
                    )
                )
            if (
                snapshot.media.duration_ns is not None
                and not visual.loop
                and not visual.freeze_at_end
                and visual.source_start_ns + visual.duration_ns
                > snapshot.media.duration_ns
            ):
                findings.append(
                    CheckFinding(
                        "VQ-SYNC",
                        "error",
                        f"visual exceeds source: {visual.asset.asset_id}",
                    )
                )
        if visual.kind == "text":
            assert visual.font_asset is not None
            if snapshots[visual.font_asset].media.kind != "font":
                findings.append(
                    CheckFinding(
                        "VQ-ASSET",
                        "error",
                        f"text uses non-font asset: {visual.font_asset.asset_id}",
                    )
                )
    for item in timeline.audio:
        snapshot = snapshots[item.asset]
        if snapshot.media.kind not in {"audio", "video"}:
            findings.append(
                CheckFinding(
                    "VQ-ASSET",
                    "error",
                    f"audio uses non-audio asset: {item.asset.asset_id}",
                )
            )
        if (
            snapshot.media.duration_ns is not None
            and not item.loop
            and item.source_start_ns + item.duration_ns
            > snapshot.media.duration_ns
        ):
            findings.append(
                CheckFinding(
                    "VQ-SYNC",
                    "error",
                    f"audio exceeds source: {item.asset.asset_id}",
                )
            )
    if policy.platform == "vertical" and timeline.height <= timeline.width:
        findings.append(
            CheckFinding("VQ-RES", "error", "vertical policy requires portrait")
        )
    if policy.platform == "landscape" and timeline.width <= timeline.height:
        findings.append(
            CheckFinding("VQ-RES", "error", "landscape policy requires landscape")
        )
    policy_hash = canonical_hash(
        policy.as_payload(), domain="dlstudio.timeline_check_policy"
    )
    return CheckReport(timeline.timeline_id, policy_hash, tuple(findings))
