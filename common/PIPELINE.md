# Devlog Pipeline — Orchestrator Instructions

This is the playbook for the **orchestrator** (Claude) when the user writes
free-form requests about a devlog video. The user describes intent; the
orchestrator picks the right action(s) and runs them. Two agents handle
focused review work: `vo-reviewer` (voice takes) and `video-reviewer`
(rendered beats + full video + plan).

> **v1/v2 note (2026-07-17):** the CLI commands below (`dl compose`,
> `dl render`, `dl reel-preview`, `dl cut`, `dl audio`, ...) are the
> **legacy v1** surface. All new production work uses **v2** (`dl2`) per
> `AGENTS.md` and `.claude/skills/dl-make-video/SKILL.md` — command names
> differ (`dl2 preview` replaces `dl reel-preview`, `dl2 final` replaces
> `dl render --final`, etc.). The *process* on this page — improve-loop
> shape, reviewer isolation, regression checklist, reel gate — is still
> the intended v2 process; only the exact command strings are stale and
> need a full pass. Until that migration lands, treat every `dl ...`
> command on this page as "the v2 equivalent from `AGENTS.md`'s defaults
> table", not as copy-pasteable. The reel gate below has a v2-accurate,
> maintained twin: `docs/CHECKLIST_VERTICAL_REEL.md`.

---

## How to read user input

The user writes in free form. Map their intent to one of these actions:

| User says | Action |
|---|---|
| "оцени запись", "проверь take", "посмотри запись" | Spawn `vo-reviewer` on the latest matching `.webm` |
| "посмотри бит X", "разбор b4", "что с битом" | Spawn `video-reviewer` on `data/finalize/<bid>_video_*.mp4` |
| "разбор iter", "посмотри финал", "что с видео" | Spawn `video-reviewer` on latest `iter*.mp4` |
| "разбери план X", "что в beats.py для X" | Spawn `video-reviewer` plan mode (no render) |
| "thumbnail", "обложка", "иконка для ролика", "картинка для YouTube" | Spawn `thumbnail-designer` and use `devlog-thumbnail` |
| "улучши X", "доведи X до ship", "make it better" | **Run improve loop** (see below) |
| "сделай быстрый рендер", "draft X" | `dl compose <edit> <bid> --width 540p --draft` |
| "финальный рендер", "render final" | `dl render <edit> --width 4k` (or 1080p if explicit) |
| "сделай рилс из X" | `dl cut <video> <range> --reframe crop_center --out reels/...` |
| "поправь рилс", "рилс непонятный/мелкий/скучный" | Run the reel story gate, then `dl reel-preview <edit>` before upload render |
| "запиши новый бит", "после записи" | Run `dl audio <edit> <bid> <file>` then spawn `vo-reviewer` |

If intent is unclear, **ask one short question** before acting.

For a new reel/short request, prioritize a watchable draft over source research:
scaffold the edit, write a provisional script, generate scratch TTS/word timings,
build available or generated visuals, and run `dl reel-preview`. Timebox website
capture, auth debugging, and exact data validation; if they block, mark them as
second-pass replacement work instead of delaying the first draft.

---

## The Improve Loop

This is the headline workflow. The user says "улучши <thing>" or equivalent,
and the orchestrator runs:

```
1. Render at 540p draft (if not already)
2. Spawn video-reviewer on the result
3. Reviewer returns ranked suggestions tagged: mech | re-record | re-design
4. Auto-apply all `mech` suggestions ≥ med severity (edit beats.py)
5. Re-render affected beats at 540p draft (use --parallel)
6. Spawn video-reviewer again
7. Loop from step 3 until:
   - Reviewer says "ship" or only `low` severity left, OR
   - Hit iteration cap (5 by default), OR
   - User interrupts
8. Report final state + any re-record / re-design items that need user input
```

After the blind review, run the orchestrator regression checklist before calling anything "ship". This pass may use prior user corrections because it is not the critic's independent verdict.

