# dlstudio Phase-1 follow-ups (integration seams)

Deferred items surfaced during the Phase-1 build (2026-07-16). None block
Phase 2; each is a bounded task.

## 1. Migrate compile/check diagnostics off warning-string regex

`Timeline.diagnostics: list[CheckIssue]` now exists in the IR (added at
integration). compile still records VQ-tagged strings into
`Timeline.warnings` and `check._promote_warnings` regex-parses them.
Migration: compile appends structured `CheckIssue` objects to
`diagnostics`; check merges them directly; `warnings` stays human-display
only. Owner: compile-agent scope (`compile/__init__.py`, `check/__init__.py`).

## 2. Populate `AssetProbe.readable`

Field exists (None = undetermined). `compile/probe.py` should set
`readable=False` when a file exists but ffprobe fails on it, and VQ-ASSET
should report present-but-broken assets distinctly from missing ones.

## 3. `rotate` anim prop

`render/beat.py` raises NotImplementedError for `Anim(prop="rotate")`.
Implement via ffmpeg `rotate=` with alpha-safe padding, or drop the prop
from the model if unused by real edits.

## 4. Decorations don't reflow content (v1 difference)

v1 reserved layout space for badges/cards inside the plate algorithm; v2
decorations composite over the finished raster. Watch the first real edits
for collisions (badge over short text); if it matters, add optional
`Layout` hints from content renderers to decoration passes
(`render/raster/_util.py` already has a `Layout` seam).

## 5. `dl2 iter --stale` cache-hit-but-file-missing edge

`--stale` skips beats whose cache key exists, then requires the MP4 on
disk. If the cache entry exists but the target file was deleted, iter
fails with "missing rendered beats" instead of restoring from cache via
`dl_cache.get`. Restore-on-skip would fix it.

## 6. Phase-2 seams (by design, not debt)

- Full mix graph in `render/assemble.py` (music beds, sidechain ducking
  keyed by `*_vo_stem.wav`, SFX at word anchors, -14 LUFS loudnorm).
- Real beat-to-beat crossfades (re-encode at boundaries).
- Overlay PNG chunk-level cache keying.
