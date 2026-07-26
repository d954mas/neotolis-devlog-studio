---
name: devlog-record-media
description: Record and machine-validate clean gameplay or voice media for a Studio v2 devlog. Use when capturing real-time game footage, replacing short or wrong-state gameplay, preventing restarts/freezes, ensuring centered client-area framing, adding edit handles, recording Studio voice takes without clicks, or auditing a capture before it enters beats.py.
---

# Devlog Record Media

Create media with enough edit handles, exact source identity, and structured
evidence. Run deterministic checks before visual review or montage.

## Choose The Media Class

- `gameplay`: real-time editorial footage. Record the game window/client area as a continuous media stream.
- `debug_proof` or `presentation`: controlled frame-stepped DevAPI output. Route to `$devlog-debug-scenes`.
- `voice`: Studio microphone take with recorded lead-in and tail room tone.

DevAPI is the control plane for preparing game state. It is not the default
gameplay video stream. Never use `capture.frame` plus `time.step` to satisfy a
`gameplay` or `realtime_window` request.

## Gameplay Contract

Create the capture contract before recording. Use the schema and example in
[recording-contract.md](references/recording-contract.md).

The contract must name:

- editorial role and required capture method;
- exact `state_id` and build identity;
- exact game-owned `scene` (equal to `state_id`) and declared `action_id`;
- orientation, minimum native resolution, FPS, and simulation rate;
- content duration plus at least 5 seconds of head and tail handles;
- continuous-take and clean-UI requirements;
- intended Studio output resolution and `fit`;
- optional game-owned `focus_rect` when subject centering is a requirement.

Do not accept prose such as “new visual” as the only state identity. A day,
branch, commit, save-state, or scenario id must make old/new footage
machine-distinguishable.

## Record Gameplay

1. Build and launch the requested game revision.
2. Use DevAPI only to load/reset the scene, set deterministic parameters, and position the camera.
3. Return the simulation to real-time clock mode before capture.
4. Capture only the game client area at native delivery resolution or higher. Exclude editor strips, window chrome, testbed menus, cursor, performance overlays, and desktop.
5. Start the video stream first, hold the camera for the head handle, perform the action once, then hold the tail handle.
6. Keep one visual state and one continuous take. Do not loop, freeze, restart, retime, interpolate, or pre-upscale the source.
7. Save structured recorder metadata beside the MP4.

On Windows, use the bundled client-area recorder:

```powershell
# First lock semantic hashes from the exact running PID into the raw v2 request.
python .agents/skills/devlog-record-media/scripts/record_window_realtime.py --pid <game-pid> --probe-requests <production-root>/data/plan/capture_requests.json --request-id <request-id>
dl2 capture-flow <product:production> <request-id>
# Then execute the isolated prepared batch printed by capture-flow.
python .agents/skills/devlog-record-media/scripts/record_window_realtime.py --pid <game-pid> --batch <production-root>/data/plan/capture_batches/<request-id>.json --request-id <request-id>
```

It records immediately, hides the mouse cursor, resolves the client rectangle
and executable from the PID, verifies the executable SHA against `build_id`,
checks the game-owned capture-scene descriptor/status, automatically triggers
the declared action after the head handle, continues recording until the
observed action response plus content and tail handles are complete, and writes both
`<capture>.capture.json` and `<capture>.game.json`. The latter preserves raw
`describe`, before/action/after status, one scene generation, semantic hashes,
and monotonic wall duration. Compute the expected build id from the
exact executable before recording; a branch name or caller-supplied prose is
not build proof. If the client area is smaller than the requested resolution
or is outside the visible desktop, stop and fix the launch mode; do not
upscale afterward. Batch mode reads all identity/geometry/duration values from
Studio's prepared request and writes one isolated
`data/plan/capture_results/<request-id>.json`; do not retype those values manually.
The semantic probe is a required preflight: it loads the declared seed, applies
the parameters, verifies that the DevAPI listener belongs to the same PID, and
atomically stores the game-reported initial/action hashes before the immutable
capture batch is prepared. The recorded action RPC must return that exact
locked action semantic hash; merely returning a hash different from the live
pre-action status is not sufficient proof.

## Validate Gameplay Before Ingest

```powershell
python .agents/skills/devlog-record-media/scripts/validate_gameplay_capture.py --contract <capture-contract.json> --production-root <production-root> --result <capture-results.json> --request-id <id> --report <audit.json>
```

For a newly recorded file with its recorder sidecar, `--result` is optional.
The validator checks structured method/role compatibility, game-reported
scene/action/build identity, one advancing scene generation, native resolution,
orientation, FPS, duration, edit handles, encoded duration against measured
real time, continuous frame motion, client-area metadata, no upscale, and
centered crop/focus math. Recorder assertions alone never prove game state,
clean UI, or 1x playback.

Any error blocks catalog ingest and `beats.py`. Warnings require an explicit
decision in the capture result. Only after the script passes, inspect a compact
contact sheet for subject emphasis, labels, text, and visual quality.

## Insert Into Studio

1. Probe the source and compile the edit.
2. Read `dl2 ir <edit> --out ir.json`; confirm the exact artifact path, offset,
   segment duration, `fit`, and transition.
3. Use one continuous gameplay scene where possible. Prefer one “before” and
   one “after” take over repeated cutting between old and new visual states.
4. Ensure every used interval stays inside the recorded head/tail handles.
5. Re-run the validator when the source file or intended crop changes.

Studio `cover` uses a centered crop, but it cannot repair a source whose game
client was already off-center or included an editor strip. Source geometry
must pass before render.

## Record Voice In Studio

1. Open `dl2 studio <edit>`.
2. Start the actual media recording immediately.
3. Show a visible `3-2-1` countdown while recording; do not speak during it.
4. After the countdown, record the Studio-managed 2-second room-tone phase,
   then speak only when the prompt changes to `Read now`.
5. Press Stop after the last word and stay silent while Studio records its
   automatic 1-second post-roll. Do not click again.
6. Process with `dl2 audio`, then follow `docs/SPEECH_EDIT.md`.
7. Run the existing WAV start preflight. A click/impulse, clipping, or missing
   clean lead-in blocks the take and requires trim or re-record.

The countdown is not dead time: it places mouse/keyboard permission clicks
outside the spoken content and gives the speech editor safe trim boundaries.

## Stop Conditions

Stop rather than improvising when:

- the correct historical build/state is unavailable;
- native target resolution cannot be recorded;
- the game cannot run in real time while recording;
- the capture method contradicts the editorial role;
- the scene needs a new debug/testbed implementation;
- the source state cannot be proven without a human choice.
