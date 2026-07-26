# Not a Trolley Problem Capture-Scene Contract

## Owning Files

- Game root: `C:\projects\game-67-idle`
- Public DevAPI guide:
  `games/private/game-not-a-trolley-problem/devapi/README.md`
- Scene interface:
  `games/private/game-not-a-trolley-problem/src/testbed/capture_scene.h`
- Scene catalog and implementations:
  `games/private/game-not-a-trolley-problem/src/testbed/capture_scene_catalog.c`
- DevAPI adapter:
  `games/private/game-not-a-trolley-problem/src/testbed/capture_scene_devapi.c`
- Shared runner:
  `ai_studio/runtime_automation/capture_scenario.py`
- Schema:
  `ai_studio/runtime_automation/schemas/capture-scenario.v1.schema.json`
- Manifests:
  `games/private/game-not-a-trolley-problem/devapi/capture_scenarios/`

## Runtime Boundary

Capture scenes compile only with `GAME_TESTBED=ON`. They must never enter a
Release build. The agent build is `build/devapi-debug`; the normal human debug
build intentionally has DevAPI disabled.

## Public API

Use the seven generic endpoints:

- `game.capture_scene.list`
- `game.capture_scene.describe`
- `game.capture_scene.load`
- `game.capture_scene.reset`
- `game.capture_scene.set_parameter`
- `game.capture_scene.trigger_action`
- `game.capture_scene.status`

Do not add one-off endpoints for a single video.

## Descriptor Requirements

`CaptureSceneDesc` owns:

- stable id and title;
- contract version;
- `hides_game_ui`;
- semantic-hash capability;
- typed parameters and named actions;
- enter/exit/update/reset;
- readiness and semantic hash;
- UI drawing.

Use production gameplay systems from the scene. A debug scene may control
presentation but must not reimplement the mechanic it claims to demonstrate.

## Manifest Requirements

The v1 manifest is strict JSON and currently supports vertical deterministic
outputs. It names:

- scene id and contract version;
- typed parameters;
- fixed-step clock;
- frame-indexed actions;
- capture size, output size, FPS, and orientation;
- expected capabilities.

The shared runner captures PNG frames through `capture.frame`, steps time
manually, encodes MP4, and writes contact sheet, boundaries, diagnostics,
provenance, and handoff hashes.

That frame-stepped pipeline is intentionally a debug/presentation pipeline. It
is not normal editorial gameplay and must not satisfy a `realtime_window`
capture request.