### Mechanical fixes the orchestrator may apply WITHOUT asking
- Plate `size` change (number → number)
- `bg_opacity` change (float → float)
- `subtitle_color` swap (palette token → palette token)
- `red_underline`, `ken_burns` flag toggles
- `position` ∈ {bottom, top, middle}
- `style` ∈ {band, card, hero}
- `fit` ∈ {cover, contain}
- Image source swap, **only if the new path exists in `data/`** — never invent
- Text typo fixes (clear typos only, not rewording)
- `line_gap_ratio`, `sub_ratio` numeric adjustments

### Fixes that REQUIRE user confirmation
- Any VO change (re-record needed)
- New asset that doesn't exist yet (generate? source? user picks)
- Structural changes: split/merge chunks, new chunk, new beat
- Word-index re-mapping (chunk timing shifts)
- Anything that affects more than one beat at once

When stuck on these, **stop the loop** and report the suggestion to the user.

### Iteration cap rationale
Five iterations × 30s renders per loop = 2.5min of compute per beat. If
that didn't converge, something deeper is wrong — show the state to the user.

---

## Render commands cheat-sheet

```powershell
# Fast iteration (use during improve loop) — cache makes unchanged beats ~instant
dl check <edit>
dl iter <edit> -j 6

# If devlog.toml has default_edit/render defaults, the short form is preferred:
dl check
dl iter
dl iter --stale
dl render
dl compose <bid>
dl watch --beat <bid>

# Deeper preflight when scene offsets/assets changed
dl check <edit> --deep

# Quick project status
dl doctor
dl beats <edit> --missing-only
dl stale <edit> --width 540p --quality draft
dl assets <edit> --width 4k
dl cache-info
dl script <edit>
dl shotlist <edit>
dl import-script script.md --out edits/youtube/beats.py
dl new-video newproject --script script.md
dl smoke --skip-tests

# Mid-quality preview
dl render <edit> --width 1080p --quality preview -j 4

# Fast reel/short preview: draft render + contact sheet + chunk keyframes
dl reel-preview <edit>

# Final delivery
dl render <edit> --quality upload             # explicit upload preset
dl render --final                             # final preset + preflight from devlog.toml
dl final <edit>                               # same final path, shorter
dl render <edit> --width 4k --quality upload --gpu
dl render <edit> --width 4k --quality master  # slower archival/high-quality render

# Single beat (after applying a fix)
dl compose <edit> <bid> --width 540p --draft

# Auto-rebuild on save (cache makes incremental rebuilds fast)
dl watch <edit>                        # default 540p draft, --j 4

# Wipe cache (rarely needed — hash auto-invalidates on inputs)
dl cache-clear <edit>

# Audio pipeline (after a new recording)
dl audio <edit> <bid> <recording_filename> --language ru --model medium

# Clip + reframe (for reels)
dl cut data/finalize/iter86.mp4 2:55-3:18 --reframe crop_center \
       --out data/reels/wave_moment.mp4

# Web tools (recorder + studio + feedback at /devlog/studio.html)
dl serve <edit>
```

`<edit>` is the dotted module path, e.g. `trolley.edits.youtube`.

**Cache:** every render is keyed by content hash (beat + design + asset mtimes
+ flags). Second run with no changes = ~0.4s (file copy). Edit a chunk →
that beat's hash changes → re-render; other beats stay cached.

---

## When to spawn which agent

### Reviewer isolation

Reviewer agents (`vo-reviewer`, `video-reviewer`, `thumbnail-designer` in review mode) should receive only the artifact and neutral task context needed to evaluate it. Do not pass the last 10-20 user corrections into the critic by default. The point of the critic is an independent read.

Prior user corrections belong to the orchestrator's regression checklist after the blind review. Run it as a separate pass: "does the new output still violate known user constraints?" Keep that separate from the critic's verdict.

### Orchestrator regression checklist

Run this after reviewer output and before final handoff:

- **Audio/music:** background music exists when requested, is audible but not distracting, and attribution is available when needed.
- **VO joins:** no abrupt phrase cut at beat boundaries or edited joins; inspect user-reported timestamps if any.
- **Visual glitches:** no one-frame/one-second wrong visual flashes, stale screenshot flashes, or transition pops in the final render.
- **Readability/safe zones:** titles, captions, and overlays do not collide with borders, accent lines, device frames, or UI edges. For vertical reels, check against the numeric platform-chrome zones and Instagram 4:5 crop line in `common/quality/VQ-SAFE.md` and `docs/CHECKLIST_VERTICAL_REEL.md` — "inside the 1080x1920 canvas" is not the same as "inside what any platform actually shows."
- **Real product proof:** website/app/game thumbnails and promo shots use real captured visuals, not invented UI.
- **Thumbnail:** if packaging for YouTube, use `thumbnail-designer` plus `devlog-thumbnail` contact-sheet QA.
- **Ending:** final video has a deliberate outro/end card or clean landing frame, not an accidental hard stop.

