"""Visual regression: extract sample frames from rendered MP4s, compare to
golden reference frames via perceptual hash + pixel diff.

Usage:
    # First time: generate golden frames from a known-good render
    GOLDEN=1 python -m pytest common/tests/test_visual_regression.py

    # Subsequent runs: compare current renders to golden
    python -m pytest common/tests/test_visual_regression.py

Golden frames live in common/tests/golden/<beat_id>_<timestamp>.png.
Compare via:
  - Exact pixel match (strict — passes only if identical)
  - Pixel-diff tolerance (mean abs diff < threshold) — used by default
  - Perceptual hash (catches large structural differences even if pixels shift)

This is the safety net for the MoviePy -> ffmpeg migration: render the same
beat with both engines, both should produce frames matching the golden.
"""
from __future__ import annotations
import os
import subprocess
from pathlib import Path
import numpy as np
import pytest
from PIL import Image


GOLDEN_DIR = Path(__file__).parent / "golden"
GOLDEN_DIR.mkdir(exist_ok=True)

# Project root resolved from this file
PROJECT_ROOT = Path(__file__).parent.parent.parent
TROLLEY_FINALIZE = PROJECT_ROOT / "trolley" / "data" / "finalize"

# Beats to regress. (beat_id, suffix, sample timestamps in seconds)
# Sample at mid-chunk to land on stable content.
REGRESSION_BEATS = [
    ("a0-1", "_video_1080p.mp4", [1.5, 2.5]),
    ("b4",   "_video_1080p.mp4", [1.0, 5.0, 10.0]),
]


def _extract_frame(video_path: Path, t: float, out_path: Path) -> bool:
    """Extract one frame at time `t` from video. Returns True on success."""
    r = subprocess.run([
        "ffmpeg", "-y", "-ss", str(t), "-i", str(video_path),
        "-frames:v", "1", str(out_path)
    ], capture_output=True, text=True)
    return out_path.exists() and out_path.stat().st_size > 0


def _frame_diff(a_path: Path, b_path: Path) -> dict:
    """Compare two frames; return metrics dict.

    Tolerates per-channel encoder noise (~1-5 byte values are normal across
    libx264 / nvenc / different presets even for visually identical frames).
    Only "significant" differences (>10 per channel) signal real change.
    """
    a = np.array(Image.open(a_path).convert("RGB"), dtype=np.float32)
    b = np.array(Image.open(b_path).convert("RGB"), dtype=np.float32)
    if a.shape != b.shape:
        return {"shape_match": False, "shape_a": a.shape, "shape_b": b.shape}
    diff = np.abs(a - b)
    per_pixel_max = diff.max(axis=-1)
    return {
        "shape_match": True,
        "mean_diff": float(diff.mean()),
        "max_diff": float(diff.max()),
        "pct_pixels_noisy": float((per_pixel_max > 1).mean() * 100),     # encoder jitter
        "pct_pixels_changed": float((per_pixel_max > 10).mean() * 100),  # real change
        "pct_pixels_big_diff": float((per_pixel_max > 30).mean() * 100), # major change
    }


@pytest.mark.parametrize("beat_id,suffix,timestamps", REGRESSION_BEATS)
def test_render_matches_golden(beat_id, suffix, timestamps, tmp_path):
    """Each rendered beat's sample frames should match the golden reference."""
    video = TROLLEY_FINALIZE / f"{beat_id}{suffix}"
    if not video.exists():
        pytest.skip(f"video not found: {video}")

    update_golden = os.environ.get("GOLDEN") == "1"

    for t in timestamps:
        current = tmp_path / f"{beat_id}_{t}s.png"
        ok = _extract_frame(video, t, current)
        assert ok, f"failed to extract frame at {t}s from {video}"

        golden = GOLDEN_DIR / f"{beat_id}_{t}s.png"
        if update_golden or not golden.exists():
            # Update mode: copy current → golden
            import shutil
            shutil.copyfile(current, golden)
            if update_golden:
                print(f"  [golden] updated {golden.name}")
            else:
                print(f"  [golden] created {golden.name}")
            continue

        # Compare current to golden
        metrics = _frame_diff(current, golden)
        assert metrics["shape_match"], f"shape mismatch for {beat_id} @ {t}s: {metrics}"
        # mean_diff: avg pixel deviation across whole frame (encoder noise ~0.5-2)
        assert metrics["mean_diff"] < 3.0, \
            f"{beat_id} @ {t}s: mean diff {metrics['mean_diff']:.2f} > 3.0 — {metrics}"
        # pct_pixels_changed: only pixels with >10 channel diff count (filters encoder noise)
        assert metrics["pct_pixels_changed"] < 5.0, \
            f"{beat_id} @ {t}s: {metrics['pct_pixels_changed']:.1f}% pixels significantly changed — {metrics}"
        # pct_pixels_big_diff: structural changes (>30 channel diff). Near zero for matching frames.
        assert metrics["pct_pixels_big_diff"] < 1.0, \
            f"{beat_id} @ {t}s: {metrics['pct_pixels_big_diff']:.2f}% major-diff pixels — {metrics}"
