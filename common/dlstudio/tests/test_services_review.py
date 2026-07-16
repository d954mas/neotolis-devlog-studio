"""services/review.py — contact sheet + keyframes from a finished MP4, and
the `dl2 preview` command that orchestrates the whole draft path.
"""
from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from dlstudio.services import extract_keyframes, make_contact_sheet

pytestmark_integration = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH")


@pytest.fixture(scope="module")
def sample_video(tmp_path_factory):
    if shutil.which("ffmpeg") is None:      # pragma: no cover
        pytest.skip("ffmpeg not on PATH")
    d = tmp_path_factory.mktemp("review_media")
    mp4 = d / "draft.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         "testsrc=d=4:s=320x180:r=24", "-pix_fmt", "yuv420p", str(mp4)],
        check=True, capture_output=True)
    return mp4


@pytestmark_integration
def test_contact_sheet_tiles_grid(sample_video, tmp_path):
    out = tmp_path / "review" / "contact_sheet.jpg"
    got = make_contact_sheet(sample_video, out, cols=4, rows=4, cell_width=160)
    assert got == out and out.exists()
    img = Image.open(out)
    # 4 cols x 160px cells (+ padding/margins) — sanity, not pixel-exact
    assert img.width > 4 * 160
    assert img.height > img.width * 0.4          # 4 rows of 16:9 cells


@pytestmark_integration
def test_keyframes_count_and_cleanup(sample_video, tmp_path):
    out_dir = tmp_path / "kf"
    frames = extract_keyframes(sample_video, out_dir, count=6, width=320)
    assert len(frames) == 6
    assert [f.name for f in frames] == [f"kf_{i:02d}.jpg" for i in range(1, 7)]

    # A re-run with fewer frames must not leave stale files behind.
    frames2 = extract_keyframes(sample_video, out_dir, count=3, width=320)
    assert len(frames2) == 3
    assert len(list(out_dir.glob("kf_*.jpg"))) == 3


def test_contact_sheet_missing_video_raises(tmp_path):
    with pytest.raises(RuntimeError, match="does not exist"):
        make_contact_sheet(tmp_path / "nope.mp4", tmp_path / "o.jpg")


def test_keyframes_missing_video_raises(tmp_path):
    with pytest.raises(RuntimeError, match="does not exist"):
        extract_keyframes(tmp_path / "nope.mp4", tmp_path / "kf")
