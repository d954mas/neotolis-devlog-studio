"""Radial vignette, vectorized with numpy.

Legacy (`common/devlog/render/effects.py`, and the even slower per-pixel
variant in `common/devlog/charts.py::_vignette`) computed the radial
alpha gradient with a nested Python `for y: for x:` loop over the frame,
stepped and block-pasted. That is O(W*H/step^2) pure-Python work per
call. Here the same radial falloff is computed as one vectorized numpy
expression (`np.mgrid` + `np.hypot` + `np.power`) — no Python-level pixel
loop — and only the (already fast, C-implemented) Gaussian blur uses PIL.
"""
from __future__ import annotations

import math

import numpy as np
from PIL import Image, ImageFilter

from dlstudio.model import Design


def radial_alpha_mask(w: int, h: int, max_alpha: float, exponent: float, blur_radius: int) -> Image.Image:
    """Return an "L" mode mask: 0 at center, rising to `max_alpha` at the
    corners following `r ** exponent`, then Gaussian-blurred for smoothness."""
    if w <= 0 or h <= 0:
        return Image.new("L", (max(1, w), max(1, h)), 0)
    yy, xx = np.mgrid[0:h, 0:w]
    cx, cy = (w - 1) / 2.0, (h - 1) / 2.0
    max_r = math.hypot(cx, cy) or 1.0
    r = np.hypot(xx - cx, yy - cy) / max_r
    alpha = np.clip(max_alpha * np.power(r, exponent), 0, 255).astype(np.uint8)
    mask = Image.fromarray(alpha)
    if blur_radius > 0:
        mask = mask.filter(ImageFilter.GaussianBlur(blur_radius))
    return mask


def vignette_layer(design: Design, strength: float) -> Image.Image:
    """Full-frame RGBA layer: transparent at center, black at the corners.
    `strength` (0..1) scales the maximum corner darkening — replaces the
    legacy hardcoded 0.45 constant baked into effects.py."""
    w, h = design.resolution
    strength = max(0.0, min(1.0, strength))
    mask = radial_alpha_mask(w, h, max_alpha=255.0 * strength, exponent=1.6,
                              blur_radius=max(1, design.px(10)))
    black = Image.new("RGBA", (w, h), (0, 0, 0, 255))
    transparent = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    return Image.composite(black, transparent, mask)
