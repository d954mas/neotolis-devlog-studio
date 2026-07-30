# Studio v3 — UI/UX review

Date: 2026-07-30

Scope: director review console at the `review` action

Persona: one owner who does not edit video manually

> **Status:** this document records the pre-redesign baseline. The score and
> friction findings below describe the interface before the implementation
> completed later on 2026-07-30.

## Implementation follow-up

The current tree addresses the primary findings without changing Studio v3
fact ownership, rendering, immutable artifacts, or cache behavior:

- click selects one frame; pointer drag selects a half-open frame range;
- active visual, transition and audio items are attached automatically from
  the exact `TimelineIR`;
- pointer drag directly on the video creates a spatial annotation;
- one custom transport covers play/pause, frame stepping, volume and
  fullscreen;
- the composer and final actions remain visible beside the player on desktop;
- the full technical timeline is collapsed by default;
- the review-only layout was checked at 1440×900, 1024×768, 768×1024,
  390×844 and 320×700 with no horizontal overflow.

The repeat-review follow-up adds the deliberately small A/B layer:

- one previous finding at a time, with previous/next navigation and a
  hold-or-toggle `До исправления` control;
- presentation-time navigation with independent FPS/duration clamping, while
  every locator remains bound to its own exact artifact;
- read-only old-video annotation with working playback, frame-step and audio
  controls;
- default-fixed resolutions, with only `still_wrong` and `obsolete`
  exceptions exposed to the owner;
- atomic local restoration of the active finding, note, range and region, plus
  migration of pre-redesign drafts;
- visible media failure/retry states and full stale-round refresh after a
  two-tab CAS conflict.

Independent subagent reviews found and drove fixes for current/old frame
desynchronization, lost legacy drafts, orphaned continuation findings,
stuck hold-preview state, mobile overflow, volume jumps, failed thumbnail
retry, incorrect pending-draft restoration and cached-media readiness races.
The final full gate passes 212 Python tests, 6 fast UI tests and 8 real-browser
Playwright scenarios.

Post-redesign evidence:

- `output/playwright/ui-redesign-20260730/desktop-final.png`
- `output/playwright/ui-redesign-20260730/desktop-feedback-selected.png`
- `output/playwright/ui-redesign-20260730/mobile-390-top.png`
- `output/playwright/ui-redesign-20260730/mobile-390-notes.png`
- `output/playwright/ui-redesign-20260730/mobile-320-top.png`

## Post-redesign audit

Overall score: **21/24**

| Pillar | Score | Assessment |
|---|---:|---|
| Copywriting | 4/4 | The default surface speaks in tasks and outcomes; implementation terms stay in the collapsed inspector. |
| Visuals | 3/4 | The player, frame strip and composer form one clear workspace; a waveform remains the main missing visual aid. |
| Color | 4/4 | Accent, selection, warning and focus states are consistent, and functional microcopy now meets AA contrast. |
| Typography | 3/4 | Primary controls and guidance are readable; dense clip labels remain intentionally compact inside technical details. |
| Spacing | 3/4 | The desktop sidecar and mobile stack remove the former page travel; a true mobile composer sheet could reduce travel further. |
| Experience Design | 4/4 | Frame, range and region selection are direct; targets attach automatically; drafts cannot be submitted accidentally; final actions remain visible. |

The follow-up interaction and accessibility review also added:

- optimistic identity checks for the exact artifact, timeline, check report and
  constraints, so a stale browser cannot approve a newer production state;
- local-only range preview while dragging, with one media seek on pointer-up;
- mobile scroll cancellation that leaves the previous selection unchanged;
- keyboard range contraction/reversal, selected-state semantics and 44 px
  technical timeline targets;
- locked draft controls during submission, live saved-count feedback and focus
  recovery after save, delete and review completion;
- an accessible central-region preset alongside direct pointer annotation.

Residual opportunities, not blockers for the owner-review workflow:

- add an audio waveform when audio-heavy productions make visual timing useful;
- consider a mobile bottom-sheet composer if real projects show excessive
  travel between the portrait player and the note field;
- add keyboard controls for precise spatial-region resizing if the central
  preset proves too coarse.

## Verdict

The screen is visually coherent and technically capable, but its information
architecture is optimized for inspecting Studio internals rather than giving
fast creative feedback. The primary task is fragmented across the page:
time selection is above the player, spatial selection is below it, target
selection is in a distant technical timeline, the comment composer is back
beside the player, and final submission is at the bottom.

Overall score: **12/24**

