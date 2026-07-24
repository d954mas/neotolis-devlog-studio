# VQ-TEMPORAL — Freeze and Capture Cadence

Rendered motion can look broken even when the container reports the expected
frame rate. A game may stop on one image for half a second, or a 30 fps file
may contain only 15 unique frames per second. Both need moving evidence; a
contact sheet cannot prove or disprove them.

## Use when

- A reel contains gameplay, screen capture, character animation, camera
  motion, or another shot expected to change every frame.
- Reviewing a final render after a report of freezes, stutter, or unpleasant
  character motion.
- Captured media has been retimed, converted, concatenated, or rendered at a
  frame rate different from its source.

## Do not use for

- Deliberate still cards, punchline holds, and ending holds declared as static
  in the shot manifest.
- A deliberately low-frame-rate style explicitly documented for review. The
  reviewer still checks whether the result is readable and intentional.

## Check

- Run `dl2 preflight <edit> --final --artifact <exact-mp4>` on the exact
  artifact intended for delivery.
- `VQ-FREEZE` reports near-identical whole-frame runs of at least 0.25s;
  runs of at least 0.40s block a final render until reviewed or fixed.
- `VQ-CADENCE` reports regularly repeated frames, such as 15 unique fps stored
  as 30 fps. A gross stepped cadence blocks a final render.
- Run `dl2 review-pack <edit> --artifact <exact-mp4>`. Review every MP4 listed
  under `compact_review.freeze_candidates` and
  `compact_review.cadence_candidates` before classifying the finding.
- Fix the earliest broken source in the chain: capture/game/render timing,
  then re-render. Do not use frame interpolation merely to silence the gate.

## Evidence required

- `data/review/preflight.json`, bound to the exact artifact under review.
- Short MP4 evidence clips in `data/review/freeze_candidates/` and/or
  `data/review/cadence_candidates/`.
- For a fix: before/after candidate metrics and a clean preflight on the new
  artifact.

## Not enough

- The container or timeline says “30 fps”. It may still repeat every frame.
- A static thumbnail or contact sheet.
- Looping the entire reel by eye without timestamps.
- Calling a detected pause intentional when the manifest does not declare it.
