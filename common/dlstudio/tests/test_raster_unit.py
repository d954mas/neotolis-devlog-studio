"""Unit tests for `dlstudio.render.raster` behavior not covered by the
golden-image suite: style fallback chain, palette token errors, the
transparent VideoShot contract, determinism, and font-fallback robustness.
"""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image

from dlstudio.model import (
    Badge,
    CaptionPill,
    Chunk,
    Design,
    Fonts,
    FramedCard,
    ImageShot,
    Overlay,
    Palette,
    Plate,
    TextStyle,
    Underline,
    Vignette,
    VideoShot,
)
from dlstudio.render.raster import render_chunk_image, render_chunk_png
from dlstudio.render.raster._util import hex_to_rgb

RESOLUTION = (960, 540)


def _design(**styles: TextStyle) -> Design:
    return Design(
        resolution=RESOLUTION,
        fps=30,
        palette=Palette(tokens={"bg": "#141210", "text": "#f5f0e6", "accent": "#d4a941"}),
        fonts=Fonts(main="fonts/DoesNotExist-Bold.ttf"),
        styles=styles,
    )


@pytest.fixture
def design() -> Design:
    return _design(
        **{
            "plate.default": TextStyle(size=140, color="text", font="bold", line_gap_ratio=0.18),
            "plate.climax": TextStyle(size=190, color="accent", font="bold", line_gap_ratio=0.18),
        }
    )


# ─── Style fallback chain (Design.style: exact -> "<kind>.default" -> hard default) ──

def test_style_fallback_exact_match(design):
    assert design.style("plate.climax").size == 190


def test_style_fallback_to_kind_default(design):
    resolved = design.style("plate.does_not_exist")
    assert resolved.size == design.styles["plate.default"].size


def test_style_fallback_hard_default_when_no_registry():
    d = _design()  # no styles at all
    resolved = d.style("overlay.anything")
    assert resolved.size == 220  # Design.style()'s documented hard default


# ─── Palette token resolution ─────────────────────────────────────────────

def test_palette_missing_token_raises_keyerror(design):
    with pytest.raises(KeyError):
        design.palette.color("does_not_exist")


def test_palette_literal_hex_passthrough(design):
    assert design.palette.color("#abcdef") == "#abcdef"


def test_palette_known_token_resolves(design):
    assert design.palette.color("accent") == "#d4a941"


# ─── VideoShot / ImageShot: raster renders nothing but decorations ─────────

def test_video_shot_is_fully_transparent(design):
    chunk = Chunk(words=(0, 1), content=VideoShot(src="unused.mp4"))
    img = render_chunk_image(chunk, design)
    assert img.mode == "RGBA"
    assert img.size == design.resolution
    alpha = np.array(img)[:, :, 3]
    assert alpha.max() == 0, "VideoShot must rasterize to a fully transparent frame"


def test_image_shot_is_fully_transparent(design):
    # H1: the image itself comes from the ffmpeg scene segment; raster must not
    # draw a static copy of it.
    chunk = Chunk(words=(0, 1), content=ImageShot(src="unused.png"))
    img = render_chunk_image(chunk, design)
    assert img.mode == "RGBA"
    assert img.size == design.resolution
    assert np.array(img)[:, :, 3].max() == 0, "ImageShot must rasterize transparent"


