"""Clip a time range from a video file, optionally reframing 16:9 → 9:16.

Used to quickly produce reels from a finished YouTube video without
re-rendering beats. For best quality (text doesn't get cropped, font sizes
sized for vertical), prefer rendering a dedicated reel edit instead.

Reframe modes:
  none         passthrough (just clip)
  crop_center  crop to 9:16 from the horizontal center of the frame
  blur_pad     scale content to width, fill top/bottom with blurred bg
  letterbox    contain in 9:16 with black bars (preserves geometry)

For now this is a thin ffmpeg wrapper. More sophisticated reframing
(face detection, smart crop) is future work.
"""
from __future__ import annotations
import subprocess
from pathlib import Path


def _parse_range(s: str) -> tuple[float, float]:
    """Accept '2:55-3:18' (mm:ss) or '175-198' (seconds) → (start_s, end_s)."""
    a, b = s.split("-", 1)
    def to_s(t: str) -> float:
        t = t.strip()
        if ":" in t:
            parts = t.split(":")
            if len(parts) == 2:
                m, s = parts
                return int(m) * 60 + float(s)
            elif len(parts) == 3:
                h, m, s = parts
                return int(h) * 3600 + int(m) * 60 + float(s)
        return float(t)
    return to_s(a), to_s(b)


def cut_range(
    video: str,
    range_spec: str,
    out_path: str,
    reframe: str = "none",
    target_w: int = 1080,
    target_h: int = 1920,
) -> None:
    """Clip [start, end] from `video` and write to `out_path`.

    If reframe is set, reframes from 16:9 source to (target_w x target_h)
    using the chosen strategy.
    """
    start, end = _parse_range(range_spec)
    dur = end - start
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    if reframe == "none":
        # Stream copy = fast, no re-encode
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", video,
               "-t", str(dur), "-c", "copy", out_path]
    elif reframe == "crop_center":
        # Crop centered 608x1080 from 1920x1080, scale to target
        vf = (f"crop=ih*{target_w}/{target_h}:ih,"
              f"scale={target_w}:{target_h}")
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", video,
               "-t", str(dur), "-vf", vf,
               "-c:v", "libx264", "-crf", "18", "-preset", "medium",
               "-c:a", "aac", "-b:a", "192k", out_path]
    elif reframe == "blur_pad":
        # Foreground: fit content to target width. Background: blurred fill.
        vf = (
            f"[0:v]split=2[fg][bg];"
            f"[bg]scale={target_w}:{target_h}:force_original_aspect_ratio=increase,"
            f"crop={target_w}:{target_h},gblur=sigma=30[bgblur];"
            f"[fg]scale={target_w}:-1[fgscaled];"
            f"[bgblur][fgscaled]overlay=(W-w)/2:(H-h)/2"
        )
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", video,
               "-t", str(dur), "-filter_complex", vf,
               "-c:v", "libx264", "-crf", "18", "-preset", "medium",
               "-c:a", "aac", "-b:a", "192k", out_path]
    elif reframe == "letterbox":
        vf = (f"scale={target_w}:{target_h}:force_original_aspect_ratio=decrease,"
              f"pad={target_w}:{target_h}:(ow-iw)/2:(oh-ih)/2:color=black")
        cmd = ["ffmpeg", "-y", "-ss", str(start), "-i", video,
               "-t", str(dur), "-vf", vf,
               "-c:v", "libx264", "-crf", "18", "-preset", "medium",
               "-c:a", "aac", "-b:a", "192k", out_path]
    else:
        raise ValueError(f"Unknown reframe mode: {reframe}")

    print(f"[devlog cut] {video} [{start:.1f}s, {end:.1f}s] → {out_path} (reframe={reframe})")
    subprocess.run(cmd, check=True)
    print(f"[devlog cut] done")
