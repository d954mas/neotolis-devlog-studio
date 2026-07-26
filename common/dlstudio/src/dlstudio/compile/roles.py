"""Content-type registry — role classification + path/background extractors.

Dispatch on the `content` variant used to be an isinstance ladder repeated
across `_build_overlays`, `_referenced_paths`, and `segments._content_bg`
(finding L4: adding a Content type touched ~5 files). This registry collapses
that: a content variant declares, ONCE, what it does at compile time.

Each `ContentRole` says:
- `role`: "overlay" (its own raster visual) or "segment" (an ffmpeg
  background source). Segment-role content ALSO becomes an overlay item when
  the chunk carries decorations — that H1 rule lives in `_build_overlays`,
  keyed off this single `role` field.
- `referenced_paths`: (path, kind) pairs the content pulls into the asset
  probe registry.
- `raster_asset_paths`: filesystem paths the RASTER pass actually reads for
  this content (e.g. Plate.bg_image) — folded into the overlay item's
  `asset_paths` so the beat cache tracks their identity (size+mtime).
- `background`: for segment-role content, the BgSpec its window renders as.

To add a Content type:
1) model/content.py — new class + add it to the `Content` union.
2) register it here (`CONTENT_ROLES`) with role + extractors.
3) render/raster — register a renderer in `CONTENT_RENDERERS`.
"""
from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass, field

from dlstudio.model.content import ImageShot, Overlay, Plate, VideoShot

from .probe import Kind


@dataclass(frozen=True)
class BgSpec:
    """A content-derived background segment source (mirrors a scene-derived
    background). Consumed by segments.build_segments."""

    kind: str          # "image" | "video"
    src: str
    asset_id: str | None
    render_manifest: str | None
    editorial_role: str | None
    expected_state_id: str | None
    expected_build_id: str | None
    expected_action_id: str | None
    offset: float
    ken_burns: bool
    loop: bool
    fit: str
    anchor_x: float
    anchor_y: float


@dataclass(frozen=True)
class ContentRole:
    role: str  # "overlay" | "segment"
    referenced_paths: Callable[[object], list[tuple[str | None, Kind]]] = field(
        default=lambda c: []
    )
    raster_asset_paths: Callable[[object], list[str]] = field(default=lambda c: [])
    background: Callable[[object], BgSpec | None] = field(default=lambda c: None)


CONTENT_ROLES: dict[type, ContentRole] = {}


def register_content(content_type: type, role: ContentRole) -> None:
    CONTENT_ROLES[content_type] = role


def content_role(content: object) -> ContentRole | None:
    return CONTENT_ROLES.get(type(content))


# ─── registrations ─────────────────────────────────────────────────────────

register_content(Plate, ContentRole(
    role="overlay",
    referenced_paths=lambda c: [(c.bg_image, "image")],
    raster_asset_paths=lambda c: [c.bg_image] if c.bg_image else [],
))

register_content(Overlay, ContentRole(role="overlay"))

register_content(ImageShot, ContentRole(
    role="segment",
    referenced_paths=lambda c: [(c.src, "image")],
    background=lambda c: BgSpec(kind="image", src=c.src,
                                asset_id=c.asset_id,
                                render_manifest=None,
                                editorial_role=c.editorial_role,
                                expected_state_id=None,
                                expected_build_id=None,
                                expected_action_id=None,
                                offset=0.0,
                                ken_burns=c.ken_burns, loop=False, fit=c.fit,
                                anchor_x=c.anchor_x, anchor_y=c.anchor_y),
))

register_content(VideoShot, ContentRole(
    role="segment",
    referenced_paths=lambda c: [(c.src, "video")],
    background=lambda c: BgSpec(kind="video", src=c.src,
                                asset_id=c.asset_id,
                                render_manifest=c.render_manifest,
                                editorial_role=c.editorial_role,
                                expected_state_id=c.expected_state_id,
                                expected_build_id=c.expected_build_id,
                                expected_action_id=c.expected_action_id,
                                offset=c.offset,
                                ken_burns=False, loop=False, fit=c.fit,
                                anchor_x=c.anchor_x, anchor_y=c.anchor_y),
))
