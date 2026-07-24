# VQ-BOUNDARY — Cut Intent and Source Continuity

The engine checks every compiled visual boundary before rendering. Gameplay
cuts must be declared; continuous takes must advance through the source
without rewinding or restarting.

## Use when

- Gameplay changes source, beat, day, state, or offset.
- A source is split into multiple timeline segments.
- A reviewer reports an abrupt cut or a clip restarting from its beginning.

## Do not use for

- Frame cadence and freezes inside one segment; use VQ-TEMPORAL.
- Crop and centering; use VQ-GEOMETRY.
- Whether a declared motivated cut is creatively good; that remains review.

## Check

- Every compiled boundary touching gameplay has an incoming
  `transition_intent`.
- `continuous_same_take` requires the same `asset_id`/source and the next
  offset must equal the previous source-window end within 0.12 s.
- `no_cut` is invalid when the compiler produced a real boundary.
- Rewind/restart requires `motivated_cut`, `before_after`, or
  `chapter_boundary`; an undeclared reset blocks render.
- `dl2 preview` writes `data/review/boundary_report.json` with every boundary,
  not a sampled subset.

## Evidence required

- Clean `VQ-BOUNDARY` and `VQ-RESTART` pre-render checks.
- `data/review/boundary_report.json` from the exact compiled edit.
- For a motivated cut: review frames around that exact timestamp.

## Not enough

- Watching only a contact sheet; it can miss a restart between samples.
- Adding a fade without declaring why the source changes.
- Assuming two identical filenames imply continuous source time.
