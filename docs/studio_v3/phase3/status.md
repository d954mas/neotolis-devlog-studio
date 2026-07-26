# Studio v3 Phase 3 gate

Status: **PASS**

## Implemented contracts

- The v3 authoring DSL has no v2 constructors or readers.
- `TimelineIR` is canonical and self-contained. Every reachable snapshot embeds
  the complete immutable `AssetRevision`; its `AssetRevisionRef` is recomputed
  from provenance, approval, license, media facts, and blob identity.
- The snapshot set is exactly equal to graph reachability: missing and surplus
  snapshots are both rejected by canonical decode.
- Raster/media/text, exact resolved crop/pad geometry, source offsets,
  loop/freeze behavior, Ken Burns and editorial transition intent,
  general x/y/scale/opacity/rotate animations on non-base raster/media layers,
  VO/music/SFX roles, fades,
  ducking, and loudness policy are serializable.
- The base visual track uses native FFmpeg `xfade`/`concat` operators for
  `fade`, `fadeblack`, `slideleft`, and `slideright`; it does not simulate a
  crossfade by fading an incoming layer over the background.
- Non-overlapping beat-boundary fades are separate post-composite
  `VideoFadeInstruction` values. They replay as interval-scoped black alpha
  overlays, so they fade the complete raster/overlay/caption result without
  changing absolute duration.
- Checks are a pure `TimelineIR + CheckPolicy -> CheckReport` function.
- Rendering imports no authoring/application/workflow/adapters code and works in
  a fresh process from IR plus immutable objects.
- Cache identity covers the complete timeline, renderer/raster sources, full
  FFmpeg build report and binary hash, runtime/platform, and render options.
  Cache entries use a per-key kernel lease, immutable content-hash object,
  atomic HMAC-authenticated manifest, and size/mtime/kernel-change-token
  postconditions; warm hits do not hash the media payload.

## Representative equivalence

Frozen semantic baselines from isolated renders of the current v2 graph:

- `vertical_legacy_baseline.json`: 17.52 s, 1 media segment, 5 captions,
  exact VO and music graph.
- `longform_legacy_baseline.json`: 243.27025 s, 9 beats, 28 media segments,
  3 overlays, 9 timing/VO tracks, and music.
- `capture_vo_legacy_baseline.json`: 144.76 s, 7 beats, 31 media segments,
  23 overlays / 31 public text items, 7 VO tracks, and music.

The one-shot port compiler pre-rasterizes each legacy overlay/caption through
the old deterministic PIL rasterizer. Every resulting RGBA PNG is a separate
`AssetRevision` bound to a SHA-256 source receipt; v3 runtime imports no legacy
rasterizer or global resolver. The baseline retains original content/style,
geometry, decoration, animation, transition, and raster hashes.

`representative_e2e.json` is produced only after exact BlobRef-set, graph,
resolved geometry, source-offset, loop/Ken-Burns, native transition, raster,
VO, music fade/duck, full-track fade, mix-policy, perceptual frames including
every output frame of every native-xfade and VideoFade interval, loudness,
true-peak, and temporally aligned PCM-correlation checks pass. Transition
comparison is presentation-timestamp based and performs no visual alignment
search. It permits at most a 2% explicit legacy PTS-discontinuity outlier
budget while requiring at least 50% strong frame matches; all non-transition
evidence remains outlier-free. Every visually observable transition group also
has exact before/after guard frames and must beat a synthetic hard cut built
from immutable frozen reference guards across every possible single-cut
boundary; rendered guards cannot poison the oracle. A separate aggregate guard
fidelity gate blocks systematic flashes/repeats, and mutation-negative tests
prove that declared transitions rendered as cuts are rejected. The three
artifacts render in fresh processes from canonical IR; stream presence alone
is not accepted.

Older final MP4s remain untouched historical evidence. They are not treated as
the current graph when their provenance cannot establish that claim. The
migration-only tool instead renders the current v2 graph into isolated,
hash-frozen reference artifacts before compiling v3; this follows the
archive-don't-invent rule while still making rendered transition equivalence a
hard gate. The references are generated outputs and are not committed.

## Local verification

- Focused Phase 3 timeline/render suite: 26 passed.
- Foundation/assets/migration contracts: 57 passed.
- Full dlstudio regression suite: 1078 passed, 4 skipped.
- Static architecture, banned-surface, canonical-vector, and performance
  contracts: PASS. The local aggregate wrapper reports only the expected
  environment mismatch (installed Node 24 versus CI-locked Node 22).
- Full representative fresh-process render: PASS.
  - vertical: 4,956,261 bytes, PCM correlation 0.999802, 0 transition frames;
  - long-form: 174,864,234 bytes, PCM correlation 0.999844,
    184/184 transition frames checked, 128 strong, 3 outliers (budget 4),
    17 frozen-reference-observable anti-cut groups passed, guard fidelity
    41/54 strong (mean MAE 33.2036, max 193.5838);
  - capture/VO: 136,151,286 bytes, PCM correlation 0.999832,
    100/100 transition frames checked, 86 strong, 0 outliers (budget 2),
    14 frozen-reference-observable anti-cut groups passed, guard fidelity
    23/24 strong (mean MAE 15.9668, max 59.3798).
- `git diff --check`: PASS.
- Independent final architecture review: PASS.
- Independent final adversarial verification: PASS. Exhaustive hard-cut
  mutations found 0 escapes across 468 capture/VO and 876 long-form cases.

The one-shot `tools/studio_v3_port_legacy.py` is migration-only and outside the
runtime package. Generated ports import only Studio v3 contracts. It must be
removed or archived at destructive cutover.
