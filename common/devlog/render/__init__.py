"""Render primitives: plates, overlays, images, scene segments.

All functions accept a `design: Design` parameter — no module-level
color/font constants. This is what makes the engine reusable across
projects and aspect ratios (16:9 / 9:16 / 1:1).
"""
from .plate import make_plate
from .overlay import make_overlay_badge, overlay_label
from .image import make_image_clip
from .effects import vignette
from .text import has_cyrillic, pick_font
from .compose import compose