| Pillar | Score | Assessment |
|---|---:|---|
| Copywriting | 2/4 | The central promise is clear, but technical and mixed-language copy competes with the task. |
| Visuals | 3/4 | Cohesive dark direction and recognizable groups, but too many equally prominent surfaces. |
| Color | 3/4 | Consistent palette and clear accent; muted microcopy and disabled states lose clarity. |
| Typography | 2/4 | Strong headings, but many operational labels are only 8–11 px and use technical monospace. |
| Spacing | 1/4 | Excess vertical travel separates controls that belong to one action. |
| Experience Design | 1/4 | A simple comment requires mode changes, navigation and two separate save/send decisions. |

## Evidence

- Tested in a real browser against a safe 12-second review-ready fixture.
- Desktop full page: 1020×2041 px.
- Mobile viewport: 390×844 px; document height: 2913 px.
- Selecting a TimelineIR target scrolls the comment composer out of view.
- Returning to the comment composer scrolls the selected timeline item out of
  view.
- Activating “Выделить область” can scroll its button into view while moving
  part of the video frame outside a 720 px desktop viewport.
- Browser console produced zero errors and warnings. The problem is interaction
  design, not runtime stability.

Screenshots:

- `output/playwright/ui-review-20260730/desktop-full.png`
- `output/playwright/ui-review-20260730/desktop-target-selected.png`
- `output/playwright/ui-review-20260730/desktop-comment-after-target.png`
- `output/playwright/ui-review-20260730/mobile-full.png`

## Primary-flow friction map

| User step | Current interaction | Friction |
|---|---|---|
| Find a problem | Native video controls, custom transport, frame slider and nine thumbnails coexist. | The user must choose a navigation method before understanding their differences. |
| Mark one frame | Default behavior is usable. | Exact frame and timecode are visually over-specified for a non-editor. |
| Mark a range | Select “Диапазону”, seek, then explicitly set start/end with `F` buttons. | The model is procedural and easy to forget; four controls describe one gesture. |
| Draw a region | Press a mode button below the player, then drag on the frame. | Mode activation and drawing target may not fit in the same viewport. |
| Attach a layer/sound | Scroll to the full TimelineIR, understand technical lanes, click an item, then return to the composer. | This asks the user to behave like an editor and breaks visual continuity. |
| Save a comment | Press “Добавить замечание”. | The result is called “Черновик”, so it is unclear whether the comment is already safe. |
| Send feedback | Scroll to the bottom and press “Передать мне N задач”. | The decisive action is detached from the work and offscreen on both desktop and mobile. |

## Findings

### P1 — The primary action is split across three distant surfaces

The player/composer grid, TimelineIR and verdict footer are rendered
sequentially in `ReviewWorkspace.tsx:320-404`. On desktop, selecting a target
moves the user away from the comment field. On mobile, the layout becomes a
single 2913 px column because `styles.css:381-401` stacks every section without
providing a sticky action surface.

**Impact:** high. Every non-trivial comment requires scrolling away from the
object being discussed.

**Recommendation:** keep the comment composer and current issue list sticky
beside the player on desktop and in a bottom sheet on mobile. Keep
“Отправить N комментариев” always visible.

### P1 — Range selection exposes implementation state instead of a direct gesture

The user explicitly selects a mode and manages `Начало = F…` and `Конец = F…`
buttons in `ReviewWorkspace.tsx:279-315`. This is closer to setting in/out
points in an editor than leaving feedback.

**Impact:** high. The user has to understand an editing concept and remember
which endpoint is being changed.

**Recommendation:** default every comment to the paused frame. A drag on the
filmstrip creates a range with two visible handles. Clicking a thumbnail
creates a frame comment. Remove the separate frame/range mode and endpoint
buttons from the default UI.

### P1 — Technical target selection is assigned to the wrong person

The screen asks the owner to inspect “Структура финального TimelineIR”, identify
“Слой 5”, audio roles and transition blocks, then click one to attach it
(`ReviewTimeline.tsx:60-63`, `ReviewTimeline.tsx:105-142`). The backend already
knows which TimelineIR items are active at the selected frame/range.

**Impact:** high. It turns creative feedback into technical diagnosis and makes
the user worry about choosing the correct internal object.

**Recommendation:** attach active layers, transitions and sounds automatically
as agent context. Show a compact “Сейчас активно: логотип · голос · музыка”
summary. Put the full timeline behind “Технические детали”.

### P1 — Mobile hierarchy delays the actual task

At 390 px, the product header, production status card, review heading, artifact
hash and range controls consume roughly the first viewport. The comment
composer appears only after the tall portrait player and filmstrip; the final
CTA is at the end of a 2913 px page.

The global chrome is rendered in `app.tsx:90-143`; the mobile CSS only stacks
the same information (`styles.css:381-401`) rather than reprioritizing it.

**Impact:** high. The user opens a review link but initially sees system status
instead of the video and comment action.

