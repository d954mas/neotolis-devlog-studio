"""cache — atomic, content-addressable render cache.

OWNER: cli-agent.

v2 requirements (fixes v1's known risks):
- ATOMIC publish: temp file + os.replace; parallel workers racing on one
  key or a crash mid-copy must never leave a truncated MP4 as a hit.
- Engine hash AUTO-DERIVED from the dlstudio package source tree (glob
  all *.py under dlstudio/) — no manual _ENGINE_FILES list to forget.
- Key inputs: IRBeat (model_dump_json), Design, RenderOpts-equivalent
  flags, and identity (size + mtime) of every referenced asset path.
- Levels: beat MP4 now; chunk-PNG level may be added later.
"""
from __future__ import annotations

import hashlib
import os
import shutil
import time
from dataclasses import dataclass
from pathlib import Path

import dlstudio
from dlstudio.ir import IRBeat
from dlstudio.model import Design

CACHE_DIR = Path("data/finalize/.cache2")

# Override hook for tests/tooling: if set, takes precedence over CACHE_DIR.
# Kept separate from CACHE_DIR (rather than replacing it) so callers can
# still monkeypatch the CACHE_DIR module attribute directly if they prefer.
CACHE_DIR_ENV_VAR = "DLSTUDIO_CACHE_DIR"

_ENGINE_HASH_CACHE: str | None = None


def _cache_dir() -> Path:
    """Resolve the active cache directory: env var override > CACHE_DIR."""
    override = os.environ.get(CACHE_DIR_ENV_VAR)
    return Path(override) if override else CACHE_DIR


def _engine_hash() -> str:
    """SHA1 over every *.py file under the installed dlstudio package tree.

    Auto-derived (no manual file list) so any engine source change
    invalidates every cached render — the v1 `_ENGINE_FILES` omission bug
    class becomes structurally impossible. Memoized per process: the
    engine doesn't change mid-invocation.
    """
    global _ENGINE_HASH_CACHE
    if _ENGINE_HASH_CACHE is not None:
        return _ENGINE_HASH_CACHE
    pkg_dir = Path(dlstudio.__file__).resolve().parent
    files = sorted(pkg_dir.rglob("*.py"), key=lambda p: p.relative_to(pkg_dir).as_posix())
    h = hashlib.sha1()
    for path in files:
        rel = path.relative_to(pkg_dir).as_posix()
        h.update(rel.encode("utf-8"))
        h.update(path.read_bytes())
    _ENGINE_HASH_CACHE = h.hexdigest()
    return _ENGINE_HASH_CACHE


def _reset_engine_hash_cache() -> None:
    """Test hook: force `_engine_hash()` to recompute on next call."""
    global _ENGINE_HASH_CACHE
    _ENGINE_HASH_CACHE = None


def _asset_identity(path: str) -> str:
    """(size, mtime_ns) fingerprint for one referenced asset path.

    Missing files hash as the literal string "missing" so a file appearing
    or disappearing is itself a cache key dimension, not silently ignored.
    """
    try:
        st = os.stat(path)
    except OSError:
        return "missing"
    return f"{st.st_size}:{st.st_mtime_ns}"


def _walk_asset_paths(beat: IRBeat) -> list[str]:
    """Every filesystem path referenced by an IRBeat.

    Covers VO audio, the words JSON, background segment sources, and SFX
    sources. Overlay chunk visuals are not filesystem paths at the IR
    level (the PNG is produced at render time by render.raster from the
    beat/chunk data already folded into `beat.model_dump_json()`), so they
    are not walked here separately.
    """
    paths: list[str] = [beat.audio, beat.words_path]
    paths.extend(seg.src for seg in beat.segments)
    paths.extend(sfx.src for sfx in beat.sfx)
    return paths


