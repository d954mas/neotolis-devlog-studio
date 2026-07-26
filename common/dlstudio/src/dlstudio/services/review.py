"""Review artifacts from a FINISHED MP4: contact sheet + keyframes.

Deliberately decoupled from the render pipeline (PLAN_STUDIO_V2 1.3): both
functions are plain ffmpeg passes over an existing file, so reviewer agents
can point them at any draft/final without touching compile/render state.

Conventions (what `dl2 preview` uses):
    contact sheet -> data/review/contact_sheet.jpg
    keyframes     -> data/review/keyframes/kf_01.jpg ... kf_NN.jpg
"""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

from PIL import Image


def _probe_duration(video: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(video)],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        raise RuntimeError(
            f"contact sheet: could not probe duration of {video}: "
            f"{r.stderr.strip()[-300:]}")


def _run_ffmpeg(cmd: list[str], what: str) -> None:
    r = subprocess.run(cmd, capture_output=True, text=True,
                       encoding="utf-8", errors="replace")
    if r.returncode != 0:
        raise RuntimeError(
            f"{what} failed (rc={r.returncode}): {r.stderr.strip()[-500:]}")


def make_contact_sheet(
    video: Path,
    out_jpg: Path,
    *,
    cols: int = 4,
    rows: int = 4,
    cell_width: int = 480,
) -> Path:
    """Tile `cols x rows` evenly-sampled frames of `video` into one JPEG.

    Frames are extracted first and then composed with Pillow. Doing the tile
    inside one FFmpeg filter graph is tempting but incorrect for real edits:
    FFmpeg reinitialises the tile filter when colour-range metadata changes at
    a beat boundary, discarding the samples collected before that boundary and
    producing a mostly-black partial sheet. Independent JPEG extraction is
    stable across those stream-parameter transitions.
    """
    video = Path(video)
    if not video.exists():
        raise RuntimeError(f"contact sheet: video does not exist: {video}")
    out_jpg = Path(out_jpg)
    out_jpg.parent.mkdir(parents=True, exist_ok=True)

    n = cols * rows
    duration = max(_probe_duration(video), 0.001)
    sample_fps = n / duration
    padding = 4
    margin = 4

    with tempfile.TemporaryDirectory(
        prefix=".contact-sheet-", dir=out_jpg.parent
    ) as temp_name:
        temp_dir = Path(temp_name)
        _run_ffmpeg(
            ["ffmpeg", "-y", "-i", str(video),
             "-vf", f"fps={sample_fps:.9f},scale={cell_width}:-2",
             "-frames:v", str(n), "-q:v", "3",
             str(temp_dir / "frame_%03d.jpg")],
            "contact sheet frames")
        frames = sorted(temp_dir.glob("frame_*.jpg"))
        if len(frames) != n:
            raise RuntimeError(
                f"contact sheet: expected {n} samples from {video}, "
                f"FFmpeg produced {len(frames)}"
            )

        with Image.open(frames[0]) as first:
            cell_height = first.height
        sheet_width = 2 * margin + cols * cell_width + (cols - 1) * padding
        sheet_height = 2 * margin + rows * cell_height + (rows - 1) * padding
        sheet = Image.new("RGB", (sheet_width, sheet_height), "black")
        for index, frame_path in enumerate(frames):
            with Image.open(frame_path) as frame:
                rgb = frame.convert("RGB")
                if rgb.size != (cell_width, cell_height):
                    raise RuntimeError(
                        f"contact sheet: inconsistent sample size {rgb.size}; "
                        f"expected {(cell_width, cell_height)}"
                    )
                row, col = divmod(index, cols)
                x = margin + col * (cell_width + padding)
                y = margin + row * (cell_height + padding)
                sheet.paste(rgb, (x, y))
        sheet.save(out_jpg, format="JPEG", quality=90)

    if not out_jpg.exists():
        raise RuntimeError(f"contact sheet: ffmpeg produced no file at {out_jpg}")
    return out_jpg


def extract_keyframes(
    video: Path,
    out_dir: Path,
    *,
    count: int = 8,
    width: int = 960,
) -> list[Path]:
    """Write `count` evenly-spaced full frames of `video` as
    `out_dir/kf_01.jpg ... kf_NN.jpg`. Returns the written paths in order.
    Existing kf_*.jpg in out_dir are removed first so a re-run never leaves
    stale frames from a longer previous video."""
    video = Path(video)
    if not video.exists():
        raise RuntimeError(f"keyframes: video does not exist: {video}")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    for old in out_dir.glob("kf_*.jpg"):
        old.unlink()

    duration = max(_probe_duration(video), 0.001)
    sample_fps = count / duration
    _run_ffmpeg(
        ["ffmpeg", "-y", "-i", str(video),
         "-vf", f"fps={sample_fps:.6f},scale={width}:-2",
         "-frames:v", str(count), "-q:v", "3",
         str(out_dir / "kf_%02d.jpg")],
        "keyframes")
    frames = sorted(out_dir.glob("kf_*.jpg"))
    if not frames:
        raise RuntimeError(f"keyframes: ffmpeg produced no frames in {out_dir}")
    return frames
