# VQ — Video Quality Rule Catalog

Gates that used to be scattered across `common/PIPELINE.md`, `AGENTS.md`,
and `common/HIT_VIDEO_PRACTICES.md` live here as one rule per file, selected
à la carte. Pattern ported from game-67-idle's `ai_studio/quality` (rule
catalog + per-rule "Use when / Do not use for / Check / Evidence / Not
enough" files, profiled rather than globally enforced).

This catalog does not replace those documents — `HIT_VIDEO_PRACTICES.md`
still holds the narrative "why" and iteration history; `PIPELINE.md` still
owns the orchestrator's improve-loop and regression-checklist mechanics.
This catalog exists so a reviewer or agent can pick the right numeric
targets and evidence bar for a change without re-reading three docs.

## Rule catalog

| Rule | Use when | Do not use for |
|---|---|---|
| [VQ-SYNC](VQ-SYNC.md) | any render/concat of a final or beat MP4 | draft mid-edit renders you already plan to re-render |
| [VQ-AUDIO](VQ-AUDIO.md) | a beat/edit has music, VO mix, ducking, or a new audio asset | silent/text-only visual-only changes |
| [VQ-MOTION](VQ-MOTION.md) | a beat uses a screenshot/scene background, especially reels | punchline-only static plates where stillness is the point |
| [VQ-TEMPORAL](VQ-TEMPORAL.md) | a rendered shot should move: gameplay, capture, animation, camera motion | declared static cards and deliberate ending holds |
| [VQ-SILENT-REEL](VQ-SILENT-REEL.md) | a reel has no VO or must work with sound off | voiced tutorials and long-form instruction |
| [VQ-HOOK](VQ-HOOK.md) | writing/reviewing the opening line of a reel/short or cold-open | mid-video build/climax beats after the hook already landed |
| [VQ-LONGFORM](VQ-LONGFORM.md) | planning, scripting, reviewing, or shipping a 6–12 minute devlog | reels/shorts, tutorials, and release-note walkthroughs |
| [VQ-SAFE](VQ-SAFE.md) | overlay/plate/subtitle position, size, or `bg_opacity` changes | full-bleed segments with no overlay text |
| [VQ-END](VQ-END.md) | any full video or reel final/upload render | draft renders of individual beats mid-production |
| [VQ-PROOF](VQ-PROOF.md) | an asset claims to show the real product/site/game, or thumbnail packaging | openly stylized b-roll/meme clips not claiming to be the real product |
| [VQ-RES](VQ-RES.md) | new full-bleed video/image asset, resolution/aspect change, choosing draft vs final width | judging composition quality at a given resolution (see VQ-SAFE/VQ-MOTION) |
| [VQ-GEOMETRY](VQ-GEOMETRY.md) | full-bleed fit/crop/anchor changes and gameplay centering | subjective composition without focus metadata |
| [VQ-BOUNDARY](VQ-BOUNDARY.md) | gameplay source/offset changes, day transitions, reported restarts | cadence/freezes inside one segment |
| [VQ-WORDS](VQ-WORDS.md) | writing/editing chunk word-index ranges in `beats.py` | style-only chunk edits that don't touch word ranges |
| [VQ-ASSET](VQ-ASSET.md) | referencing a new `src=` path, swapping an image/scene asset | authenticity of what an asset depicts (route to VQ-PROOF) |
| [VQ-STANDALONE](VQ-STANDALONE.md) | every publishable reel/short | internal regression renders and isolated beats |
| [VQ-EDITORIAL-LABEL](VQ-EDITORIAL-LABEL.md) | HyperFrames/audience copy may contain production labels | explicitly approved public serialization |

Eight of these (`VQ-SYNC`, `VQ-RES`, `VQ-GEOMETRY`, `VQ-BOUNDARY`,
`VQ-WORDS`, `VQ-ASSET`, `VQ-STANDALONE`, `VQ-EDITORIAL-LABEL`) have a mechanical part that is
**enforced by engine** in `common/dlstudio` — see the core checks plus
`services/editorial_preflight.py`. Their `.md` files also state the judgment
part the code cannot see. The other seven
(`VQ-AUDIO`, `VQ-MOTION`, `VQ-HOOK`, `VQ-LONGFORM`, `VQ-SAFE`, `VQ-END`,
`VQ-PROOF`) have
no code gate at all — they are pure judgment, checked by reviewer agents or
the orchestrator's regression checklist (`common/PIPELINE.md`).

