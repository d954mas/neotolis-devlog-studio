# dlstudio Phase-1 follow-ups (integration seams)

Deferred items surfaced during the Phase-1 build (2026-07-16). None block
Phase 2; each is a bounded task.

## 1. Migrate compile/check diagnostics off warning-string regex — DONE 2026-07-16

compile (`compile/segments.py`'s `resolve_windows`/`build_segments`) now
appends structured `CheckIssue` objects to `Timeline.diagnostics` for the
VQ-WORDS out-of-range and VQ-OFFSET clamp cases, in addition to the existing
tagged strings in `Timeline.warnings` (human display only).
`check._promote_warnings` no longer regex-parses `warnings`; it merges
`timeline.diagnostics` directly (`_WARN_RE` and the regex path were
deleted — nothing else depended on it). Tests: `test_compile_windows.py`,
`test_compile_segments.py` (diagnostics assertions added), `test_check.py`,
`test_compile_timeline.py` (new structured-diagnostics tests).

## 2. Populate `AssetProbe.readable` — DONE 2026-07-16

`compile/probe.py` sets `readable=False` when a file exists but ffprobe
fails on it (nonzero rc or unparseable JSON), `readable=True` on a
successful probe, and leaves it `None` for kinds never ffprobed (fonts,
other) or missing files. `check._check_assets` reports a VQ-ASSET error for
exists-but-`readable is False` assets ("present but unreadable"), distinct
from the missing-asset error. Tests: `tests/test_compile_probe.py` (new;
monkeypatched-subprocess unit tests + `@pytest.mark.slow` real-ffprobe
corrupt-file tests), `test_check.py`.

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

## 5. `dl2 iter --stale` cache-hit-but-file-missing edge — DONE 2026-07-16

`cmd_iter` (`cli/__init__.py`) now restores a stale-skipped beat from cache
when its `beat_files[bid]` copy is missing on disk: for each beat with a
cache hit, if the file isn't already there it calls `dl_cache.get(key,
path)` before the trailing missing-rendered-beats check runs. Tests:
`test_cli.py::test_cmd_iter_stale_restores_missing_cached_beat_file` and
`::test_cmd_iter_stale_skips_restore_when_file_already_present` (no
redundant re-copy when the file is already present).

## 6. Phase-2 seams (by design, not debt)

- Full mix graph in `render/assemble.py` (music beds, sidechain ducking
  keyed by `*_vo_stem.wav`, SFX at word anchors, -14 LUFS loudnorm).
- Real beat-to-beat crossfades (re-encode at boundaries).
- Overlay PNG chunk-level cache keying.
