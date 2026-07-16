# VQ-SAFE — Safe Zones and Readability

Titles, captions, and overlays do not collide with borders, accent lines,
device frames, face cam, or other UI edges, and remain readable against
their background. No code gate — judged from an actual frame extract.

## Use when

- Any overlay/plate/subtitle position, size, or `bg_opacity` change.
- Introducing a new aspect ratio/orientation (e.g. a vertical reel from a
  horizontal source).
- Part of the orchestrator's pre-ship regression checklist
  (`common/PIPELINE.md`).

## Do not use for

- Full-bleed video/image segments with no overlay text at all.
- Motion/retention judgment on the background itself (route to VQ-MOTION).

## Check

- No overlap between text/captions and frame borders, device frames, face
  cam, or other UI elements, across the full window the overlay is on
  screen (not just its first frame).
- `bg_opacity` stays in the **0.28-0.35** sweet spot when text is the focal
  point (0.45 ghosts the text; 0.20 leaves the plate floating with no
  anchor). Only go above **0.40** when the background image itself is the
  message (e.g. an authentic product screenshot that needs to read as
  real).
- Vertical reels default to `sub_ratio >= 0.5` and keep subtitle lines
  short — mobile contrast on a dark background is unforgiving.
- Subtitle/headline color: gold subtitles at **96%**, full gold for
  headlines — anything below ~90% reads as grey on mobile.
- No `style: card` overlay on a `face: full` beat (it covers the speaker) —
  use a band overlay with `bg_opacity >= 0.35` for contrast instead.
- Plate text is CAPS, max 2 lines; 3-line takeaways need 150px+ and a
  tight `line_gap_ratio` (~0.04, not the ~0.15 default) or they fragment
  into separate ideas.

## Evidence required

- A frame extract at the chunk midpoint (and, for animated overlays, at
  least one more frame later in the window) showing the overlay fully
  inside frame bounds and legible against its background.
- The actual `bg_opacity`/`sub_ratio`/color values used, stated against the
  target ranges above.

## Not enough

- "Looks safe" without an actual frame extract.
- Checking only the first frame of an overlay that animates or holds
  across a multi-second window.
- Confirming text fits the frame but not checking contrast/color against
  the target ranges.
