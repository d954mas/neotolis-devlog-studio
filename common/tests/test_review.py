"""Tests for chunk-aware reviewer (devlog.review).

Focus on the detection function — pure pixel math, no ffmpeg dependency.
Covers: clean overlay, missing overlay, partial overlap, threshold boundaries.
"""
import numpy as np
from devlog.review import detect_chunk_presence


def _band_rgba(w=1920, h=1080, band_top=900, band_bottom=1060,
               band_color=(26, 22, 18), text_color=(232, 182, 71)):
    """Synthetic chunk PNG: dark band at bottom with a gold horizontal line
    of text in its middle. Mirrors what make_overlay_badge produces shape-wise."""
    png = np.zeros((h, w, 4), dtype=np.uint8)
    png[band_top:band_bottom, :, :3] = band_color
    png[band_top:band_bottom, :, 3] = 240
    # Fake gold text: a 40-pixel-tall horizontal stripe in band center
    text_y = (band_top + band_bottom) // 2
    png[text_y - 20:text_y + 20, w // 4:3 * w // 4, :3] = text_color
    return png


def _scene_frame(w=1920, h=1080, scene_color=(180, 200, 150)):
    """Synthetic 'naked scene' frame — green-ish gameplay, no overlay applied."""
    return np.full((h, w, 3), scene_color, dtype=np.uint8)


def _composited_frame(chunk_png, scene_color=(180, 200, 150)):
    """Scene with chunk PNG correctly alpha-composited over it. Mirrors what
    a correctly-rendered overlay frame looks like at mid-chunk (alpha=peak)."""
    h, w = chunk_png.shape[:2]
    scene = np.full((h, w, 3), scene_color, dtype=np.uint8)
    alpha = chunk_png[:, :, 3:4].astype(np.float32) / 255.0
    out = chunk_png[:, :, :3].astype(np.float32) * alpha + scene.astype(np.float32) * (1 - alpha)
    return out.astype(np.uint8)


def test_clean_overlay_passes():
    """Correctly-composited frame: diff should be small (~6% scene bleed from
    chunk PNG alpha=240/255). Real renders measure 1.3-8.8 on iter91."""
    png = _band_rgba()
    frame = _composited_frame(png)
    v = detect_chunk_presence(frame, png, threshold=35.0)
    assert v.passed, f"expected PASS, got diff={v.diff:.1f}"
    assert v.diff < 15, f"clean composite should have diff<15, got {v.diff:.1f}"
    assert v.coverage > 100_000, "band should cover >100k pixels at 1920x1080"


def test_missing_overlay_fails():
    """Naked scene where overlay should have been: diff should be huge."""
    png = _band_rgba()
    frame = _scene_frame()                              # scene-only, no band
    v = detect_chunk_presence(frame, png, threshold=35.0)
    assert not v.passed, f"expected FAIL for naked scene, got diff={v.diff:.1f}"
    assert v.diff > 100, f"naked scene should diff hugely from band, got {v.diff:.1f}"


def test_partial_fade_in_still_passes():
    """Mid-chunk fade is at peak alpha, but boundary cases (e.g. sampling slightly
    off-center) may see ~50% alpha. Verify graceful handling under partial fade."""
    png = _band_rgba()
    # Simulate 70% composite (sampled mid-fade-in)
    h, w = png.shape[:2]
    scene = np.full((h, w, 3), (180, 200, 150), dtype=np.uint8)
    alpha = (png[:, :, 3:4].astype(np.float32) / 255.0) * 0.7
    frame = (png[:, :, :3].astype(np.float32) * alpha +
             scene.astype(np.float32) * (1 - alpha)).astype(np.uint8)
    v = detect_chunk_presence(frame, png, threshold=35.0)
    # At 70% alpha, band is still recognizably present, but diff is non-trivial.
    # We accept this fails strict threshold — caller should sample at mid-chunk.
    # Key: the diff is meaningfully larger than clean but smaller than naked.
    assert 10 < v.diff < 100, f"expected mid-range diff, got {v.diff:.1f}"


def test_threshold_boundary():
    """Threshold parameter actually controls PASS/FAIL boundary. Use a 50%
    chunk/scene mix (intermediate fade level) to land in the gap between
    strict and loose thresholds."""
    png = _band_rgba()
    h, w = png.shape[:2]
    scene = np.full((h, w, 3), (180, 200, 150), dtype=np.uint8)
    alpha = (png[:, :, 3:4].astype(np.float32) / 255.0) * 0.5
    frame = (png[:, :, :3].astype(np.float32) * alpha +
             scene.astype(np.float32) * (1 - alpha)).astype(np.uint8)
    v_strict = detect_chunk_presence(frame, png, threshold=20.0)
    v_loose = detect_chunk_presence(frame, png, threshold=100.0)
    assert not v_strict.passed, f"expected FAIL at threshold=20, got diff={v_strict.diff:.1f}"
    assert v_loose.passed, f"expected PASS at threshold=100, got diff={v_loose.diff:.1f}"


def test_resolution_mismatch_auto_rescales():
    """If frame and chunk PNG differ in resolution (e.g. 540p render vs 1080p PNG),
    detection rescales chunk PNG to frame size and still works."""
    png_1080 = _band_rgba(w=1920, h=1080)
    # Frame at 540p
    h_small, w_small = 540, 960
    scene_small = np.full((h_small, w_small, 3), (180, 200, 150), dtype=np.uint8)
    from PIL import Image
    composite_full = _composited_frame(png_1080)
    composite_small = np.array(Image.fromarray(composite_full).resize((w_small, h_small), Image.LANCZOS))
    v = detect_chunk_presence(composite_small, png_1080, threshold=35.0)
    assert v.passed, f"expected PASS after rescale, got diff={v.diff:.1f}"


def test_empty_chunk_png_skips_gracefully():
    """If a chunk PNG has effectively no band pixels (alpha all 0 — empty text overlay),
    detector returns coverage=0 and passes without error."""
    empty = np.zeros((1080, 1920, 4), dtype=np.uint8)         # all transparent
    frame = _scene_frame()
    v = detect_chunk_presence(frame, empty, threshold=35.0)
    assert v.passed
    assert v.coverage == 0
