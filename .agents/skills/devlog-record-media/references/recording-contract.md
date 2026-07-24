# Recording Contract

Use one JSON contract per gameplay take.

```json
{
  "schema": "devlog.gameplay_capture",
  "version": 1,
  "request_id": "day5_station_realtime",
  "artifact": "data/footage/day5_station_realtime.mp4",
  "editorial_role": "gameplay",
  "capture_method": "realtime_window",
  "state_id": "day5_station_new_visual",
  "build_id": "exe-sha256:<running-executable-sha256>",
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
  "planned_use": {
    "start": 5,
    "end": 32
  },
  "presentation": {
    "output_width": 1920,
    "output_height": 1080,
    "fit": "cover",
    "focus_center_required": false,
    "focus_tolerance_ratio": 0.05
  }
}
```

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
`state_id`, and `build_id`. Missing structured identity is a blocking error;
free-form notes are not authoritative.
