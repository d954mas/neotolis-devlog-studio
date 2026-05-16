# Devlog Pipeline — Orchestrator Instructions

This is the playbook for the **orchestrator** (Claude) when the user writes
free-form requests about a devlog video. The user describes intent; the
orchestrator picks the right action(s) and runs them. Two agents handle
focused review work: `vo-reviewer` (voice takes) and `video-reviewer`
(rendered beats + full video + plan).

---

## How to read user input

The user writes in free form. Map their intent to one of these actions:

| User says | Action |
|---|---|
| "оцени запись", "проверь take", "посмотри запись" | Spawn `vo-reviewer` on the latest matching `.webm` |
| "посмотри бит X", "разбор b4", "что с битом" | Spawn `video-reviewer` on `data/finalize/<bid>_video_*.mp4` |
| "разбор iter", "посмотри финал", "что с видео" | Spawn `video-reviewer` on latest `iter*.mp4` |
| "разбери план X", "что в beats.py для X" | Spawn `video-reviewer` plan mode (no render) |
| "улучши X", "доведи X до ship", "make it better" | **Run improve loop** (see below) |
| "сделай быстрый рендер", "draft X" | `dl compose <edit> <bid> --width 540p --draft` |
| "финальный рендер", "render final" | `dl render <edit> --width 4k` (or 1080p if explicit) |
| "сделай рилс из X" | `dl cut <video> <range> --reframe crop_center --out reels/...` |
| "запиши новый бит", "после записи" | Run `dl audio <edit> <bid> <file>` then spawn `vo-reviewer` |

If intent is unclear, **ask one short question** before acting.

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
dl render <edit> --width 540p --quality draft -j 6

# If devlog.toml has default_edit/render defaults, the short form is preferred:
dl check
dl render
dl compose <bid>
dl watch --beat <bid>

# Deeper preflight when scene offsets/assets changed
dl check <edit> --deep

# Quick project status
dl doctor
dl beats <edit> --missing-only
dl assets <edit> --width 4k
dl cache-info
dl script <edit>
dl shotlist <edit>
dl smoke --skip-tests

# Mid-quality preview
dl render <edit> --width 1080p --quality preview -j 4

# Final delivery
dl render <edit> --quality upload             # explicit upload preset
dl render --final                             # default final preset from devlog.toml
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

**Don't spawn for:** raw audio take quality.

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

---

## Quick reference card

```
USER SAYS                   ORCHESTRATOR DOES
─────────────────────────   ─────────────────────────────────────
"оцени запись"          →  spawn vo-reviewer on latest .webm
"посмотри бит X"        →  spawn video-reviewer on data/finalize/X*
"разбор iter"           →  spawn video-reviewer on latest iter*.mp4
"улучши X"              →  RUN IMPROVE LOOP
"быстрый рендер X"      →  dl compose <edit> X --width 540p --draft
"финал"                 →  dl render <edit>
"рилс из X"             →  dl cut <video> <range> --reframe crop_center
"новая запись"          →  dl audio <edit> <bid> <file> + vo-reviewer
"что улучшить"          →  spawn video-reviewer + present ranked suggestions
                           (don't auto-apply on this verb)
```