### Reel / short-form gate

Run this before rendering an upload-quality reel:

- **Visual draft first:** when creating a new reel, do not begin with open-ended website research, auth debugging, or exact-data validation. First create a provisional script/edit, generate scratch TTS and word timings, build usable visual placeholders or available real assets, and run `dl reel-preview`. If product capture or data access blocks, mark it as second-pass replacement work and keep the draft moving.
- **Goal in the first second:** the opening voice line must name the situation, problem, or product. If the viewer cannot answer "what is this about?" after one second, rewrite or re-record before rendering.
- **Hook for the viewer:** start from a problem, contradiction, funny situation, concrete number, or visible failure. Do not lead with a neutral feature tour or with what the author personally finds interesting.
- **Voice energy:** delivery should sound interested and conversational. If the take is flat or "read on autopilot", treat it as `re-record`, even if the words and visuals are technically correct.
- **Voice context first:** the opening voice line names the product or problem. Do not rely on a text overlay to explain what the reel is about.
- **Standalone story:** the reel must make sense without the previous reel. Avoid starting with "а", "можно", "теперь" unless context was already stated in voice.
- **Screencast is weak by default:** raw static screencast should not carry the reel. Prefer live/hand-held monitor shots, product/game motion, meme/situation B-roll, or generated motion assets. If a screenshot is necessary, make it a framed/inset object or add `Scene(..., ken_burns=True)` and keep something else moving.
- **Motion floor:** no more than about 3 seconds of static screenshot without motion; repeated UI frames need either a new crop/zoom/position or a new visual source.
- **Short overlay copy:** main text should be one strong idea; subtitles must be readable on phone. For vertical reels, default to `sub_ratio >= 0.5` and keep yellow lines short.
- **Deliberate ending:** include a final hold with site/product/CTA, usually about one second.
- **Cheap preview first:** use `dl2 preview <edit>` (v2) / `dl reel-preview <edit>` (v1) to inspect contact sheet and chunk keyframes. Only run 1080/upload after this passes. **This step is not optional under a deadline** — it is one command and costs about the same as the final render itself; see `docs/CHECKLIST_VERTICAL_REEL.md` for the full pre-publish gate (platform-safe zones, VQ-RES anti-bypass rule, transcript token check) that a `trolley3d` reel shipped without in 2026-07-17, catchable only because the lead happened to look at it after publish.
- **Render serially:** do not run upload renders for two different reel edits in parallel. They share `data/finalize/main_*` and `_concat.txt`; parallel final renders can corrupt or overwrite intermediate concat inputs.

If a checklist item fails, fix it or report it as open. Do not hide it behind a reviewer "ship" verdict.

### `vo-reviewer` — spawn when:
- User just recorded a take and asks for review
- User uploaded a new `.webm` and wants verdict
- Workflow phase: **after recording, before render**

**Don't spawn for:** composed beats, full videos, beats.py plan questions.

### `video-reviewer` — spawn when:
- A beat or full video has been rendered and user asks for review
- User wants improvement suggestions for visuals or pacing
- User asks "what to improve" or "is this ready to ship"
- User changed beats.py and wants plan-level critique before rendering

**Don't spawn for:** raw audio take quality; YouTube thumbnails or cover art.

### `thumbnail-designer` — spawn when:
- User asks for a YouTube thumbnail, cover image, or "icon for the video"
- User wants AI art combined with a real product/site screenshot
- User asks whether the thumbnail is readable, clickable, or uses the real product correctly
- Packaging phase needs a thumbnail before upload

**Don't spawn for:** composed video pacing, raw VO, or internal motion graphics unless they are being used as thumbnail source material.

