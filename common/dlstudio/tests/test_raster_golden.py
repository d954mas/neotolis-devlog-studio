"""Golden-image regression tests for `dlstudio.render.raster`.

Renders a canonical set of chunks at 960x540 using a small test
palette/style registry (defined here — real projects define their own;
the engine must never assume these values) and compares against
reference PNGs in tests/golden/.

Usage:
    # (Re)generate golden references after an intentional visual change:
    GOLDEN=1 python -m pytest common/dlstudio/tests/test_raster_golden.py -q

    # Normal run: compares current renders against the committed references.
    python -m pytest common/dlstudio/tests/test_raster_golden.py -q

Comparison approach ported from common/tests/test_visual_regression.py:
tolerant pixel-diff metrics rather than strict byte equality, so a future
Pillow/FreeType point release (different default-font hinting) doesn't
spuriously break the suite. Byte-exact reproducibility within ONE
environment is covered separately by test_raster_unit.py::test_determinism_*.
"""
from __future__ import annotations

import os
import shutil
from pathlib import Path

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
)
from dlstudio.render.raster import render_chunk_image

GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_DIR.mkdir(exist_ok=True)

RESOLUTION = (960, 540)

# Real system TTF for the T3 typography golden. The rest of the suite uses a
# nonexistent TTF (PIL default-font fallback); this one variant pins real
# FreeType rendering — including Cyrillic shaping — so a font/hinting change is
# caught. Skipped where the font isn't installed (CI without Windows fonts).
ARIAL = Path("C:/Windows/Fonts/arial.ttf")


def _design() -> Design:
    """Test-only design + style registry (styling discipline: the engine
    itself contains no brand constants — this is project-shaped test data)."""
    return Design(
        resolution=RESOLUTION,
        fps=30,
        palette=Palette(tokens={
            "bg": "#141210",
            "text": "#f5f0e6",
            "accent": "#d4a941",
            "muted": "#8a7f6b",
        }),
        # Nonexistent TTF on purpose: exercises the PIL-default-font
        # fallback path — this suite runs without the project's real fonts.
        fonts=Fonts(main="fonts/DoesNotExist-Bold.ttf"),
        styles={
            "plate.default": TextStyle(size=140, color="text", font="bold", line_gap_ratio=0.18),
            "plate.climax": TextStyle(size=190, color="accent", font="bold", line_gap_ratio=0.18),
            "overlay.default": TextStyle(size=86, color="text", font="bold", line_gap_ratio=0.20),
            "overlay.card": TextStyle(size=150, color="accent", font="bold", line_gap_ratio=0.20),
            "overlay.hero": TextStyle(size=130, color="text", font="bold", line_gap_ratio=0.16),
        },
        safe_margin_ratio=0.05,
    )


@pytest.fixture(scope="module")
def design() -> Design:
    return _design()


@pytest.fixture(scope="module")
def gradient_path(tmp_path_factory) -> Path:
    """Deterministic synthetic gradient PNG, used as a bg_image / ImageShot
    source — generated with PIL/numpy rather than committing a binary asset."""
    path = tmp_path_factory.mktemp("raster-golden-assets") / "gradient.png"
    w, h = 640, 360
    xx, yy = np.meshgrid(np.linspace(0, 255, w), np.linspace(0, 255, h))
    arr = np.zeros((h, w, 3), dtype=np.uint8)
    arr[:, :, 0] = xx.astype(np.uint8)
    arr[:, :, 1] = yy.astype(np.uint8)
    arr[:, :, 2] = (255 - xx).astype(np.uint8)
    Image.fromarray(arr).save(path)
    return path


def _png_diff(a_path: Path, b_path: Path) -> dict:
    a = np.array(Image.open(a_path).convert("RGBA"), dtype=np.float32)
    b = np.array(Image.open(b_path).convert("RGBA"), dtype=np.float32)
    if a.shape != b.shape:
        return {"shape_match": False, "shape_a": a.shape, "shape_b": b.shape}
    diff = np.abs(a - b)
    per_pixel_max = diff.max(axis=-1)
    return {
        "shape_match": True,
        "mean_diff": float(diff.mean()),
        "max_diff": float(diff.max()),
        "pct_pixels_changed": float((per_pixel_max > 10).mean() * 100),
        "pct_pixels_big_diff": float((per_pixel_max > 30).mean() * 100),
    }


