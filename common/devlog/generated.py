"""Render generated infographic scenes to PNG or MP4 assets."""
from __future__ import annotations

import json
import subprocess
from collections.abc import Callable
from pathlib import Path
from typing import Any

import numpy as np
from PIL import Image

from devlog.types import Design


FrameFn = Callable[[float, Design], Image.Image | np.ndarray]


def _as_rgb_array(frame: Image.Image | np.ndarray, design: Design) -> np.ndarray:
    if isinstance(frame, Image.Image):
        img = frame.convert("RGB")
        if img.size != design.resolution:
            img = img.resize(design.resolution, Image.LANCZOS)
        arr = np.asarray(img, dtype=np.uint8)
    else:
        arr = np.asarray(frame, dtype=np.uint8)
        if arr.shape[:2] != (design.H, design.W):
            img = Image.fromarray(arr).convert("RGB").resize(design.resolution, Image.LANCZOS)
            arr = np.asarray(img, dtype=np.uint8)
        if arr.ndim == 3 and arr.shape[2] == 4:
            arr = np.asarray(Image.fromarray(arr).convert("RGB"), dtype=np.uint8)
    if arr.ndim != 3 or arr.shape[2] != 3:
        raise ValueError(f"Expected RGB frame, got array shape {arr.shape}")
    return np.ascontiguousarray(arr)


def render_png(frame_fn: FrameFn, out_path: str | Path, design: Design,
               t: float = 999.0) -> Path:
    """Render one representative frame as PNG."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    frame = _as_rgb_array(frame_fn(t, design), design)
    Image.fromarray(frame, "RGB").save(out)
    return out


def render_mp4(frame_fn: FrameFn, out_path: str | Path, design: Design,
               duration: float, fps: int | None = None, crf: int = 18) -> Path:
    """Render a time-based frame function to MP4 using ffmpeg rawvideo input."""
    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    fps = fps or design.fps
    frame_count = max(1, int(round(duration * fps)))
    cmd = [
        "ffmpeg", "-y", "-loglevel", "error",
        "-f", "rawvideo",
        "-vcodec", "rawvideo",
        "-pix_fmt", "rgb24",
        "-s", f"{design.W}x{design.H}",
        "-r", str(fps),
        "-i", "-",
        "-an",
        "-c:v", "libx264",
        "-crf", str(crf),
        "-pix_fmt", "yuv420p",
        str(out),
    ]
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=subprocess.PIPE)
    assert proc.stdin is not None
    try:
        for i in range(frame_count):
            t = i / fps
            proc.stdin.write(_as_rgb_array(frame_fn(t, design), design).tobytes())
    finally:
        proc.stdin.close()
    stderr = proc.stderr.read().decode("utf-8", errors="replace") if proc.stderr else ""
    rc = proc.wait()
    if rc != 0:
        debug = out.with_suffix(out.suffix + ".ffmpeg_error.txt")
        debug.write_text(stderr, encoding="utf-8")
        raise RuntimeError(f"ffmpeg failed while rendering {out} (rc={rc}). Debug: {debug}")
    return out


def load_json_spec(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def render_generated(spec: dict[str, Any], design: Design, out_path: str | Path,
                     *, fps: int | None = None) -> Path:
    """Render a JSON-like generated visual spec."""
    from devlog.charts import scene_from_spec

    scene = scene_from_spec(spec)
    out = Path(out_path)
    if out.suffix.lower() == ".png":
        return render_png(scene.frame, out, design, t=scene.duration)
    return render_mp4(scene.frame, out, design, duration=scene.duration,
                      fps=fps or scene.fps or design.fps, crf=scene.crf)
