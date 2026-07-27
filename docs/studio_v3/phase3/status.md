# Studio v3 Phase 3 gate

Status: **PASS**

## What exists

- Authoring uses one small v3 DSL and an explicit `edit.py` path. It does not
  load asset revisions or migration evidence from author code.
- The application resolves current `AssetRevision` values from the asset
  repository and compiles them into canonical `TimelineIR`.
- `TimelineIR` contains resolved timing, geometry, media identity, audio,
  transitions, and immutable asset snapshots. A fresh process can validate and
  render it without importing authoring, workflow, adapters, or legacy code.
- Checks are the pure function
  `TimelineIR + CheckPolicy + ConstraintSet -> CheckReport`.
- Rendering uses FFmpeg only. Its cache key covers canonical IR, render options,
  renderer/runtime identity, and the FFmpeg binary/build identity.
- A cache hit verifies its small manifest and stable file metadata before
  copying the cached artifact. It does not rerun FFmpeg or read source media.

The cache deliberately has no HMAC or cache service hierarchy. Cache bytes are
rebuildable; release trust is established later from immutable objects and
exact hashes.

## Current evidence

- Canonical decode rejects missing or surplus asset snapshots.
- Render verifies the complete reachable asset evidence closure before cache
  lookup.
- Execution identity is freshly detected at the application/render boundary;
  stale caller-provided identity is rejected.
- Fresh-process render tests cover visual-only, mixed audio, transition,
  animation, cache-hit, and corrupt-object paths.
- Representative release tests cover vertical reel, long-form, and capture/VO
  flows through the same application path to an immutable delivery receipt.

Historical v2 outputs remain evidence bytes only. A legacy artifact that cannot
be bound to exact v3 asset approval, review, and release facts is archived
read-only rather than upgraded by assertion.

## Gate

Run:

```text
python -m pytest common/dlstudio/tests/test_v3_timeline_rendering.py -q
python -m pytest common/dlstudio/tests/test_v3_application_flow.py -q
python -m tools.studio_v3_verify --profile phase0 --scope static --skip-toolchain
```

The final cutover gate remains blocked until the real-workspace backup can read
every in-scope source byte.
