# Studio v3 — Phase 0 review agent loop

Date: 2026-07-30

Status: completed

Executable proof:
`common/dlstudio/tests/test_v3_review_agent_loop.py`

## Result

The current Studio v3 contracts are sufficient to complete one real loop:

```text
exact review finding
  → fresh-process HTTP handoff
  → authoring revision
  → prepare invalidation
  → draft/final render
  → new review-ready artifact
```

The proof uses a temporary synthetic production:

- 64×96, 30 fps, 200 ms;
- one full-frame `SolidLayer`;
- no source media, recordings, assets or delivery;
- real Studio v3 compile/check/FFmpeg render path;
- real `/api/v3/review/current` and `/api/v3/review/context` queries from a
  separate Python process.

No domain schema or render-cache contract changed in this phase.

## Observations

The submitted finding contains:

- exact artifact, timeline, check report and constraints refs;
- exact frame `[0, 1)`;
- normalized region;
- target `visual.000`;
- plain-language requested change.

The fresh process reconstructs the handoff from canonical state without
browser storage, screenshot, clipboard or timecode conversion.

After changing the one authored color, the ordinary prepare invalidation
removes downstream attempts. Three `advance` calls produce a different
TimelineIR, a different final artifact and return the workflow to `review`.

## Source locatability

Canonical result:

```json
{"source_mapping": {"status": "unavailable"}}
```

The current target remains useful but heuristic:

- `visual.000`;
- label `solid #112233`;
- lane `layer.0`;
- first item in `Edit.visuals`;
- exactly one matching authored color in the fixture.

This was one unambiguous manual source candidate. There is still no canonical
source file, symbol or line mapping, and inserting an earlier visual would
renumber the target. Phase 3 must therefore return `unavailable` honestly
until a real authoring-owned source map exists.

## Reproduced semantic defect

`changes_requested` currently stores a valid exact verdict but marks the
workflow review attempt as succeeded. Status therefore becomes:

```text
current_stage = package
action = advance
```

Release remains protected because packaging rejects a non-pass verdict, but
the workflow projection is wrong and the UI has to mask it. Phase 2 must keep
`changes_requested` and `block` at `review` while atomically publishing review
history.

## Verification

```powershell
common\dlstudio\.venv\Scripts\python.exe -m pytest `
  common\dlstudio\tests\test_v3_review_agent_loop.py -q
```

Result: `1 passed`.
