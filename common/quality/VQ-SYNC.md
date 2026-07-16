# VQ-SYNC — Audio/Video Duration Sync

The rendered output's audio and video streams cover the same duration.
This is the single most expensive historical bug in this workspace: trolley
iter22→iter35 ran 13 iterations with audio=363s vs video=181s (half the
content invisible) before the user, not the agent, noticed.

**Enforced by engine (v2):** `dlstudio.check.verify_output()` in
`common/dlstudio/src/dlstudio/check/__init__.py:146-204`. Every v2 renderer
MUST call this as a postcondition after writing an MP4 — it ffprobes the
file, raises `RuntimeError` if the video stream is missing/zero-duration,
or if `abs(actual - expected) > tolerance` (default `0.25s`). This closes
the exact failure class described above for anything rendered through
`dl2`.

Legacy v1 (`common/devlog`, `dl`, used by `trolley`/`neotolis_diary` —
frozen per `docs/ARCHITECTURE_V2.md`) has **no such postcondition**. For
those projects this rule is entirely manual.

## Use when

- Rendering or re-rendering a final or concatenated video on a **legacy v1
  edit** (`trolley`, `neotolis_diary`) — there is no automatic gate.
- Reviewing any v1 render before calling it ship-ready.
- Adding or changing a v2 renderer that writes an MP4, to confirm it
  actually calls `verify_output()`.

## Do not use for

- v2 (`dl2`) renders where `verify_output()` already ran without raising —
  the postcondition is the check; don't re-derive it by eye, just cite that
  it ran.
- Mid-edit draft beats you already know you'll re-render before shipping
  (still worth a quick probe, but not a blocking gate).

## Check

- `ffprobe` the audio stream duration and the video stream duration of the
  same file; they must match within ~0.25s tolerance.
- The video stream must exist and have nonzero duration (an audio-only
  file with a missing/zero-length video stream is a fail, not a partial
  pass).
- For v1: run this after **every** `dl render` / `dl concat`, not just once
  at the end — the failure mode above went undetected across 13 renders
  because the check wasn't repeated.
- For v2: confirm the renderer path calls `verify_output()` — don't assume
  a new render function inherits it.

## Evidence required

- `ffprobe -v error -show_entries stream=codec_type,duration -of json FILE`
  output showing both streams' durations, or
- The `dl2`/`dlstudio` log line / absence of a raised `VQ-SYNC:` exception
  from `verify_output()`.

## Not enough

- "Render finished without error" on a v1 render — v1 has no duration
  postcondition; a silent truncation produces a clean exit code.
- Reviewer or orchestrator saying "ship" based on watching a few frames —
  frames don't reveal a shortened video stream sitting under longer audio.
- Assuming a previous successful check on an earlier render of the same
  edit still applies after new assets or beats.py changes.
