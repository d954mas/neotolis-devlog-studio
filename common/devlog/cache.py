"""Content-addressable cache for rendered beats.

A rendered beat is a pure function of:
  - the Beat dataclass (chunks, text, scene refs)
  - the Design dataclass (resolution, fps, palette, tokens)
  - the mtime of every asset path referenced (audio, words, images, video)
  - draft / gpu flags
  - **the source code of the render engine itself** — if plate.py / overlay.py
    / image.py / compose.py / compose_ffmpeg.py / effects.py / text.py / types.py change, the
    cache key changes too, so engine improvements automatically invalidate
    stale renders. No manual `cache-clear` after pulling engine updates.

Store rendered MP4 under `data/finalize/.cache/<hash>.mp4`. On subsequent
calls just copy from cache. Editing one beat re-renders only that beat;
others stay cached (O(file copy)).

Cache is keyed by content, not filename, so different `--width` flags
produce different cache entries.

**Known gaps:**
- Font file *contents* are not hashed (path is). If you replace a TTF with
  the same path but different glyphs, cache won't notice. Run `dl cache-clear`.
- Internal-only chunk fields that don't appear in `asdict(beat)` are missed,
  but Chunk is a flat dataclass so this shouldn't happen in practice.
"""
from __future__ import annotations
import hashlib
import json
import os
import shutil
import time
from dataclasses import asdict
from dataclasses import dataclass
from pathlib import Path

from devlog.types import Beat, Design


CACHE_DIR = Path("data/finalize/.cache")


@dataclass(frozen=True)
class CacheInfo:
    entries: int
    total_bytes: int
    oldest_mtime: float | None
    newest_mtime: float | None

# Engine source files that affect render output. If any of these change,
# all cached entries are considered stale. Files not in this list (cli.py,
# audio/, web/, cache.py itself) don't affect render output.
_ENGINE_FILES = [
    "types.py",
    "render/plate.py",
    "render/overlay.py",
    "render/image.py",
    "render/compose.py",
    "render/compose_ffmpeg.py",
    "render/effects.py",
    "render/text.py",
]

_engine_hash_cache: str | None = None


def _engine_hash() -> str:
    """SHA1 of the render engine source bytes. Memoized — engine doesn't
    change during a single CLI invocation."""
    global _engine_hash_cache
    if _engine_hash_cache is not None:
        return _engine_hash_cache
    h = hashlib.sha1()
    base = Path(__file__).parent           # common/devlog/
    for rel in _ENGINE_FILES:
        p = base / rel
        if p.exists():
            h.update(rel.encode("utf-8"))
            h.update(p.read_bytes())
    _engine_hash_cache = h.hexdigest()[:12]
    return _engine_hash_cache


def _walk_asset_paths(beat: Beat) -> list[str]:
    """Collect every filesystem path referenced by the beat's chunks + scene."""
    paths = [beat.audio, beat.words]
    if beat.scene:
        paths.append(beat.scene.src)
    for ch in beat.chunks:
        if ch.src:
            paths.append(ch.src)
        if ch.bg_image:
            paths.append(ch.bg_image)
        if ch.scene:
            paths.append(ch.scene.src)
    return paths


def beat_hash(
    beat: Beat,
    design: Design,
    draft: bool = False,
    gpu: bool = False,
    quality: str | None = None,
) -> str:
    """Stable content hash that changes iff render output would change."""
    h = hashlib.sha1()
    # Engine source — invalidates everything when the renderer changes
    h.update(f"engine={_engine_hash()}".encode("utf-8"))
    # Beat spec — sort_keys keeps hash stable across dict insertion order
    h.update(json.dumps(asdict(beat), default=str, sort_keys=True).encode("utf-8"))
    # Design spec
    h.update(json.dumps(asdict(design), default=str, sort_keys=True).encode("utf-8"))
    # Render flags that affect output
    quality_key = quality or ("draft" if draft else "standard")
    h.update(f"draft={draft};gpu={gpu};quality={quality_key}".encode("utf-8"))
    # Asset mtimes — only existing paths; missing assets produce different hash too
    for p in _walk_asset_paths(beat):
        h.update(p.encode("utf-8"))
        try:
            h.update(str(os.path.getmtime(p)).encode("utf-8"))
        except OSError:
            h.update(b"missing")
    return h.hexdigest()[:16]


def cache_path(key: str) -> Path:
    return CACHE_DIR / f"{key}.mp4"


def get_cached(beat: Beat, design: Design, out_path: str,
               draft: bool = False, gpu: bool = False,
               quality: str | None = None) -> bool:
    """If a cached render exists, copy it to out_path and return True.

    Returns False on cache miss — caller should render normally and call
    `put_cached` to populate the cache.
    """
    key = beat_hash(beat, design, draft=draft, gpu=gpu, quality=quality)
    cp = cache_path(key)
    if cp.exists():
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(cp, out_path)
        print(f"[cache] hit {key} -> {out_path}")
        return True
    return False


def put_cached(beat: Beat, design: Design, out_path: str,
               draft: bool = False, gpu: bool = False,
               quality: str | None = None) -> None:
    """Save a successfully rendered file into the cache under its content hash."""
    key = beat_hash(beat, design, draft=draft, gpu=gpu, quality=quality)
    cp = cache_path(key)
    cp.parent.mkdir(parents=True, exist_ok=True)
    # Atomic publish: parallel workers (-j N) may race on the same key, and a
    # crash mid-copy must never leave a truncated MP4 behind as a false hit.
    tmp = cp.with_suffix(f".tmp-{os.getpid()}")
    try:
        shutil.copyfile(out_path, tmp)
        os.replace(tmp, cp)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)
    print(f"[cache] saved {key}")


def clear_cache() -> int:
    """Wipe the cache. Returns number of files removed."""
    if not CACHE_DIR.exists():
        return 0
    files = list(CACHE_DIR.glob("*.mp4"))
    for f in files:
        f.unlink()
    return len(files)


def cache_info() -> CacheInfo:
    if not CACHE_DIR.exists():
        return CacheInfo(entries=0, total_bytes=0, oldest_mtime=None, newest_mtime=None)
    files = list(CACHE_DIR.glob("*.mp4"))
    mtimes = [f.stat().st_mtime for f in files]
    total = sum(f.stat().st_size for f in files)
    return CacheInfo(
        entries=len(files),
        total_bytes=total,
        oldest_mtime=min(mtimes) if mtimes else None,
        newest_mtime=max(mtimes) if mtimes else None,
    )


def prune_cache(older_than_days: float) -> int:
    if older_than_days < 0:
        raise ValueError("older_than_days must be >= 0")
    if not CACHE_DIR.exists():
        return 0
    cutoff = time.time() - older_than_days * 86400
    removed = 0
    for path in CACHE_DIR.glob("*.mp4"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed
