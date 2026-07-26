# Studio v2 — long-form devlog production contract

Status: normative. Applies to every product-first production with
`kind = "devlog"`. The executable implementation lives in
`dlstudio.services.longform_preflight`.

Reference benchmark: `docs/ZERAH_DEVLOG_BENCHMARK.md`.
Editorial rationale and examples: `docs/LONG_DEVLOG_PLAYBOOK.md`.
Ship procedure: `docs/CHECKLIST_LONG_DEVLOG.md`.

## 1. Required production artifacts

`dl2 new-production <product> --kind devlog` MUST create:

```text
<product>/devlogs/<production>/
  production.toml
  edit/
    __init__.py
    beats.py
    design.py
  data/
    plan/
      story_map.json       # narrative and evidence contract
      shot_manifest.json   # montage and presentation contract
```

Before draft rendering:

```powershell
dl2 longform-check <product:production>
```

Before final VO recording:

```powershell
dl2 longform-check <product:production> --strict
```

Both contracts are also checked by `dl2 preflight` and `dl2 autopilot-run`.
Final preflight uses strict source resolution.

## 2. Story map

Schema: `devlog.longform_story_map/v1`.

The root MUST contain:

- `title`: viewer-facing working title;
- `macro_question`: one question the ending answers;
- `target_duration_seconds`: normally 360–720;
- `cold_open`;
- `mini_arcs`;
- `ending`.

### 2.1 Cold open

`cold_open` MUST name:

- `anomaly`: real failure, surprising behavior, or costly decision;
- `result_glimpse`: visible eventual payoff;
- `episode_promise`: what the viewer will understand or see;
- sources with roles `failure` and `payoff`.

The montage MUST begin both failure and payoff glimpse before 0:08.
The product and episode promise MUST be spoken by 0:15; this remains a
transcript/reviewer judgment because a JSON string cannot prove delivery.

### 2.2 Mini-arcs

Minimum count:

```text
max(4, ceil(target_duration_seconds / 90))
```

Every mini-arc MUST contain:

```text
viewer_question
goal
failure
cause
solution
proof
reaction
```

Every mini-arc MUST bind real evidence:

- `before`;
- `payoff`;
- at least one of `failure` or `process`.

Source status:

- `existing` — file MUST exist inside the production root;
- `needs_capture` — warning in planning, error in strict mode;
- `placeholder` — warning in planning, error in strict mode.

A result-only block is a status report, not a devlog story.

### 2.3 Ending

The ending MUST contain:

- `resolved_question`: direct answer to `macro_question`;
- `honest_status`: what remains unfinished or uncertain;
- `next_open_loop`: at most one concrete next question.

## 3. Montage and presentation contract

The existing `shot_manifest.json` is the single source of truth for
montage. Long-form productions use:

```json
{
  "version": 2,
  "profile": "longform_devlog",
  "target_semantic_change_seconds": [3, 6],
  "master_shot_max_seconds": 8,
  "target_vo_wpm": [150, 165],
  "author_reaction_interval_seconds": [45, 75],
  "music_phases": [],
  "sfx_cues": [],
  "shots": []
}
```

Every shot MUST include the normal production-contract fields plus:

| Field | Meaning |
|---|---|
| `arc_id` | `cold_open`, `ending`, or exact `mini_arcs[].id` |
| `story_role` | `before`, `failure`, `cause`, `process`, `solution`, `payoff`, `reaction`, `bridge`, `context` |
| `visual_mode` | one of the modes below |
| `src` | production-owned evidence source |
| `t0`, `t1` | shot position on the episode timeline |
| `motion` | `native`, `ken_burns`, `animated`, etc. |
| `presentation` | `full_bleed`, `inset`, `framed`, `contain`, `split` |
| `internal_changes_seconds` | required for master shots longer than 8s |

Allowed `visual_mode` values:

```text
gameplay
editor
code
diagram
reference
physical_metaphor
meme
kinetic_text
before_after
face
title
other
```

The strict gate requires montage coverage for every arc:

- `before`;
- `payoff`;
- at least one of `failure` or `process`.

The source paths used by an arc's shots MUST be bound to that same arc in
`story_map.json`.

## 4. Editing rules

These rules describe semantic rhythm, not mandatory hard cuts.

### 4.1 Shot rhythm