**Recommendation:** on `action === "review"`, replace the normal dashboard
chrome with a compact review header: production title, version and one overflow
menu. Start with the video.

### P2 — Spatial annotation is an avoidable interaction mode

`ReviewPlayer.tsx:223-241` requires pressing “Выделить область”, drawing, then
potentially using “Убрать область”. Native video controls disappear while the
mode is active (`ReviewPlayer.tsx:171-179`).

**Impact:** medium. The state change is subtle, and the control can be separated
from the drawing canvas by viewport height.

**Recommendation:** allow direct pointer-drag on a paused frame. A short click
continues playback/pauses; a drag creates a rectangle. If an explicit tool is
retained, place a small annotation toolbar over the frame.

### P2 — Draft and submission form an unclear two-stage commit

The same feedback is first “Добавить замечание” (`ReviewNotes.tsx:61-72`), then
stored under “Черновик”, and finally “Передать мне N задач”
(`ReviewWorkspace.tsx:368-404`).

**Impact:** medium. Users can leave the page after adding a comment without
realizing it has not been submitted, or hesitate because they do not know what
“Черновик” means.

**Recommendation:** use explicit states:

- “Сохранено на этом устройстве” after adding;
- sticky “Отправить 3 комментария” for canonical submission;
- confirmation after submission.

Alternatively, auto-save each comment canonically and make the final action
only “Завершить ревью”.

### P2 — Four competing playback/navigation mechanisms add noise

The native video controls, custom play/frame-step buttons, range input and
filmstrip are all visible (`ReviewPlayer.tsx:171-254`,
`FrameStrip.tsx:130-143`). Their capabilities overlap.

**Impact:** medium. The user spends attention choosing controls instead of
watching.

**Recommendation:** retain one transport row and one visual scrubber. Hide
native controls and use the filmstrip/scrubber as the single time surface.

### P2 — Critical operational copy is too technical and too small

Examples include `exact artifact`, `TimelineIR`, raw hashes, rational FPS,
`Eligible candidate`, `duck`, dB and fade metadata. Many labels are 8–11 px
(`styles.css:124-152`, `styles.css:249-293`, `styles.css:310-350`).

**Impact:** medium. Important instructions and irrelevant diagnostics receive
similar visual weight.

**Recommendation:** use human labels in the default UI and reserve technical
metadata for an expandable inspector. Raise functional labels to at least
12–14 px.

### P2 — Audio can be selected but cannot be visually located

Audio appears as technical colored bars without a waveform. A user who hears
“music is too loud here” cannot visually identify the phrase or sound peak.

**Impact:** medium for audio feedback.

**Recommendation:** add a compact waveform aligned to the same scrubber. Keep
role labels (“Голос”, “Музыка”, “Эффекты”) but hide dB/fade/duck details unless
expanded.

## What should be removed or hidden by default

- The large `Studio v3` masthead during review.
- Run ID, revision number, workflow stage and eligible-candidate status.
- Raw artifact hash and rational FPS.
- The words `exact artifact` and `TimelineIR`.
- Numeric layer IDs and detailed audio processing metadata.
- The full multi-lane technical timeline.
- Keyboard instructions until help or keyboard focus is requested.

These facts should remain available to the agent and in an expandable
“Технические детали” inspector. Hiding them does not change Studio v3 fact
ownership or caching.

## Recommended default layout

```text
┌─────────────────────────────┬──────────────────────┐
│                             │  Что не так?         │
│          VIDEO              │  [comment field]     │
│    direct region drawing    │  current frame/range │
│                             │  saved comments      │
├─────────────────────────────┤                      │
│ filmstrip + range handles   │                      │
│ waveform + comment markers  │                      │
└─────────────────────────────┴──────────────────────┘
  [Всё устраивает]      [Отправить 3 комментария]
```

On mobile, the composer becomes a bottom sheet and the final action remains
sticky. Layers and audio details open from a small “Контекст” button.

## Top five fixes

1. Co-locate player, comment composer and persistent submit action.
2. Replace frame/range modes and endpoint buttons with direct filmstrip
   selection.
3. Auto-attach active TimelineIR context; move the full timeline to advanced
   details.
4. Remove dashboard/technical chrome from the review route, especially on
   mobile.
5. Unify playback controls and add one shared filmstrip/waveform time surface.

## Human-judgment flags

- `needs_human_review: true` — whether the lime/dark visual direction feels
  appropriate for long review sessions.
- `needs_human_review: true` — whether canonical comments should be submitted
  individually or in one final batch.
- `needs_human_review: true` — whether advanced TimelineIR inspection is useful
  often enough to justify a visible “Контекст” button.
