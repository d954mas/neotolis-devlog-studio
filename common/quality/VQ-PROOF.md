# VQ-PROOF — Real Product Visuals

Website/app/game visuals that claim to show the real product are backed by
an actual capture, not an invented or generated mockup. No code gate — this
is a provenance/authenticity judgment on top of VQ-ASSET's existence check.

## Use when

- A beat's visual claims to show the actual product, site, or game (not
  openly stylized b-roll).
- Thumbnail/cover packaging (`thumbnail-designer` scope) that combines AI
  art with a product screenshot.
- Part of the orchestrator's pre-ship regression checklist ("real product
  proof") in `common/PIPELINE.md`.

## Do not use for

- Openly stylized illustrative b-roll, meme clips, or generated
  infographics that don't claim to be the real product.
- Whether the referenced file exists/is readable at all — that's VQ-ASSET.

## Check

- The visual traces to an actual capture (screenshot, screen recording,
  live/hand-held monitor shot) of the real product/site/game, not an
  AI-generated illustration standing in for it.
- Prefer real artifact screenshots over generated illustrations when both
  could work (e.g. a real `git log`-derived commit chart over a generic
  "AI helped" plate) — authenticity reads differently to viewers than
  polish.
- Generated charts/infographics used as background assets must not carry
  their own burned-in header/title text that competes with the overlay
  (strip built-in titles before use as a `Scene`).
- Thumbnails combining AI art with a real screenshot: the real-product
  portion must be an actual capture, correctly composited, not implied.

## Evidence required

- The source capture's path/provenance (e.g. under `data/screens/`,
  `data/reels/live_capture/`, or a named recording) linking the on-screen
  visual back to a real capture event.
- For thumbnails: the specific screenshot file used and where it was
  captured from.

## Not enough

- "Looks realistic" without checking whether the image is generated or
  captured.
- Reviewer approval of visual quality that doesn't separately confirm
  authenticity/provenance.
- Reusing a placeholder/generated asset past the draft stage without
  swapping in the real capture once available.
