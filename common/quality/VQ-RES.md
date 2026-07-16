# VQ-RES — Resolution Sanity

Output resolution and per-asset upscale stay within encoder-safe bounds,
and the render width matches the current production stage.

**Enforced by engine (v2):** `dlstudio.check._check_resolution()` in
`common/dlstudio/src/dlstudio/check/__init__.py:107-131`, using constants
`_MAX_DIM = 4096` px/axis and `_MAX_UPSCALE = 2.2` (`check/__init__.py:34-35`).
It errors if the target resolution exceeds 4096px on either axis, or if any
full-bleed segment upscales more than 2.2x from its source dimensions — the
class of bug that produced a 3840×6826 x264 OOM in v1. Legacy v1 has no
such check.

## Use when

- Adding a new full-bleed video/image asset.
- Changing a target resolution or aspect ratio (e.g. new vertical reel
  design).
- Deciding which render width/quality tier to use for the current stage
  (draft/preview/upload).
- Working on a **legacy v1 edit**, where the engine gate doesn't exist —
  this becomes a fully manual check.

## Do not use for

- Judging visual composition/readability at a given resolution — that's
  VQ-SAFE (overlay placement) or VQ-MOTION (motion floor).
- Legacy v1 assets that already render successfully at their existing
  resolution with no new asset added.

## Check

- v2: `dl2 check` reports no `VQ-RES` error (engine-enforced part).
- v1: manually confirm no source asset needs more than ~2.2x upscale to
  fill the target frame, and target resolution stays within encoder-safe
  bounds — do this by hand since there's no code gate.
- The render width used matches the production stage: **540p draft**
  during iteration (`dl iter`/`dl2 iter`), **1080p preview** for
  mid-quality checks, **4K only at explicit final/upload** — per
  `AGENTS.md`, don't render at 4K during iteration (slower + separate cache
  entry).
- `dl assets --width 4k` / `dl2 assets` run before final render to surface
  low-resolution source warnings, not just missing files.

## Evidence required

- `dl check` / `dl2 check` output showing no `VQ-RES` error, or
- For v1/manual: the source asset's probed dimensions vs. target
  resolution and the computed upscale factor.
- The render command actually used, to confirm it matches the intended
  stage (draft vs. final).

## Not enough

- "Video looks sharp" without confirming no upscale-cap violation on the
  actual source dimensions.
- Running upload-width renders during iteration and calling it fine
  because it "looked ok" on one preview.
- Assuming a v1 asset that worked in a horizontal edit will scale cleanly
  into a new vertical reel without checking its native dimensions.
