# Recording Contract

Put each gameplay take in the production's v2
`data/plan/capture_requests.json`. This is the executable Studio schema:

```json
{
  "version": 2,
  "requests": [{
    "id": "character_walk_realtime",
    "source": "gameplay",
    "target": "data/footage/character_walk_realtime.mp4",
    "editorial_role": "gameplay",
    "capture_method": "realtime_window",
    "state_id": "character.anatomy",
    "scene": "character.anatomy",
    "action_id": "walk",
    "build_id": "exe-sha256:<running-executable-sha256>",
    "seed": 42,
    "parameters": {
      "presentation": "single",
      "camera_yaw_radians": 0.0,
      "camera_pitch_degrees": 30.0,
      "camera_half_height": 1.15
    },
    "orientation": "landscape",
    "min_width": 1920,
    "min_height": 1080,
    "min_fps": 30,
    "simulation_rate": 1.0,
    "continuous": true,
    "clean_ui": true,
    "content_seconds": 27,
    "head_handle_seconds": 5,
    "tail_handle_seconds": 5,
    "presentation": {
      "output_width": 1920,
      "output_height": 1080,
      "fit": "cover",
      "focus_center_required": false,
      "focus_tolerance_ratio": 0.05
    }
  }]
}
```

`character.anatomy` and `walk` above are real ids from the current game capture
scene catalog. The semantic hash fields are deliberately omitted. Lock
them with `record_window_realtime.py --probe-requests <capture_requests.json>
--request-id <id> --pid <game-pid>` before preparing the batch. The probe loads
the exact scene/seed, applies the parameters, reads
`game.capture_scene.status`, then triggers the declared action and stores the
second status hash atomically into this same request. The two probe hashes must
differ. During real-time recording the scene may advance between load and the
action, so the recorder also captures a fresh `pre_action` status and requires
the action response to change that live semantic hash. The recorder brackets
those two action RPCs with `time.pause`/`time.resume`, while the media stream
continues, so an ordinary simulation tick cannot impersonate the action.
The mandatory cadence audit blocks any visible freeze. This stable delta
proves the action without expecting a time-varying scene to reproduce the
probe's exact post-action hash five seconds later. A passive scene such as
`crowd.progression` uses
`"action_id": null` and `"expected_action_semantic_hash": null`.

When centering a known subject is a hard requirement, add a game-owned focus
rectangle in source-pixel coordinates:

```json
{
  "presentation": {
    "output_width": 1920,
    "output_height": 1080,
    "fit": "cover",
    "focus_center_required": true,
    "focus_tolerance_ratio": 0.05,
    "focus_rect": {"x": 760, "y": 300, "width": 400, "height": 480}
  }
}
```

The focus rectangle should come from game layout/DevAPI semantics, not from an
agent guessing pixels by sight.

## Capture Methods

- `realtime_window`: real-time client-area media stream. Required for `gameplay`.
- `deterministic_devapi`: manual clock plus per-frame framebuffer capture.
  Allowed only for `debug_proof` or `presentation`.

## Result Metadata

The real-time recorder writes `<artifact>.capture.json` with:

- capture method;
- PID, HWND, window title;
- exact client-area screen rectangle;
- FPS and requested handle durations;
- start/end timestamps;
- output SHA-256;
- resolved process executable path and executable SHA-256;
- `client_area=true` and `cursor_visible=false`.

A production capture result should additionally repeat `capture_method`,
`state_id`, and `build_id`, and name `game_report_path` plus its
`game_report_sha256`. The game report must contain the raw
`game.capture_scene.describe`, load/parameter/before/optional-action/after
statuses, exact executable build id and PID, and encoded-PTS-backed monotonic
start/end measurements. Studio rejects scene restarts, missing or changed
semantic hashes, undeclared actions, hidden-UI failures, stale report hashes,
a DevAPI listener owned by a different PID, and encoded durations that differ
from measured real time. Missing
structured identity is a blocking error; free-form notes and recorder-only
`simulation_rate=1.0` assertions are not authoritative.