def test_image_shot_with_caption_pill_transparent_except_pill(design):
    # H1: decorations DO composite over the transparent image frame — the PNG
    # is transparent everywhere except the (top-left) CaptionPill.
    chunk = Chunk(words=(0, 1), content=ImageShot(src="unused.png"),
                  decorations=[CaptionPill(text="GAMEPLAY")])
    img = render_chunk_image(chunk, design)
    alpha = np.array(img)[:, :, 3]
    W, H = design.resolution
    # the pill is a small top-left badge: some ink there, but the frame is
    # overwhelmingly transparent, and the image body (centre) stays empty.
    assert alpha.max() == 255                       # the pill drew opaque ink
    assert (alpha > 0).mean() < 0.25, "only the pill should be opaque, not the image"
    assert (alpha[:H // 4, :W // 3] > 0).any()      # ink in the top-left pill region
    assert alpha[H // 2, W // 2] == 0               # centre (image body) transparent


# ─── Determinism: same inputs -> byte-identical PNG ───────────────────────

def test_determinism_png_bytes(design, tmp_path):
    chunk = Chunk(
        words=(0, 4),
        content=Plate(text="Determinism check", style="plate.climax"),
        decorations=[Underline(), Badge(name="silver"), FramedCard(), Vignette()],
    )
    p1 = render_chunk_png(chunk, design, tmp_path / "a.png")
    p2 = render_chunk_png(chunk, design, tmp_path / "b.png")
    assert p1.read_bytes() == p2.read_bytes()


def test_determinism_overlay_hero(design, tmp_path):
    chunk = Chunk(words=(0, 3), content=Overlay(text="Ship it\ntoday", variant="hero"))
    p1 = render_chunk_png(chunk, design, tmp_path / "a.png")
    p2 = render_chunk_png(chunk, design, tmp_path / "b.png")
    assert p1.read_bytes() == p2.read_bytes()


def test_determinism_image_array_equal(design):
    chunk = Chunk(words=(0, 2), content=Plate(text="X"))
    a = np.array(render_chunk_image(chunk, design))
    b = np.array(render_chunk_image(chunk, design))
    assert np.array_equal(a, b)


# ─── Font fallback: renders without raising when the TTF path is missing ──

def test_renders_without_project_fonts(design):
    chunk = Chunk(words=(0, 2), content=Plate(text="No fonts here"))
    img = render_chunk_image(chunk, design)  # must not raise
    bg = hex_to_rgb(design.palette.color("bg"))
    arr = np.array(img.convert("RGB"))
    assert (arr != np.array(bg)).any(), "expected the fallback font to actually draw ink"


# ─── Decoration Layout coupling: Plate wires text geometry, other content
# types degrade to a documented generic fallback rather than crashing ──────

def test_underline_generic_fallback_on_non_plate_content(design):
    chunk = Chunk(words=(0, 2), content=Overlay(text="Hi"), decorations=[Underline()])
    img = render_chunk_image(chunk, design)  # must not raise
    assert img.size == design.resolution


def test_badge_generic_fallback_on_non_plate_content(design):
    chunk = Chunk(words=(0, 2), content=Overlay(text="Hi"), decorations=[Badge(name="silver")])
    img = render_chunk_image(chunk, design)
    assert img.size == design.resolution


# ─── content.size overrides the style's size ──────────────────────────────

def _ink_bbox(img: Image.Image, bg_rgb: tuple[int, int, int]):
    arr = np.array(img.convert("RGB")).astype(int)
    diff = np.abs(arr - np.array(bg_rgb)).sum(axis=-1)
    ys, xs = np.where(diff > 30)
    if len(xs) == 0:
        return None
    return xs.min(), ys.min(), xs.max(), ys.max()


def test_plate_size_override_changes_text_extent(design):
    bg_rgb = hex_to_rgb(design.palette.color("bg"))
    small = Chunk(words=(0, 1), content=Plate(text="X", size=40))
    big = Chunk(words=(0, 1), content=Plate(text="X", size=300))
    small_bbox = _ink_bbox(render_chunk_image(small, design), bg_rgb)
    big_bbox = _ink_bbox(render_chunk_image(big, design), bg_rgb)
    assert small_bbox and big_bbox
    small_h = small_bbox[3] - small_bbox[1]
    big_h = big_bbox[3] - big_bbox[1]
    assert big_h > small_h * 2


# ─── px()/scale semantics vs legacy devlog.types.Design ──────────────────
#
# Legacy: scale = resolution[0] (WIDTH) / 1920.0; px(v) = int(round(v*scale)).
# v2 model matches legacy width-based semantics for ALL aspect ratios
# (fixed at integration after the raster port flagged the divergence —
# width-based is the production-proven behavior for 9:16 reels).

def test_px_matches_legacy_width_basis_for_16_9():
    d = _design()
    assert d.resolution == RESOLUTION
    legacy_scale = RESOLUTION[0] / 1920.0
    for v in (10, 90, 240, 480, 1080):
        assert d.px(v) == int(round(v * legacy_scale))


def test_px_matches_legacy_width_basis_for_vertical():
    d = Design(
        resolution=(1080, 1920),  # 9:16 reel
        palette=Palette(tokens={"bg": "#000000", "text": "#ffffff", "accent": "#ff0000"}),
        fonts=Fonts(main="x.ttf"),
    )
    legacy_scale = 1080 / 1920.0  # legacy: width-based
    assert d.px(480) == int(round(480 * legacy_scale))  # == 270, v1-tuned value
    assert d.scale == legacy_scale
