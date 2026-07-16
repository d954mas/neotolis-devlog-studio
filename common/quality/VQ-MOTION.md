# VQ-MOTION — Static-Screenshot Floor

Continuous motion carries retention; a run of unmoving screenshot/UI reads
as a screen recording, not a video. No code gate exists — this is a visual
judgment call made from a contact sheet or extracted frames.

## Use when

- A beat's background is a screenshot, static product image, or UI capture
  — especially in reels/shorts, which are judged harsher per
  `common/PIPELINE.md`'s reel gate.
- Reviewing a full video or reel for retention risk before ship.
- Deciding whether a "proof" screenshot (see VQ-PROOF) needs Ken Burns,
  framing, or a moving surround instead of standing alone.

## Do not use for

- Punchline-only static text plates — `HIT_VIDEO_PRACTICES.md` explicitly
  scopes those as intentionally static ("static text plates are
  punchline-only"); don't flag a 1-2s plate hold as a motion violation.
- Beats where the screenshot's exact on-screen text must be read verbatim
  and stability is required for legibility (still keep the *surrounding*
  scene moving).

## Check

- No more than **~3 seconds** of unmoving screenshot/UI without motion in
  a reel (the motion floor from `AGENTS.md`/`HIT_VIDEO_PRACTICES.md`).
- Continuous-motion background stays under roughly **70% of runtime**
  overall — static plates are the punctuation, not the norm; three static
  plates in a row reads as a slideshow.
- No back-to-back beats reusing the same background image, and no
  identical back-to-back plates (viewer reads repeats as a render bug).
- If a screenshot must hold, it uses `Scene(..., ken_burns=True)` (1.0→
  1.10x zoom), a framed/inset card while the surrounding scene moves, or a
  crop/position change — not left bare.
- Charts/infographics that grow left-to-right get **≥1.5s** on screen
  after the grow completes before cutting, so the eye can read the final
  state.

## Evidence required

- A contact sheet (`dl reel-preview`) or `ffmpeg -vf "fps=1/5"` frame
  extraction with the longest static run measured in seconds and its
  timestamp range.
- For flagged beats: confirmation of which technique (Ken Burns / inset /
  crop change / new source) was applied, with a before/after frame.

## Not enough

- "Looks dynamic enough" without a contact sheet or frame timestamps.
- A reviewer verdict that doesn't state the longest static run in seconds.
- Checking one frame per beat and extrapolating motion for the whole beat
  duration.
