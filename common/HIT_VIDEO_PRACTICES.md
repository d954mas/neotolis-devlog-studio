# Hit Video Practices

Practical patterns distilled from real iteration on the trolley devlog.
Updated continuously as we run improve-loop cycles against finished videos.

Target: Kurzgesagt-style sci-pop — sticky hook, constant motion, clear
hierarchy, never boring. Within our pipeline (no animated characters, but
plates / overlays / scenes / crossfades / Ken Burns are available).

## How to use this file

When starting a new project (or new video), read this file first. It's a
checklist for `beats.py` design choices that empirically held up under
critic review. Don't repeat mistakes other projects already made.

Evidence: `data/review/iterations/LOG.md` (trolley iter87, 22 mechanical
iterations on top of a "needs polish" baseline).

---

## Validate after render

- **DO compare video/audio duration with `ffprobe` after every final render.**
  When ffmpeg-engine has a bug or a source asset is shorter than expected,
  the video stream silently truncates. iter22→iter35 of trolley loop:
  half the content was invisible for 13 iterations because audio=363s
  vs video=181s was missed. The user noticed before I did. **Rule: numbers
  don't lie, eyes do.**

## Sanity-check reviewer suggestions

- **DO verify any `Scene.src` or `offset` suggestion against the asset's
  actual duration.** Reviewer agents propose offsets that look plausible
  in a 30s segment timeline but don't account for source file length.
  iter23 of trolley: reviewer suggested trailer_final_30fps offset=22.0,
  but the trailer is 20s. ffmpeg silently rendered audio-only (no video),
  broke concat. **Fix: probe duration; clamp offset past EOF; warn.**

## Pacing

- **DO keep continuous-motion background under 70% of runtime.** Static
  text plates are punchline-only. Trolley iter_44 introduced scene+overlay
  (continuous gameplay/infographic bg under bottom-band labels) and that
  single change is what moved it from "slideshow" to "video". A run of
  three static plates in a row reads as a deck.
- **DO treat short-form screencast as guilty until proven useful.** In reels,
  a plain static product screenshot reads like a screen recording, not a
  story. Use live/hand-held monitor shots, product/game motion, meme/situation
  B-roll, or an animated generated asset when the visual does not need exact
  UI reading. If the screenshot is the proof, make it move with Ken Burns or
  frame it as an inset card while the surrounding scene moves.
- **AVOID more than ~3s of unmoving screenshot in a reel.** If text on the
  screenshot must be read, keep the screenshot stable but animate the
  background, labels, highlights, or neighboring elements. If text is not
  important, replacing the screenshot with a relevant meme/situation clip
  often loses no information because the VO carries the point.
- **DO end each beat on a new visual.** If two adjacent beats reuse the
  same bg image (e.g. a2-1 and b4 both used `files_breakdown.png`), the
  viewer feels stuck. Reviewer flags it even when it was intentional.
- **AVOID identical back-to-back plates.** iter_39 fix: two adjacent
  "ВСЁ НАПИСАЛ ИИ" plates → renamed second to "ПРИМИТИВЫ · НАПИСАЛ ИИ".
  Same text twice = viewer assumes a render bug.

## Visual hierarchy

- **DO scale climax plates physically larger than build plates.** Sweet
  spot: connectors 150-180px, build 200-280px, climax 320-420px (at 1080p).
  iter_1 bumped a2-3 takeaway from 110→150 because a 3-line takeaway at
  110px reads quieter than the connector text leading into it.
- **AVOID overshooting size on multi-line plates.** iter_4: finale
  "СПАСИБО" at 480px hit the margins and compressed the subtitle below
  unreadable. 420px is the ceiling for one-word plates with subtitle.
- **DO bump only the closer of a thesis arc.** iter_9: bumped a2-2 "ДАЖЕ
  БОЛЬШИЕ" from 340→380. Don't bump every plate in a sequence — relative
  size IS the hierarchy. Bumping everything flattens it.
- **DO give the final card visible final-frame weight.** iter_10: outro
  "ПРОДОЛЖЕНИЕ СЛЕДУЕТ" 220→260. End cards are seen for 2-3 seconds; small
  text feels like a footnote.

## Hook (first 5-8s)

- **DO make the goal obvious in the first second for reels.** The viewer
  should immediately know the product, problem, or situation from voice, not
  only from a text overlay. If the first sentence is just a feature tour,
  rewrite the VO before touching visual polish.
- **DO hook from the viewer's problem, not the author's interest.** "Я сделал
  дневник" is internal; "через неделю не помнишь, что продвигал" is
  viewer-facing. Reels need the latter first, then the product.