def _check_golden(name: str, img: Image.Image, tmp_path: Path) -> None:
    current = tmp_path / f"{name}.png"
    img.save(current, format="PNG")

    golden = GOLDEN_DIR / f"{name}.png"
    update_golden = os.environ.get("GOLDEN") == "1"
    if update_golden or not golden.exists():
        shutil.copyfile(current, golden)
        return

    metrics = _png_diff(current, golden)
    assert metrics["shape_match"], f"{name}: shape mismatch — {metrics}"
    assert metrics["mean_diff"] < 1.5, f"{name}: mean diff {metrics['mean_diff']:.3f} — {metrics}"
    assert metrics["pct_pixels_changed"] < 1.0, (
        f"{name}: {metrics['pct_pixels_changed']:.2f}% pixels changed — {metrics}"
    )
    assert metrics["pct_pixels_big_diff"] < 0.2, (
        f"{name}: {metrics['pct_pixels_big_diff']:.2f}% major-diff pixels — {metrics}"
    )


# ─── Canonical set (at least: see raster-agent task spec) ───────────────

def test_golden_plate_plain(design, tmp_path):
    chunk = Chunk(words=(0, 4), content=Plate(text="30 000\nSTROK"))
    _check_golden("plate_plain", render_chunk_image(chunk, design), tmp_path)


def test_golden_plate_underline(design, tmp_path):
    chunk = Chunk(words=(0, 4), content=Plate(text="ITOG", style="plate.climax"),
                  decorations=[Underline()])
    _check_golden("plate_underline", render_chunk_image(chunk, design), tmp_path)


def test_golden_plate_bg_image(design, tmp_path, gradient_path):
    chunk = Chunk(words=(0, 4), content=Plate(text="DOSTIZHENIE",
                                               bg_image=str(gradient_path), bg_opacity=0.35))
    _check_golden("plate_bg_image", render_chunk_image(chunk, design), tmp_path)


def test_golden_overlay_band_subtitle(design, tmp_path):
    chunk = Chunk(words=(0, 4), content=Overlay(text="New record", subtitle="Personal best",
                                                 variant="band", position="bottom"))
    _check_golden("overlay_band_subtitle", render_chunk_image(chunk, design), tmp_path)


def test_golden_overlay_card(design, tmp_path):
    chunk = Chunk(words=(0, 4), content=Overlay(text="30 000", subtitle="lines of code",
                                                 variant="card", style="overlay.card"))
    _check_golden("overlay_card", render_chunk_image(chunk, design), tmp_path)


def test_golden_overlay_hero(design, tmp_path):
    chunk = Chunk(words=(0, 4), content=Overlay(text="SHIP IT", variant="hero", style="overlay.hero"))
    _check_golden("overlay_hero", render_chunk_image(chunk, design), tmp_path)


def test_golden_image_cover_caption_pill(design, tmp_path, gradient_path):
    chunk = Chunk(words=(0, 4), content=ImageShot(src=str(gradient_path), fit="cover"),
                  decorations=[CaptionPill(text="GAMEPLAY")])
    _check_golden("image_cover_caption_pill", render_chunk_image(chunk, design), tmp_path)


def test_golden_plate_badge_framed_card(design, tmp_path):
    chunk = Chunk(words=(0, 4), content=Plate(text="WINNER", style="plate.climax"),
                  decorations=[Badge(name="trophy"), FramedCard()])
    _check_golden("plate_badge_framed_card", render_chunk_image(chunk, design), tmp_path)


def test_golden_vignette_pass(design, tmp_path, gradient_path):
    chunk = Chunk(words=(0, 4), content=ImageShot(src=str(gradient_path), fit="cover"),
                  decorations=[Vignette(strength=0.6)])
    _check_golden("vignette_pass", render_chunk_image(chunk, design), tmp_path)


# ─── T3: real-TTF typography (Cyrillic), pinned separately ──────────────────

@pytest.mark.skipif(not ARIAL.exists(), reason="system arial.ttf not installed")
def test_golden_plate_real_font_cyrillic(design, tmp_path):
    """Pins real FreeType typography (not the PIL bitmap fallback the rest of
    the suite uses), including Cyrillic glyph shaping + the diacritic-aware
    vertical centering path in render_plate."""
    real = design.model_copy(update={"fonts": Fonts(main=str(ARIAL))})
    chunk = Chunk(words=(0, 4), content=Plate(text="30 000\nСТРОК", style="plate.climax"),
                  decorations=[Underline()])
    _check_golden("plate_real_font_cyrillic", render_chunk_image(chunk, real), tmp_path)
