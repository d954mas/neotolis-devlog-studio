"""Chunk-aware visual reviewer.

Walks every overlay/plate chunk in an edit, extracts the rendered frame at the
chunk's mid-point timestamp, and compares it against the would-be chunk PNG
(via the same pre-render path compose uses). Reports per-chunk PASS/FAIL.

Why this exists: the previous reviewer sampled at fps=1/5 (every 5s) which fell
between chunk boundaries — short overlays (3-7s) were systematically missed.
This one samples at meaningful points and verifies pixel fidelity in the band
region, which actually catches "overlay silently dropped" regressions.

CLI:
    dl review <edit> <video.mp4>           # report per-chunk verdict
    dl review <edit> <video.mp4> --strict  # exit 1 on any FAIL (for CI)
"""
from __future__ import annotations
import io
import json
import subprocess
import sys
import tempfile
from pathlib import Path
from dataclasses import dataclass

import numpy as np
from PIL import Image

from devlog.types import Beat, Chunk, Design

# Windows console defaults to cp1251 which can't print Cyrillic. Force UTF-8.
if sys.platform == "win32" and not isinstance(sys.stdout, io.TextIOWrapper):
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
elif sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ─── Chunk timestamp computation ──────────────────────────────────

def _audio_duration(path: str) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", path],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip())


@dataclass
class ChunkSpec:
    """One chunk's location in the concatenated video."""
    beat_id: str
    chunk_idx: int
    kind: str
    text: str
    t_video_start: float
    t_video_end: float
    t_video_mid: float
    chunk: Chunk
    beat: Beat


def compute_chunk_specs(edit) -> list[ChunkSpec]:
    """Walk all beats in edit.order, return mid-timestamps for every overlay/plate
    chunk in concatenated-video timeline."""
    specs = []
    beat_offset = 0.0
    for bid in edit.order:
        beat = edit.beats[bid]
        audio_dur = _audio_duration(beat.audio)
        words = json.loads(Path(beat.words).read_text(encoding="utf-8"))["words"]
        for ci, ch in enumerate(beat.chunks):
            if ch.kind not in ("overlay", "plate"):
                continue
            if not ch.text:
                continue
            w_start, w_end = ch.words
            w_end = min(w_end, len(words) - 1)
            t_start_local = words[w_start]["start"]
            t_end_local = words[w_end]["end"]
            t_video_start = beat_offset + t_start_local
            t_video_end = beat_offset + t_end_local
            specs.append(ChunkSpec(
                beat_id=bid, chunk_idx=ci, kind=ch.kind, text=ch.text,
                t_video_start=t_video_start,
                t_video_end=t_video_end,
                t_video_mid=(t_video_start + t_video_end) / 2,
                chunk=ch, beat=beat,
            ))
        beat_offset += audio_dur
    return specs


# ─── Frame extraction + chunk PNG rendering ────────────────────────

def extract_frame(video: str, t: float) -> np.ndarray:
    """Pull one RGB frame from video at time t. Returns HxWx3 uint8."""
    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
        out = f.name
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{t:.3f}", "-i", video,
             "-frames:v", "1", "-q:v", "2", out],
            capture_output=True, check=True,
        )
        return np.array(Image.open(out).convert("RGB"))
    finally:
        Path(out).unlink(missing_ok=True)


def render_chunk_png(ch: Chunk, design: Design) -> np.ndarray:
    """Run the same PIL pre-render compose uses. Returns HxWx4 uint8 (RGBA)
    for overlay; HxWx3 RGB for plate (we add alpha=255 to match shape)."""
    from devlog.render.plate import make_plate
    from devlog.render.overlay import make_overlay_badge
    if ch.kind == "overlay":
        rgba = make_overlay_badge(ch.text, design,
                                  subtitle=ch.subtitle,
                                  position=ch.position,
                                  style=ch.style)
        return rgba
    elif ch.kind == "plate":
        rgb = make_plate(ch, design)
        # Synthesize full-opacity alpha so detection treats whole frame as mask
        h, w = rgb.shape[:2]
        alpha = np.full((h, w, 1), 255, dtype=np.uint8)
        return np.concatenate([rgb, alpha], axis=2)
    raise ValueError(f"unsupported chunk kind: {ch.kind}")


# ─── Detection ─────────────────────────────────────────────────────

@dataclass
class Verdict:
    spec: ChunkSpec
    diff: float            # mean abs RGB diff over band region
    coverage: int          # # of band pixels inspected
    passed: bool


def detect_chunk_presence(frame: np.ndarray, chunk_png: np.ndarray,
                          threshold: float = 35.0) -> Verdict:
    """Compare rendered frame's band region against chunk PNG's band colors.

    Band region = chunk_png pixels where alpha > 200 (the actual band pixels,
    excluding fully-transparent margins). At mid-chunk fade is at peak (alpha=1
    multiplier), so the rendered band pixels should be ≈ chunk_png band pixels
    (± ~6% scene bleed-through from chunk PNG's own 240/255 alpha).

    Mean abs diff per channel:
    - < 35: PASS (overlay clearly present, fully composited)
    - >= 35: FAIL (scene showing through where band should be)
    """
    # Resize chunk_png to match frame if needed (frame may be from downscaled render)
    if chunk_png.shape[:2] != frame.shape[:2]:
        png_pil = Image.fromarray(chunk_png).resize(
            (frame.shape[1], frame.shape[0]), Image.LANCZOS
        )
        chunk_png = np.array(png_pil)
    mask = chunk_png[:, :, 3] > 200
    coverage = int(mask.sum())
    if coverage < 100:  # essentially-empty chunk PNG (shouldn't happen for real overlays)
        return Verdict(spec=None, diff=0.0, coverage=0, passed=True)
    frame_band = frame[mask].astype(np.int16)
    chunk_band = chunk_png[mask, :3].astype(np.int16)
    diff = np.abs(frame_band - chunk_band).mean()
    return Verdict(spec=None, diff=float(diff), coverage=coverage,
                   passed=diff < threshold)


# ─── Orchestration ─────────────────────────────────────────────────

def review_video(edit, video_path: str, threshold: float = 35.0,
                 verbose: bool = True) -> list[Verdict]:
    """Run chunk-aware review over a rendered video. Returns list of Verdicts."""
    specs = compute_chunk_specs(edit)
    verdicts: list[Verdict] = []
    fails = 0
    for s in specs:
        frame = extract_frame(video_path, s.t_video_mid)
        chunk_png = render_chunk_png(s.chunk, edit.design)
        v = detect_chunk_presence(frame, chunk_png, threshold=threshold)
        v.spec = s
        verdicts.append(v)
        if not v.passed:
            fails += 1
        if verbose:
            tag = "PASS" if v.passed else "FAIL"
            text = s.text.replace("\n", " / ")[:50]
            print(f"  [{tag}] {s.beat_id:<8} c{s.chunk_idx} {s.kind:<8} "
                  f"t={s.t_video_mid:6.2f}  diff={v.diff:5.1f}  {text}")
    if verbose:
        passed = len(verdicts) - fails
        print(f"\n  {passed}/{len(verdicts)} chunks rendered correctly "
              f"({fails} FAIL)" if fails else
              f"\n  {passed}/{len(verdicts)} chunks rendered correctly")
    return verdicts
