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

# Cache ENTRY FORMAT version, hashed into every beat_key (PLAN_STUDIO_V2
# этап 0, блок 2 — the SINGLE bump covering defects 0.1/0.2/0.6/0.10).
# Bumping it turns every pre-existing entry into a miss; cold renders right
# after a bump are expected, not a regression.
#   1: bare <key>.mp4 (video only; the VO stem desync class of 0.2)
#   2: <key>.mp4 + <key>.wav pair (MP4 + VO stem published/restored
#      together), design font files included in the identity hash (0.10)
ENTRY_FORMAT_VERSION = 2

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

    Covers VO audio, the words JSON, background segment sources, SFX sources,
    and every raster-input path an overlay reads (`IROverlayItem.asset_paths`,
    e.g. a Plate's bg_image). The overlay PNG itself is produced at render time
    by render.raster and is not a persisted path, but the SOURCE files the
    rasterizer reads are — so a bg_image edited on disk (same path, new bytes)
    changes the beat's cache key via its identity (size+mtime). The overlay's
    non-file content (text/style/decorations) is tracked separately by
    `IROverlayItem.content_hash`, which rides inside `beat.model_dump_json()`.
    """
    paths: list[str] = [beat.audio, beat.words_path]
    paths.extend(seg.src for seg in beat.segments)
    paths.extend(sfx.src for sfx in beat.sfx)
    for ov in beat.overlays:
        paths.extend(ov.asset_paths)
    return paths


def _design_font_paths(design: Design) -> list[str]:
    """Every font FILE the design references (main/bold/accent), in role
    order. Defect 0.10: the design JSON only carries the path STRINGS, so a
    font file replaced on disk under the same path never invalidated any
    beat — font file identity must feed the key exactly like bg_image does."""
    fonts = design.fonts
    return [p for p in (fonts.main, fonts.bold, fonts.accent) if p]


def beat_key(beat: IRBeat, design: Design, *, quality: str, width: int | None, gpu: bool) -> str:
    """Stable content hash: changes iff the rendered beat would change.

    Hashes, in order: the entry-format version, the auto-derived engine
    hash, the IRBeat itself (`model_dump_json`), the Design
    (`model_dump_json`), the render flags that affect output
    (quality/width/gpu), and the identity (size + mtime_ns, or "missing")
    of every asset path the beat references plus every design font file.
    """
    h = hashlib.sha1()
    h.update(f"entry_format={ENTRY_FORMAT_VERSION}".encode("utf-8"))
    h.update(f"engine={_engine_hash()}".encode("utf-8"))
    h.update(beat.model_dump_json().encode("utf-8"))
    h.update(design.model_dump_json().encode("utf-8"))
    h.update(f"quality={quality};width={width};gpu={gpu}".encode("utf-8"))
    for p in _walk_asset_paths(beat):
        h.update(p.encode("utf-8"))
        h.update(_asset_identity(p).encode("utf-8"))
    for p in _design_font_paths(design):
        h.update(f"font:{p}".encode("utf-8"))
        h.update(_asset_identity(p).encode("utf-8"))
    return h.hexdigest()


def _cache_path(key: str) -> Path:
    return _cache_dir() / f"{key}.mp4"


def _cache_stem_path(key: str) -> Path:
    """The VO stem half of an entry pair (entry format 2)."""
    return _cache_dir() / f"{key}.wav"


def vo_stem_sibling(mp4_path: Path) -> Path:
    """`render_beat` drops `<stem>_vo_stem.wav` next to each beat MP4 and
    assemble reads the same convention — this is that convention, shared so
    put/get publish and restore the pair the mix path will actually read."""
    mp4_path = Path(mp4_path)
    return mp4_path.with_name(mp4_path.stem + "_vo_stem.wav")


def has(key: str) -> bool:
    """Whether a COMPLETE cache entry (MP4 + VO stem pair) exists for `key`.
    A bare MP4 without its stem is not an entry (defect 0.2: video of render
    A must never assemble against audio of render B)."""
    return _cache_path(key).exists() and _cache_stem_path(key).exists()


def get(key: str, out_path: Path) -> bool:
    """Materialize a cache hit: copy the MP4 to `out_path` AND its VO stem
    to the `<out>_vo_stem.wav` sibling. Returns True on hit, False on miss.
    An incomplete entry (either half missing) is a miss and copies nothing."""
    cp = _cache_path(key)
    sp = _cache_stem_path(key)
    if not (cp.exists() and sp.exists()):
        return False
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(cp, out_path)
    shutil.copyfile(sp, vo_stem_sibling(out_path))
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
    """Atomically publish the (MP4, VO stem) pair into the cache under `key`.

    The stem is `rendered_path`'s `<stem>_vo_stem.wav` sibling (what
    render_beat writes). If that sibling is missing, NOTHING is published —
    an MP4-only entry would resurrect defect 0.2 (cache hit restores video A
    while a stale on-disk stem B feeds the mix).

    Each half copies to a `.tmp-<pid>` file then os.replace()s onto its
    final name, so parallel `-j N` workers racing on one key, or a crash
    mid-copy, never leave a truncated file behind as a hit. The stem is
    published FIRST: the MP4's appearance is what flips `has()` to True, and
    by then its pair is already in place. (Two racers interleaving halves is
    harmless: the stem is a byte-copy of the beat's input audio, which is
    part of the key — so all stems published under one key are identical.)
    Temp files are removed on any failure.
    """
    rendered_path = Path(rendered_path)
    stem_src = vo_stem_sibling(rendered_path)
    if not stem_src.exists():
        print(f"[cache] WARNING: not publishing {key}: VO stem missing next to "
              f"{rendered_path.name} (an MP4-only entry is not a valid pair)")
        return
    cache_dir = _cache_dir()
    cache_dir.mkdir(parents=True, exist_ok=True)
    for src, dst in ((stem_src, _cache_stem_path(key)),
                     (rendered_path, _cache_path(key))):
        tmp = cache_dir / f"{key}{dst.suffix}.tmp-{os.getpid()}"
        try:
            shutil.copyfile(src, tmp)
            _atomic_replace(tmp, dst)
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
    """Entry count + total size + mtime range. An entry is an MP4 (+ its
    stem pair file, counted into total_bytes). Mirrors v1 `cache_info()`."""
    cache_dir = _cache_dir()
    if not cache_dir.exists():
        return CacheInfo(entries=0, total_bytes=0, oldest_mtime=None, newest_mtime=None)
    files = list(cache_dir.glob("*.mp4"))
    if not files:
        return CacheInfo(entries=0, total_bytes=0, oldest_mtime=None, newest_mtime=None)
    mtimes = [f.stat().st_mtime for f in files]
    total = sum(f.stat().st_size for f in files)
    total += sum(f.stat().st_size for f in cache_dir.glob("*.wav"))
    return CacheInfo(
        entries=len(files),
        total_bytes=total,
        oldest_mtime=min(mtimes),
        newest_mtime=max(mtimes),
    )


def prune(older_than_days: float) -> int:
    """Remove cache entries older than `older_than_days`. Returns count of
    entries removed (an entry = MP4 + its stem pair file, removed together).
    Mirrors v1 `prune_cache()`."""
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
            path.with_suffix(".wav").unlink(missing_ok=True)
            removed += 1
    return removed