### Parallel reviews
If user has both new audio AND new render, spawn both agents in **one
message with two tool calls** — they're independent.

---

## Stop conditions for the loop

The improve loop terminates when **any** of:

1. **Reviewer says "ship"** in the TL;DR
2. Only `low` severity items remain (cosmetic polish, not retention-affecting)
3. All remaining suggestions are tagged `re-record` or `re-design` (need user)
4. **5 iterations reached** (safety cap — something deeper is wrong)
5. **User says stop** or asks a different question

On exit, summarize:
- What was changed (commits-style list of edits)
- What's still open + tag (re-record / re-design / low-priority)
- Recommended next action

---

## Decision discipline

**Don't over-iterate.** If a beat is at 90%, ship it. Hit videos aren't the
sum of perfect beats; they're a strong hook + clear arc + decent execution.

**Don't apply fixes the reviewer didn't suggest.** The reviewer is the source
of truth for what's wrong. Don't add your own changes.

**Don't ask the user a question that the reviewer already answered.** If
reviewer said "swap image X for image Y" and Y exists, just do it.

**Ask the user when:**
- Reviewer suggested a fix outside the mechanical whitelist
- Multiple competing suggestions ranked equal — user picks priority
- Loop hit iteration cap with unresolved issues
- A fix would break another beat (cross-beat dependency)

---

## Examples

### Example 1: "улучши b4"
```
1. dl compose <edit> b4 --width 540p --draft
2. Spawn video-reviewer on data/finalize/b4_960w_draft.mp4
3. Reviewer returns:
   - HIGH · mech · 5min: drop bg_opacity in chunk 2 from 0.45 to 0.30
   - MED · mech · 5min: enable ken_burns in chunk 3
   - MED · re-record · 2h: pause "ИИ → Я говорил" is 2.46s, target 0.7s
4. Apply suggestion 1 + 2 in beats.py (both mechanical)
5. dl compose <edit> b4 --width 540p --draft
6. Spawn video-reviewer again
7. Reviewer returns: "all visual issues resolved; re-record still open"
8. Report to user: "Visual fixes applied. Re-record needed for pause issue."
```

### Example 2: "посмотри финал"
```
1. ls data/finalize/iter*.mp4 → pick latest (iter86.mp4)
2. Spawn video-reviewer Mode 2 (Full Video)
3. Return the reviewer's verdict + top 5 improvements directly to user
   (don't auto-apply on full-video review — too many cross-beat decisions)
```

### Example 3: "что с записью outro"
```
1. ls data/recordings/*outro* → find latest take
2. Spawn vo-reviewer
3. Return verdict (in-final / re-record + main fix)
```

### Example 4: "проверь b4 и улучши если возможно"
```
1. Spawn video-reviewer on b4
2. Read response
3. If reviewer says ship → tell user it's ready
4. Else → run improve loop (Example 1 path)
```

---

## What the orchestrator NEVER does

- Make up that an asset exists (always check `data/` before referencing in beats.py)
- Re-record VO autonomously (always needs user)
- Modify multiple beats based on a single beat's review (scope creep)
- Loop more than 5 iterations without checking in
- Skip rendering after a beats.py edit ("trust me bro" — always re-render + re-review)
- Apply fixes the reviewer flagged as `re-design` (those need user)
- Treat blind reviewer approval as final ship approval when regression gates still fail

---

## Quick reference card

```
USER SAYS                   ORCHESTRATOR DOES
─────────────────────────   ─────────────────────────────────────
"оцени запись"          →  spawn vo-reviewer on latest .webm
"посмотри бит X"        →  spawn video-reviewer on data/finalize/X*
"разбор iter"           →  spawn video-reviewer on latest iter*.mp4
"thumbnail/обложка"     →  spawn thumbnail-designer
"улучши X"              →  RUN IMPROVE LOOP
"быстрый рендер X"      →  dl compose <edit> X --width 540p --draft
"финал"                 →  dl render <edit>
"рилс из X"             →  dl cut <video> <range> --reframe crop_center
"новая запись"          →  dl audio <edit> <bid> <file> + vo-reviewer
"что улучшить"          →  spawn video-reviewer + present ranked suggestions
                           (don't auto-apply on this verb)
```
