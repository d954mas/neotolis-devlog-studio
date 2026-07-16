"""render.raster — PIL pre-render of chunk visuals to RGBA PNGs.

OWNER: raster-agent (port of legacy plate/overlay/image/effects/text
renderers to the v2 composition model).

Rules:
- (spec, design) discipline: styling comes from Design.styles / Palette;
  no module-level brand constants.
- Content variants (Plate/Overlay/ImageShot/VideoShot) map to renderers via
  the `CONTENT_RENDERERS` registry below; the `decorations` list composes on
  top (Underline, Badge, FramedCard, Vignette, Label, CaptionPill each render
  as an independent pass, dispatched via `_decorations.DECORATION_RENDERERS`).
- Cyrillic-capable font selection: port from legacy render/text.py.
- px()/scale semantics: port from legacy devlog/types.py Design.px —
  if legacy semantics differ from dlstudio.model.Design.px, align the
  model helper to legacy behavior and note it in the commit.

Implementation lives in the private `_content.py` (content renderers),
`_decorations.py` (decoration passes), `_effects.py` (vectorized
vignette), and `_util.py` (color/font/text-measurement helpers + the
`Layout` geometry hint passed from content to decorations). Only the two
functions below are public.

To add a Content type (finding L4 — one registry entry per concern):
1) model/content.py — new class + add it to the `Content` union.
2) compile/roles.py — register its role + path/background extractors.
3) here — add `render_<x>` in _content.py and register it in
   `CONTENT_RENDERERS`.
"""
from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

from PIL import Image

from dlstudio.model import Chunk, Design, ImageShot, Overlay, Plate, VideoShot

from ._content import render_image_shot, render_overlay, render_plate, render_video_shot
from ._decorations import apply_decoration
from ._util import Layout

# Content type -> renderer. Dead-simple dict dispatch (no plugin framework):
# adding a variant is one line here plus its renderer in _content.py.
CONTENT_RENDERERS: dict[type, Callable[[object, Design], tuple[Image.Image, Layout]]] = {
    Plate: render_plate,
    Overlay: render_overlay,
    ImageShot: render_image_shot,
    VideoShot: render_video_shot,
}


def _render_content(content, design: Design) -> tuple[Image.Image, Layout]:
    renderer = CONTENT_RENDERERS.get(type(content))
    if renderer is None:  # pragma: no cover — union is closed
        raise TypeError(f"unknown content type: {type(content).__name__}")
    return renderer(content, design)


def render_chunk_image(chunk: Chunk, design: Design) -> Image.Image:
    """Render the chunk's visual (content + decorations) to an RGBA image
    at design resolution. Deterministic: same inputs -> byte-stable output
    (required for cache correctness and golden tests).

    Motion (`chunk.anims`, Ken Burns, punch-in) and the background `scene`
    are intentionally NOT handled here — raster renders one static frame;
    motion and scene compositing are the ffmpeg graph layer's job.
    """
    img, layout = _render_content(chunk.content, design)
    img = img.convert("RGBA")
    for deco in chunk.decorations:
        img = apply_decoration(img, deco, design, layout)
    return img


def render_chunk_png(chunk: Chunk, design: Design, out_path: Path) -> Path:
    """Same as render_chunk_image but writes an RGBA PNG to out_path."""
    img = render_chunk_image(chunk, design)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")
    return out_path


def render_caption_image(text: str, design: Design) -> Image.Image:
    """Render ONE subtitle phrase (`Design.captions` style) to a full-frame
    RGBA image: wrapped, centered text over a soft backdrop pill in the
    bottom safe zone. The caption primitive for `beat.subtitles`
    (PLAN_STUDIO_V2 1.6) — one primitive, one position, one style."""
    from ._captions import render_caption

    return render_caption(text, design)


def render_caption_png(text: str, design: Design, out_path: Path) -> Path:
    """Same as render_caption_image but writes an RGBA PNG to out_path."""
    img = render_caption_image(text, design)
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, format="PNG")
    return out_path