- **DO open on a number or a specific noun, not a category.** "Не ТРАМВАЙ.
  МАШИНА." or "0 СТРОК КОДА" outperform "О ЧЁМ ИГРА" because they create
  immediate informational tension.
- **AVOID center-card style on face-mode beats.** A `style: card`
  overlay covers the speaker's face. Reviewer suggested card three times
  during iter_6-10 batch; we declined twice because the underlying beat
  was `face: full`. Use a band overlay + higher `bg_opacity` (0.35+) for
  contrast instead.
- **DO let the speaker's eyes hit the lens before the first cut.** Face
  beats need 0.3-0.5s of held eye contact at the head of the clip to land
  as "real human address" rather than B-roll voice-over.
- **DO reject flat short-form VO early.** A technically clean take can still
  fail if it sounds uninterested. For reels, the VO should feel curious,
  amused, frustrated, or excited enough to justify watching; otherwise mark it
  as re-record before spending time on visuals.

## Transitions between scenes/chunks

- **DO crossfade between two adjacent face-mode beats, hard-cut into a
  plate.** Plates are designed as interrupts — a crossfade dilutes the
  punch. Face-to-face needs the crossfade or the head jumps.
- **DO let one infographic animation play to completion before cutting.**
  Iter_43-44 finding: charts that grow L→R need ≥1.5s on screen post-grow,
  or the eye doesn't have time to read the final bars. Cutting at the
  apex of the animation feels frantic.
- **AVOID swapping bg image mid-plate.** Plate visuals must be stable
  while the text reads. If you need movement under a plate, use
  `ken_burns: True` (1.0→1.10× zoom) — it adds motion without changing
  composition.

## Color and emphasis discipline

- **DO reserve red (`COL_RED`) for punchline accents only.** `red_underline`
  on every plate kills the device; use it on takeaways and number reveals.
  Trolley uses ~5 red moments in 4 minutes — enough to feel like a system,
  not so many it becomes noise.
- **DO keep `bg_opacity` in the 0.28-0.35 sweet spot when text is the
  focal point.** iter_3 found 0.45 ghosts the plate text; iter_8 found 0.20
  leaves the plate floating with no anchoring. Both extremes hurt.
- **AVOID `bg_opacity > 0.40` unless the bg IS the message.** Reserve high
  opacity for image-driven beats (e.g. a real itch.io screenshot that
  needs to read as authentic, not as backdrop).
- **DO use 96% gold for subtitles, full gold for headlines.** iter_38-40
  bumped `COL_GOLD_DIM` from 83%→90%→96% over three iterations. Mobile
  contrast on dark bg is brutal; anything below 90% reads as grey.

## Text content

- **DO write plate text in CAPS, max 2 lines.** 3-line takeaways need
  150px+ AND tight `line_gap_ratio` (0.04 not the default ~0.15) or they
  fragment into 3 separate ideas instead of one.
- **DO localize anglicisms.** "Sticky finger" → "ЛИПКИЙ ПАЛЕЦ". The
  English term is faster for you to type, but the viewer parses it 200ms
  slower than the native equivalent. Per-beat that's invisible; across
  a 4-min video it costs a re-watch.
- **AVOID overlay text that duplicates a header burned into the bg
  asset.** iter_5: workflow_diagram_anim has its own "КАК Я РАБОТАЮ"
  header → fought the overlay → swapped to neutral timeline animation.
  **Rule: bg assets must not contain text that competes with the
  overlay.** When generating a chart/infographic for use as a scene,
  strip its built-in title.
- **AVOID self-deprecation drama and fake tension** (e.g. "я почти
  ошибся"). Viewers reward honesty + facts; they punish theatrics.

## Information density / payoff

- **DO front-load the surprising number.** "$1000", "273 коммита",
  "30 000 строк". Numbers are the cheapest density payload — one plate,
  one second, full memorability.
- **DO use real artifact screenshots over generated illustrations.**
  Iter_43 swapped a generic "AI helped" plate for a real `git log`-derived
  chart of 273 commits. Authenticity > polish: viewers know the difference.
- **DO end on the human, not the metric.** The Telegram CTA shot of the
  speaker outperforms the same CTA over a city snapshot. People follow
  people, not channels.
- **AVOID promising next-video content in the outro.** "Buду делиться"
  works; "следующий девлог про X" creates a debt you may not pay.
- **AVOID over-claiming from wishlist/follower counts.** N wishlists ≠ N
  buyers. State the raw number + gratitude; let the viewer do the math.
