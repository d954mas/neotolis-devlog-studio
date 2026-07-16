"""Asset probing — ffprobe facts for every referenced path.

compile builds an AssetProbe for every path an Edit touches (VO audio, words
json, scene srcs, content srcs, plate bg_image, sfx, music, fonts). The IR
carries these facts so check/ and reviewer agents reason on ground truth
instead of re-deriving (or hallucinating) durations and resolutions.

Two modes, mirroring build_timeline(probe=...):
- probe=True  -> real ffprobe subprocess (list args, never shell).
- probe=False -> facts come from an injected {path: AssetProbe} dict; paths
  not injected fall back to a cheap Path.exists() check with no media facts.

`AssetProbe.readable` is populated for image/video/audio kinds when probe=True:
True on a successful ffprobe, False when the file exists but ffprobe fails on
it (nonzero exit or unparseable output) -- distinguishes present-but-broken
from missing (VQ-ASSET reports both, distinctly). Stays None for font/other
kinds (never ffprobed) and for missing files (existence already covers it).
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Literal

from dlstudio.ir import AssetProbe

Kind = Literal["image", "video", "audio", "font", "other"]

_AUDIO_EXT = {".wav", ".mp3", ".m4a", ".aac", ".flac", ".ogg", ".opus", ".wma"}
_VIDEO_EXT = {".mp4", ".mov", ".mkv", ".webm", ".avi", ".m4v"}
_IMAGE_EXT = {".png", ".jpg", ".jpeg", ".webp", ".bmp", ".tif", ".tiff", ".gif"}
_FONT_EXT = {".ttf", ".otf", ".ttc", ".woff", ".woff2"}


def classify(path: str) -> Kind:
    """Best-effort kind from file extension. Used only where the caller has no
    explicit kind (scenes/content carry their own)."""
    ext = Path(path).suffix.lower()
    if ext in _AUDIO_EXT:
        return "audio"
    if ext in _VIDEO_EXT:
        return "video"
    if ext in _IMAGE_EXT:
        return "image"
    if ext in _FONT_EXT:
        return "font"
    return "other"


def probe_asset(path: str, kind: Kind) -> AssetProbe:
    """Run ffprobe on one asset. Missing files return exists=False with no
    facts; font/other kinds only get an existence check (no ffprobe)."""
    p = Path(path)
    if not p.exists():
        return AssetProbe(path=path, kind=kind, exists=False)
    if kind in ("font", "other"):
        return AssetProbe(path=path, kind=kind, exists=True)
    return _ffprobe(path, kind)


def _ffprobe(path: str, kind: Kind) -> AssetProbe:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", path],
            capture_output=True, text=True,
        )
    except FileNotFoundError as e:  # pragma: no cover - ffprobe missing
        raise RuntimeError("ffprobe not found on PATH") from e

    if r.returncode != 0:
        # File exists but is unreadable/corrupt — report exists + readable=False
        # so VQ-ASSET can distinguish "there but broken" from "missing", with
        # no usable facts.
        return AssetProbe(path=path, kind=kind, exists=True, readable=False)

    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError:  # pragma: no cover - defensive
        return AssetProbe(path=path, kind=kind, exists=True, readable=False)

    streams = data.get("streams", [])
    fmt = data.get("format", {})

    duration: float | None = None
    dur_raw = fmt.get("duration")
    if dur_raw not in (None, "N/A"):
        try:
            duration = float(dur_raw)
        except (TypeError, ValueError):
            duration = None

    width = height = None
    for s in streams:
        if s.get("codec_type") == "video":
            width = _as_int(s.get("width"))
            height = _as_int(s.get("height"))
            break

    has_audio = any(s.get("codec_type") == "audio" for s in streams)

    # Still images report width/height but no meaningful duration.
    if kind == "image":
        duration = None

    return AssetProbe(
        path=path, kind=kind, exists=True, readable=True,
        duration=duration, width=width, height=height,
        has_audio=has_audio if kind in ("video", "audio") else None,
    )


def _as_int(v) -> int | None:
    try:
        return int(v)
    except (TypeError, ValueError):
        return None


def build_registry(
    paths: dict[str, Kind],
    *,
    probe: bool,
    injected: dict[str, AssetProbe] | None,
) -> dict[str, AssetProbe]:
    """Resolve {path: kind} into {path: AssetProbe}.

    probe=True:  ffprobe each path.
    probe=False: use `injected[path]` when present; otherwise a cheap
                 Path.exists() check with no media facts (lets tests inject
                 only the media probes they assert on and rely on real fixture
                 files existing for the rest).
    """
    injected = injected or {}
    out: dict[str, AssetProbe] = {}
    for path, kind in paths.items():
        if probe:
            out[path] = probe_asset(path, kind)
        elif path in injected:
            out[path] = injected[path]
        else:
            out[path] = AssetProbe(path=path, kind=kind, exists=Path(path).exists())
    return out
