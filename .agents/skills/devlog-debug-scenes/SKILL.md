---
name: devlog-debug-scenes
description: Create or revise deterministic game-owned debug, testbed, and presentation scenes for devlog capture through DevAPI. Use when a video needs a repeatable controlled game state, a before/after renderer comparison, an isolated mechanic demonstration, semantic capture proof, or a reusable capture scenario. Do not use it for ordinary editorial gameplay recording.
---

# Devlog Debug Scenes

Build deterministic capture scenes inside the game, validate their contracts through DevAPI, and produce machine-verifiable proof artifacts. Keep debug proof and ordinary gameplay footage as separate media classes.

## Route The Request First

- Use this skill for a controlled testbed/presentation scene with exact state, parameters, actions, reset behavior, and semantic hashes.
- Use `$devlog-record-media` for normal-speed editorial gameplay or voice recording.
- DevAPI `capture.frame` plus manual `time.step` is allowed here because the output is explicitly `debug_proof` or `presentation`.
- Never relabel a frame-stepped DevAPI result as `gameplay`, `live`, or `realtime_window`.

## Read The Owning Contracts

Before changing a game scene, read:

1. The game repository `AGENTS.md`.
2. The game's `devapi/README.md`, especially “Custom scenes for video capture”.
3. `src/testbed/capture_scene.h` and `src/testbed/capture_scene_catalog.c`.
4. `ai_studio/runtime_automation/capture_scenario.py` and its JSON schema.

For Not a Trolley Problem, use the concrete paths and invariants in
[capture-scene-contract.md](references/capture-scene-contract.md).

## Build The Scene

1. Define one stable scene id and increment its contract version only for a breaking contract change.
2. Add the descriptor to the sorted static catalog under `GAME_TESTBED=ON`.
3. Expose typed, bounded presentation parameters and named actions. Do not expose arbitrary memory mutation.
4. Implement `enter`, `reset`, `update`, `draw_ui`, and actions using production gameplay owners.
5. Reset every causal field explicitly: game state, clocks, RNG seed, camera, renderer knobs, selection, overlays, and pending actions.
6. Hide game/debug UI unless the scene's public purpose explicitly requires it.
7. Implement `ready` and `semantic_hash`. Equal manifests must produce equal semantic hashes at the same frame.
8. Add a versioned manifest under the game's `devapi/capture_scenarios/`.

## Validate Before Rendering A Take

Run from the game repository:

```powershell
cmake --build build/devapi-debug
python ai_studio/runtime_automation/capture_scenario.py validate games/private/game-not-a-trolley-problem/devapi/capture_scenarios/<scene>.v1.json
python ai_studio/runtime_automation/capture_scenario.py --exe build/devapi-debug/<game-exe> run games/private/game-not-a-trolley-problem/devapi/capture_scenarios/<scene>.v1.json --out <run-dir>
```

The run must produce the encoded asset, contact sheet, diagnostics, provenance,
and handoff hashes. Compare two identical runs when determinism is material:

```powershell
python ai_studio/runtime_automation/capture_scenario.py compare <run-a> <run-b>
```

## Machine Gates

Block the handoff when any of these is true:

- the manifest does not validate;
- the scene is absent from `game.capture_scene.list`;
- descriptor and manifest contract versions differ;
- required parameters/actions are missing or out of bounds;
- `ready` never becomes true;
- a reset does not restore the semantic hash;
- the output lacks provenance or exact artifact hashes;
- testbed/debug chrome is visible despite `hides_game_ui=true`;
- the artifact is being assigned the editorial role `gameplay`.

Only after these gates pass, inspect the contact sheet for labels, text,
occlusion, emphasis, and visual style. Do not use visual inspection to infer
determinism, state identity, frame cadence, or capture method.

## Handoff

Name the artifact role explicitly:

- `debug_proof` for engineering evidence;
- `presentation` for a designed controlled demonstration;
- never `gameplay`.

Persist the scene id, contract version, manifest path, build identity, output
path, artifact SHA-256, and provenance path beside the production assets.