- A new semantic state SHOULD arrive every 3–6 seconds.
- A master shot longer than 8 seconds MUST list
  `internal_changes_seconds`.
- No gap between declared internal changes may exceed 6 seconds.
- Three or more consecutive shots in one visual mode spanning over 12
  seconds trigger a review warning.
- The complete episode SHOULD use at least four visual modes.

Semantic change means at least one of:

- new action or state in gameplay;
- new framing or scale;
- before/after switch;
- callout that changes what the viewer should inspect;
- editor/code view that exposes the cause;
- diagram that explains the decision;
- human reaction or deliberate comic punctuation.

Camera motion over unchanged information does not count.

### 4.2 Sequence grammar

Default arc assembly:

```text
before → failure → cause/process → solution → payoff → reaction
```

- `failure` and `payoff` SHOULD use comparable framing.
- The clean payoff MUST hold long enough to read without VO.
- Code/editor footage MUST explain a cause or decision; it cannot be filler.
- Diagram footage MUST reduce a real causal explanation.
- Meme/quote inserts MUST punctuate a story beat, not replace proof.
- Author reaction MAY be face footage, VO over proof, or a deliberate pause.

### 4.3 Transitions

- Hard cuts are the default inside one causal sequence.
- A 0.2–0.35s fade/crossfade MAY mark a chapter or time jump.
- Generic wipes, zoom transitions, and motion presets MUST NOT substitute
  for missing story information.
- A before/after transition MUST preserve subject position whenever
  possible.

### 4.4 Text

- One message per shot.
- Viewer-visible overlay normally contains no more than 5–7 words.
- Large kinetic text is reserved for a number, failure, rule, or payoff.
- Code and UI labels must be readable at normal playback, not only paused.
- Devlog number and production labels cannot be the main on-screen promise.

## 5. Delivery rhythm

- Russian VO SHOULD target 150–165 words/minute.
- An honest reaction/opinion/cost SHOULD occur every 45–75 seconds.
- A typical 8–12 minute episode SHOULD plan 2–3 music phases.
- Roughly 8–15 purposeful stingers/SFX is an advisory range.
- Music MUST step back for causes, jokes, and first clean payoff view.
- Delivery loudness remains the Studio standard: −14 LUFS with safe true
  peak. Loudness is not a pacing fix.

Before blind review, analyze the exact draft with the same reference-lab
settings used for the benchmark:

```powershell
py -3.12 tools/devlog_reference_lab/analyze.py <exact.mp4> `
  --out <production>/data/review/longform_metrics --skip-sheets
```

Scene-event cadence is a diagnostic proxy, not a cut quota. A candidate with
an order-of-magnitude gap versus the benchmark or a median detected plateau
above 12 seconds cannot pass on the numeric report alone: the reviewer MUST
name the exact semantic changes that make those intervals intentional.

## 6. Review contract

`review_pack.json` includes:

- exact artifact path and SHA-256;
- complete `story_map`;
- shot `arc_id`, `story_role`, `visual_mode`, source and timing;
- compact frames and preflight issues.

A blind reviewer MUST report:

1. the macro question it inferred;
2. every mini-arc it could identify;
3. failure and payoff timestamps for each identified arc;
4. the longest master-shot/visual-mode plateau;
5. whether the ending answered the macro question;
6. exact artifact path, SHA-256, timestamp, and verdict.

If the reviewer cannot identify an authored arc without production notes,
that arc is not yet clear enough to ship.

Packaging MUST prepare three meaningfully different title/thumbnail
hypotheses for YouTube's native long-form A/B test. Variants differ in the
viewer promise (curiosity, number, outcome), not only color or wording. The
test is evaluated by watch time; click-through rate alone is not the winner
criterion. The selected pair MUST still match the first 15 seconds.

## 7. Gate matrix

| Stage | Command | Blocking behavior |
|---|---|---|
| planning | `dl2 longform-check <production>` | structure, missing story fields, missing proof coverage |
| before final VO | `dl2 longform-check <production> --strict` | all planning errors plus unresolved/missing sources |
| storyboard | `dl2 autopilot-run <production>` | long-form gate + ordinary asset/script/visual checks |
| final | `dl2 preflight <production> --final` | strict long-form gate bound into exact preflight |
| delivery | `publish-evidence` / `deliver` | exact final and non-stale review evidence |
