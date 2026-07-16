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

M3: cross-invocation ffprobe memo. Without it, every CLI invocation reprobes
every referenced asset even on a full cache hit -- a 30-beat edit shells out
to ffprobe ~60 times just to confirm nothing changed. `probe_asset` now
consults an on-disk memo (data/finalize/.cache2/probe_memo.json, same dir the
render cache uses; override via DLSTUDIO_PROBE_MEMO) keyed by absolute path ->
{size, mtime_ns, probe fields}. Identical (size, mtime_ns) skips the
subprocess entirely; anything else re-probes and updates the memo. See
_memo_lookup/_memo_store/_save_memo below.
"""
from __future__ import annotations

import json
import os
import subprocess
import time
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
    facts; font/other kinds only get an existence check (no ffprobe).

    image/video/audio kinds consult the on-disk memo first: identical
    (size, mtime_ns) for this path returns the memoized AssetProbe without a
    subprocess; otherwise ffprobe runs and the memo is updated. Missing files
    are never memoized (a Path.exists() check above is already cheap)."""
    p = Path(path)
    if not p.exists():
        return AssetProbe(path=path, kind=kind, exists=False)
    if kind in ("font", "other"):
        return AssetProbe(path=path, kind=kind, exists=True)

    st = p.stat()
    abs_path = str(p.resolve())
    cached = _memo_lookup(path, abs_path, kind, st.st_size, st.st_mtime_ns)
    if cached is not None:
        return cached

    result = _ffprobe(path, kind)
    _memo_store(abs_path, st.st_size, st.st_mtime_ns, result)
    return result


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


# ─── probe memo (cross-invocation ffprobe cache) ───────────────────────────

MEMO_PATH = Path("data/finalize/.cache2/probe_memo.json")

# Override hook for tests/tooling: if set, takes precedence over MEMO_PATH.
# Kept separate from MEMO_PATH (rather than replacing it) so callers can
# still monkeypatch the MEMO_PATH module attribute directly if they prefer
# (mirrors dlstudio.cache.CACHE_DIR_ENV_VAR).
MEMO_PATH_ENV_VAR = "DLSTUDIO_PROBE_MEMO"

_MEMO_MAX_ENTRIES = 4096


def _memo_path() -> Path:
    """Resolve the active memo file path: env var override > MEMO_PATH."""
    override = os.environ.get(MEMO_PATH_ENV_VAR)
    return Path(override) if override else MEMO_PATH


def _load_memo() -> dict:
    """Read the on-disk memo. Tolerates a missing file, an unreadable file,
    or corrupt JSON by starting fresh -- a cold memo is a perf hit, never a
    crash."""
    path = _memo_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(raw)
    except json.JSONDecodeError:
        return {}
    return data if isinstance(data, dict) else {}


def _atomic_write_memo(path: Path, memo: dict, *, retries: int = 8, delay: float = 0.03) -> None:
    """temp file + os.replace, same atomic-publish pattern as dlstudio.cache.
    The retry-with-backoff rides out the same transient Windows contention
    (WinError 5/32) two writers racing os.replace onto one path can see."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.parent / f"{path.name}.tmp-{os.getpid()}"
    try:
        tmp.write_text(json.dumps(memo), encoding="utf-8")
        last_exc: OSError | None = None
        for attempt in range(retries):
            try:
                os.replace(tmp, path)
                return
            except OSError as e:  # pragma: no cover - Windows contention
                last_exc = e
                if attempt < retries - 1:
                    time.sleep(delay * (attempt + 1))
        assert last_exc is not None
        raise last_exc
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


def _save_memo(memo: dict) -> None:
    """Prune entries whose path no longer exists, cap growth at
    _MEMO_MAX_ENTRIES (dropping the oldest by insertion order), then publish
    atomically."""
    pruned = {k: v for k, v in memo.items() if Path(k).exists()}
    if len(pruned) > _MEMO_MAX_ENTRIES:
        pruned = dict(list(pruned.items())[-_MEMO_MAX_ENTRIES:])
    _atomic_write_memo(_memo_path(), pruned)


def _memo_lookup(path: str, abs_path: str, kind: Kind, size: int,
                 mtime_ns: int) -> AssetProbe | None:
    """Return the memoized AssetProbe iff (size, mtime_ns) still match --
    the caller's `path` string (which may differ run-to-run even for the
    same file, e.g. relative vs absolute) always wins over whatever was
    stored, so the returned AssetProbe.path matches what the caller passed."""
    entry = _load_memo().get(abs_path)
    if not isinstance(entry, dict):
        return None
    if entry.get("size") != size or entry.get("mtime_ns") != mtime_ns:
        return None
    probe_data = entry.get("probe")
    if not isinstance(probe_data, dict):
        return None
    try:
        asset = AssetProbe(**{**probe_data, "path": path})
    except Exception:
        return None
    if asset.kind != kind:
        return None
    return asset


def _memo_store(abs_path: str, size: int, mtime_ns: int, probe: AssetProbe) -> None:
    """Memoize a successful probe or a stable readable=False result (both
    hold for as long as size+mtime_ns don't change). Never called for
    missing files -- probe_asset returns before reaching here."""
    memo = _load_memo()
    memo[abs_path] = {"size": size, "mtime_ns": mtime_ns, "probe": probe.model_dump()}
    _save_memo(memo)


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
