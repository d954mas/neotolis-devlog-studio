"""Visual effects: radial vignette overlay (RGBA), cached per resolution.

The vignette is content-independent — same image for every frame of a given
resolution — so we cache it. Cache key is `design.resolution` so different
edits (YT vs reel) get their own cached overlay.
"""
from __future__ import annotations
import math
from typing import Tuple
from PIL import Image, ImageDraw, ImageFilter

from devlog.types import Design


_VIGNETTE_CACHE: dict[Tuple[int, int], Image.Image] = {}


def _make_vignette(size: Tuple[int, int]) -> Image.Image:
    """Build a subtle radial vignette overlay (RGBA) for the given size.

    Produces a transparent layer that's dark at the corners and clear in the
    center. Alpha-composite onto a frame to add depth.
    """
    w, h = size
    mask = Image.new("L", (w, h), 0)
    cx, cy = w // 2, h // 2
    max_r = math.hypot(cx, cy)
    # Radial gradient: 0 at center → 255 at corners (stepped, blurred below)
    for y in range(0, h, 4):
        for x in range(0, w, 4):
            r = math.hypot(x - cx, y - cy) / max_r
            v = int(255 * (r ** 1.6) * 0.45)         # 0.45 = max darken at corner
            mask.paste(v, (x, y, x + 4, y + 4))
    mask = mask.filter(ImageFilter.GaussianBlur(40))
    overlay = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    dark = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    overlay = Image.composite(dark, overlay, mask)
    return overlay


def vignette(design: Design) -> Image.Image:
    """Return the cached vignette overlay for this design's resolution."""
    key = design.resolution
    if key not in _VIGNETTE_CACHE:
        _VIGNETTE_CACHE[key] = _make_vignette(key)
    return _VIGNETTE_CACHE[key]
