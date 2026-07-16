"""Shared helpers for the raster renderers: color/font resolution, text
measurement, and the `_Layout` geometry hint passed from a content renderer
to the decoration passes that follow it.

Kept private (leading underscore module name) — everything here is an
implementation detail of `render.raster`; the public surface is
`render_chunk_png` / `render_chunk_image` in `__init__.py`.
"""
from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from PIL import ImageFont

from dlstudio.model import Design


# ─── Layout hint ─────────────────────────────────────────────────────────
#
# Decorations are independent compositing passes over the finished content
# raster (v2 architecture: no reflow coupling between content and
# decorations — see docs/ARCHITECTURE_V2.md "composition over flags").
# `_Layout` is a best-effort geometry hint so a decoration CAN align itself
# to the content when that content is text (Plate), while still degrading
# gracefully (documented fallback positions) for content types that carry
# no text geometry (Overlay/ImageShot/VideoShot).

@dataclass(frozen=True)
class Layout:
    text_top: int | None = None
    text_bottom: int | None = None
    text_center_x: int | None = None
    main_size_px: int | None = None


# ─── Color ───────────────────────────────────────────────────────────────

def hex_to_rgb(value: str) -> tuple[int, int, int]:
    v = value.lstrip("#")
    if len(v) == 3:
        v = "".join(ch * 2 for ch in v)
    if len(v) != 6:
        raise ValueError(f"not a #rrggbb color: {value!r}")
    return (int(v[0:2], 16), int(v[2:4], 16), int(v[4:6], 16))


# ─── Fonts ───────────────────────────────────────────────────────────────
#
# Cyrillic detection is ported from legacy render/text.py — used to
# compensate vertical centering for tall diacritics (Й/Ё) when laying out
# Plate text. Legacy also swapped between two whole font FAMILIES
# (fonts.display vs fonts.text) based on script; v2's Design.Fonts model
# only has role slots (main/bold/accent), not language slots, so that
# family-swap is intentionally dropped — see raster-agent report.

def has_cyrillic(text: str) -> bool:
    """True if text contains any Cyrillic character (basic + extended)."""
    return any("Ѐ" <= ch <= "ӿ" for ch in text)


def font_path(design: Design, role: str) -> str | None:
    """Resolve a TextStyle.font role ("main"|"bold"|"accent") to a TTF path,
    falling back to `main` per the Fonts model contract."""
    fonts = design.fonts
    if role == "main":
        return fonts.main
    value = getattr(fonts, role, None)
    return value or fonts.main


@lru_cache(maxsize=None)
def _load_font_cached(path: str | None, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    size = max(1, int(size))
    if path:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    # Fall back to PIL's built-in font — tests (and any environment without
    # the project's TTFs installed) still render deterministically.
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        # Pillow < 9.2 doesn't take a `size` kwarg for the bitmap default font.
        return ImageFont.load_default()


def load_font(design: Design, role: str, size: int) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    return _load_font_cached(font_path(design, role), size)


# ─── Text measurement ────────────────────────────────────────────────────

def text_width(draw, text: str, font) -> int:
    bbox = draw.textbbox((0, 0), text, font=font, anchor="lt")
    return bbox[2] - bbox[0]


def text_box(draw, text: str, font, spacing: int = 0) -> tuple[int, int]:
    """Bounding box (w, h) of `text`, multiline-aware."""
    if not text:
        return 0, 0
    if "\n" in text:
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
    else:
        bbox = draw.textbbox((0, 0), text, font=font, anchor="lt")
    return bbox[2] - bbox[0], bbox[3] - bbox[1]


def text_ink_bottom(draw, text: str, font, spacing: int = 0) -> int:
    """y-offset from a text block's draw origin to the bottom of its
    rendered ink, when drawn with PIL's *default* anchor (no `anchor=`
    kwarg — required for multiline text, which doesn't support anchor).

    Needed because `bbox[3] - bbox[1]` (ink height) is NOT the same as
    this offset whenever the font has a non-zero ascender-to-cap-top gap
    — notably the PIL fallback bitmap font used when a project TTF is
    missing. Using ink *height* where this ink-bottom *offset* was meant
    causes a subtitle to be drawn overlapping the line above it. This is
    a latent bug in the legacy overlay renderer's subtitle-gap math
    (`ty + th + gap`); fixed here rather than ported, since it produces
    visibly broken output (see raster-agent report)."""
    if not text:
        return 0
    if "\n" in text:
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=spacing)
    else:
        bbox = draw.textbbox((0, 0), text, font=font)
    return bbox[3]