`VQ-OFFSET` (scene offset at/past source EOF) exists as an engine-only warn
in `check/__init__.py` with no separate judgment component worth a file —
compile clamps it automatically; there is nothing a human needs to decide.

## How rules are selected

**By change type** — pick rules from what actually changed, not the full catalog:

| Changed | Run |
|---|---|
| Chunk word-index range | VQ-WORDS |
| New/swapped `src=` asset | VQ-ASSET (+ VQ-PROOF if it claims to be the real product) |
| Full-bleed fit/crop/anchor change | VQ-GEOMETRY (+ VQ-RES for source quality) |
| Gameplay source/offset/day boundary | VQ-BOUNDARY (+ VQ-TEMPORAL post-render) |
| VO take processed, music/mix touched | VQ-AUDIO |
| Reel/short opening line or cold-open | VQ-HOOK |
| Long-form devlog story, evidence plan, or final | VQ-LONGFORM (+ VQ-HOOK for the cold open) |
| Overlay/plate/caption position, size, `bg_opacity` | VQ-SAFE |
| Scene/background using a screenshot, any reel edit | VQ-MOTION |
| Gameplay/screen capture or reported freeze/stutter | VQ-TEMPORAL on the exact rendered MP4 |
| Silent reel or feedback that a reel is too fast to parse | VQ-SILENT-REEL |
| Any beat/final/concat render | VQ-SYNC, VQ-RES (engine-mechanical part always runs via `dl check`/`dl2 check`) |
| Full video or reel final/upload render | VQ-END, plus the full `PIPELINE.md` regression checklist |
| Long-form devlog final/upload render | VQ-LONGFORM, VQ-END, plus `docs/CHECKLIST_LONG_DEVLOG.md` |

**By ship stage** — hard-gating happens once, at ship time; earlier stages
use the same rules advisorily:

| Stage | Hard gate | Advisory only |
|---|---|---|
| Draft iteration (`dl iter`, `dl2 iter`, `dl2 compose --quality draft`) | VQ-SYNC/VQ-RES/VQ-WORDS/VQ-ASSET mechanical part (always runs via `check`) | everything else — note issues, don't block |
| Improve-loop review (`video-reviewer`/`vo-reviewer`) | none | whichever rules match what the beat touches |
| Ship / final / upload render | all selected rules, plus `PIPELINE.md`'s orchestrator regression checklist and reel gate | — |

Legacy v1 edits (`common/devlog`, `trolley`, `neotolis_diary` — frozen per
`docs/ARCHITECTURE_V2.md`) have none of the `dlstudio/check` code gates.
For those projects, treat every rule as judgment-only and run the manual
`ffprobe`/`dl check` steps `HIT_VIDEO_PRACTICES.md` already documents.

## "Unverified" != pass

If a rule cannot actually be checked — no ffprobe run, no frame extracted,
no contact sheet looked at — the correct report is `unverified` plus the
reason and the next concrete artifact needed, **never** a silent pass and
never "looks fine" standing in for a check. `PIPELINE.md` already states
this as "do not hide it behind a reviewer 'ship' verdict"; this catalog
makes it the default assumption for every rule, matching the game-67-idle
convention (`pass` / `block` / `review` / `unverified` — no bare "skip").

A reviewer that writes "ship" without the evidence a rule's file requires
has not passed that rule — it has skipped it and mislabeled the skip.

## Rule file format

Every `VQ-*.md` file uses exactly these sections:

- **Use when** — the concrete situation that makes this rule apply.
- **Do not use for** — situations that look similar but aren't this rule's
  job (usually pointing at the correct rule instead).
- **Check** — the concrete, numeric checklist. Numbers come from
  `HIT_VIDEO_PRACTICES.md` / `AGENTS.md` / `PIPELINE.md` where they exist
  (LUFS targets, the ~3s motion floor, `bg_opacity` ranges, the
  first-second hook rule). Where a mechanical part is enforced by
  `dlstudio/check`, the file says so up front and this section covers only
  what the code can't judge.
- **Evidence required** — the concrete artifact that proves a pass:
  ffprobe/loudnorm output, a contact sheet, a frame extract, a `dl check`
  clean run, a provenance path.
- **Not enough** — what does not count as evidence, most commonly a
  reviewer or agent saying "ship"/"looks fine" without the artifact above.
