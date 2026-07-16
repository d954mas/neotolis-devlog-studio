# VQ-END — Deliberate Ending

The final video/reel ends on a deliberate outro, CTA, or clean landing
frame — not an accidental hard stop or an unresolved cut. No code gate —
judged from the actual last frame of the rendered output.

## Use when

- Any full video or reel final/upload render.
- Part of the orchestrator's pre-ship regression checklist
  (`common/PIPELINE.md`) and the reel gate in `AGENTS.md`.

## Do not use for

- Draft renders of individual beats mid-production, where the outro beat
  hasn't been reached/rendered yet.
- Mid-video beat transitions — this rule is specifically about the final
  frame of the whole piece.

## Check

- The last ~1 second holds on a deliberate frame: site/product/CTA shot,
  not a mid-motion hard cut or an accidental freeze.
- End cards get visible final-frame weight — text sized so it doesn't read
  as a footnote (outro plates commonly need a size bump vs. mid-video
  connector text).
- Ending favors the human over the metric when both are options (a
  speaker CTA shot outperforms the same CTA over a static city/graphic
  shot).
- Outro does not over-promise ("следующий девлог про X" creates a debt;
  "буду делиться" doesn't) and does not over-claim from raw
  wishlist/follower counts (state the number + gratitude, let the viewer
  do the math).
- Concat/render order actually lands on the intended outro beat — verify,
  don't assume `CONCAT_ORDER`/edit order is correct.

## Evidence required

- The actual last frame extracted (`ffmpeg -sseof` or equivalent) plus its
  timestamp and hold duration.
- Confirmation of which beat/chunk the tail is, cross-checked against the
  edit's intended concat order.

## Not enough

- "It ends fine" without extracting and looking at the actual last frame.
- Assuming the concat/order list is correct without watching the tail of
  the rendered file.
- Treating a clean render exit code as proof the ending lands as intended
  — a wrong concat order still exits 0.
