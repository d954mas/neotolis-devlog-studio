# VQ-SAFE — Safe Zones and Readability

Titles, captions, and overlays do not collide with borders, accent lines,
device frames, face cam, or other UI edges, and remain readable against
their background. No code gate — judged from an actual frame extract.

## Use when

- Any overlay/plate/subtitle position, size, or `bg_opacity` change.
- Introducing a new aspect ratio/orientation (e.g. a vertical reel from a
  horizontal source).
- Part of the orchestrator's pre-ship regression checklist
  (`common/PIPELINE.md`) and the reel-specific
  `docs/CHECKLIST_VERTICAL_REEL.md`.

## Do not use for

- Full-bleed video/image segments with no overlay text at all.
- Motion/retention judgment on the background itself (route to VQ-MOTION).

## Check

- No overlap between text/captions and frame borders, device frames, face
  cam, or other UI elements, across the full window the overlay is on
  screen (not just its first frame).
- **Vertical 1080x1920 platform-chrome zones (Reels/TikTok/Shorts union;
  see `AGENTS.md` "Platform-safe zones"):** no overlay/caption inside the
  top ~220px (camera/search bars), bottom ~450px (caption + action rail —
  Instagram is the strictest), right ~140px (like/comment/share), or left
  ~60px. Caption/overlay vertical center sits at **y_ratio 0.66-0.78**
  (y ≈ 1272-1498px of 1920), keeping ≥370px clearance from the bottom edge
  — not the engine's legacy `position="bottom"` default, which places a
  band only ~44px from the true bottom on a 1080-wide vertical frame (see
  `common/dlstudio/src/dlstudio/render/raster/_content.py:209-210`) and
  reads as clipped on Instagram. Also confirm nothing load-bearing sits
  outside the centered **1080x1350** rectangle — Instagram's feed view
  crops every reel to 4:5 and silently cuts anything past that line.
  Evidence: `trolley3d` shipped with the legacy bottom default, the lead
  reported "не вижу текста внизу... как будто обрезалось" on Instagram,
  and the fix was an explicit `y_ratio=0.73` override per chunk.
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
- For any vertical reel: the actual `y_ratio` (or computed pixel center)
  used per overlay, stated against the 0.66-0.78 target, plus confirmation
  the band does not cross the 1080x1350 centered 4:5 line.

## Not enough

- "Looks safe" without an actual frame extract.
- Checking only the first frame of an overlay that animates or holds
  across a multi-second window.
- Confirming text fits the frame but not checking contrast/color against
  the target ranges.
- For a vertical reel, confirming text is "inside the 1080x1920 canvas"
  without checking it against the platform-chrome zones and the Instagram
  4:5 crop line above — a caption can be inside the full frame and still
  be clipped by every platform that matters.
