# VQ-LONGFORM — Evidence-First Devlog Story

A long-form devlog is a chain of completed problem/payoff stories, not a
chronological status report. This is a judgment-only rule; the companion
story-map validator checks planning completeness but cannot judge the
finished editorial result.

## Use when

- Planning, scripting, reviewing, or shipping a 6–12 minute devlog.
- A draft is technically clean but feels slow, presentation-like, or hard
  to remember.
- Deciding whether captured development material supports a full episode.

## Do not use for

- Reels/shorts whose complete standalone story is governed by
  `VQ-STANDALONE` and `VQ-HOOK`.
- Pure tutorials or release-note walkthroughs that intentionally optimize
  for reference lookup rather than narrative retention.
- Treating scene-change detection as a mechanical edit-count target; it is
  only a comparison proxy.

## Check

- By **0:08**, the cold open shows a real anomaly/failure and a glimpse of
  the eventual result. By **0:15**, voice names the product and the
  episode's concrete promise.
- The episode has one answerable macro question and at least
  `max(4, ceil(duration / 90 seconds))` completed mini-arcs. A practical
  8–12 minute target is **6–10**.
- Every major mini-arc contains: goal → failed/limited version → cause →
  solution → visible proof → author reaction. Before and payoff must be
  visible; failure or process must be evidenced, not merely asserted.
- A visual semantic change normally arrives every **3–6 seconds**. The
  same master shot does not run beyond about **8 seconds** without a new
  action, angle, or callout.
- The author contributes an honest opinion, cost, mistake, surprise, or
  self-ironic reaction every **45–75 seconds**.
- Russian VO normally targets **150–165 words/minute**. It keeps pauses for
  jokes, proof, and chapter transitions instead of copying an English
  reference's faster speech rate.
- The episode carries one macro open loop and **3–5** micro-loops. Every
  promised loop is paid off or honestly reframed by the ending.
- A typical 8–12 minute audio plan has **2–3** music phases and roughly
  **8–15** quiet stingers/SFX serving transitions, failures, and payoffs.
  These are editorial ranges, not quotas.
- The ending answers the macro question, states the honest current status,
  and opens at most one concrete next question.
- Thumbnail and title promise the same transformation shown in the first
  15 seconds. The thumbnail uses real product proof, one primary object,
  and normally **0–3 words**; the devlog number is not the primary promise.

## Evidence required

- A completed `story_map.json` plus a passing
  `tools/devlog_reference_lab/validate_story_map.py --strict` result.
- Exact reviewed MP4 path and SHA-256, `ir.json`, transcript-derived WPM,
  and the first 15 seconds quoted with timestamps.
- Contact sheets or dense timestamped frame samples plus a full-resolution
  frame for every flagged static run or claimed payoff.
- Source paths/provenance for every before, failure/process, and payoff.
- The exact last frame and hold duration, thumbnail candidate, and audio
  phase/SFX plan.
- A blind review naming the mini-arcs it could actually infer from the
  video without production notes.

## Not enough

- A high scene-event count without watching the exact MP4.
- Stylish cards, clean loudness, or a successful render exit.
- A list of completed features without failure, cause, proof, and reaction.
- A reviewer saying "ship" without naming the artifact, SHA, mini-arcs,
  first-15-second promise, and ending payoff.
- `needs_capture` or placeholder evidence surviving the strict story gate.