def beat_key(beat: IRBeat, design: Design, *, quality: str, width: int | None, gpu: bool) -> str:
    """Stable content hash: changes iff the rendered beat would change.

    Hashes, in order: the auto-derived engine hash, the IRBeat itself
    (`model_dump_json`), the Design (`model_dump_json`), the render flags
    that affect output (quality/width/gpu), and the identity (size +
    mtime_ns, or "missing") of every asset path the beat references.
    """
    h = hashlib.sha1()
    h.update(f"engine={_engine_hash()}".encode("utf-8"))
    h.update(beat.model_dump_json().encode("utf-8"))
    h.update(design.model_dump_json().encode("utf-8"))
    h.update(f"quality={quality};width={width};gpu={gpu}".encode("utf-8"))
    for p in _walk_asset_paths(beat):
        h.update(p.encode("utf-8"))
        h.update(_asset_identity(p).encode("utf-8"))
    return h.hexdigest()


def _cache_path(key: str) -> Path:
    return _cache_dir() / f"{key}.mp4"


def has(key: str) -> bool:
    """Whether a cache entry exists for `key`, without copying it anywhere."""
    return _cache_path(key).exists()


def get(key: str, out_path: Path) -> bool:
    """Copy a cache hit to `out_path`. Returns True on hit, False on miss."""
    cp = _cache_path(key)
    if not cp.exists():
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cp, out_path)
    return True


def _atomic_replace(tmp: Path, cp: Path, *, retries: int = 8, delay: float = 0.03) -> None:
    """os.replace with a short retry-with-backoff.

    The replace itself is atomic on both POSIX and Windows, but on Windows
    two workers racing os.replace onto the *identical* destination can
    transiently see WinError 5 (Access is denied) / WinError 32 (sharing
    violation) while the other worker's replace is momentarily holding the
    destination handle mid-operation. Retrying rides out that transient
    contention; it never changes what ends up on disk (still whichever
    replace wins, fully formed).
    """
    last_exc: OSError | None = None
    for attempt in range(retries):
        try:
            os.replace(tmp, cp)
            return
        except OSError as e:
            last_exc = e
            if attempt < retries - 1:
                time.sleep(delay * (attempt + 1))
    assert last_exc is not None
    raise last_exc


def put(key: str, rendered_path: Path) -> None:
    """Atomically publish `rendered_path` into the cache under `key`.

    Copies to CACHE_DIR/<key>.tmp-<pid>, then os.replace()s it onto
    <key>.mp4. Parallel `-j N` workers racing on the same key, or a crash
    mid-copy, therefore never leave a truncated MP4 behind as a false hit.
    The temp file is removed on any failure.
    """
    cache_dir = _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    cp = cache_dir / f"{key}.mp4"
    tmp = cache_dir / f"{key}.tmp-{os.getpid()}"
    try:
        shutil.copyfile(rendered_path, tmp)
        _atomic_replace(tmp, cp)
    finally:
        if tmp.exists():
            tmp.unlink(missing_ok=True)


@dataclass(frozen=True)
class CacheInfo:
    entries: int
    total_bytes: int
    oldest_mtime: float | None
    newest_mtime: float | None


def info() -> CacheInfo:
    """Entry count + total size + mtime range. Mirrors v1 `cache_info()`."""
    cache_dir = _cache_dir()
    if not cache_dir.exists():
        return CacheInfo(entries=0, total_bytes=0, oldest_mtime=None, newest_mtime=None)
    files = list(cache_dir.glob("*.mp4"))
    if not files:
        return CacheInfo(entries=0, total_bytes=0, oldest_mtime=None, newest_mtime=None)
    mtimes = [f.stat().st_mtime for f in files]
    total = sum(f.stat().st_size for f in files)
    return CacheInfo(
        entries=len(files),
        total_bytes=total,
        oldest_mtime=min(mtimes),
        newest_mtime=max(mtimes),
    )


def prune(older_than_days: float) -> int:
    """Remove cache entries older than `older_than_days`. Returns count
    removed. Mirrors v1 `prune_cache()`."""
    if older_than_days < 0:
        raise ValueError("older_than_days must be >= 0")
    cache_dir = _cache_dir()
    if not cache_dir.exists():
        return 0
    cutoff = time.time() - older_than_days * 86400
    removed = 0
    for path in cache_dir.glob("*.mp4"):
        if path.stat().st_mtime < cutoff:
            path.unlink()
            removed += 1
    return removed
