# VQ-GEOMETRY — Source Fit, Crop, and Centering

The engine enforces the mechanical part of this rule from resolved IR
geometry. Creative subject centering remains a review decision unless the
source provides an explicit subject/focus rectangle.

## Use when

- A full-bleed image or video is cropped, contained, or repositioned.
- Gameplay must remain centered across several beats/days.
- A source has a different aspect ratio from the delivery frame.

## Do not use for

- Text safe zones and caption placement; use VQ-SAFE.
- Source resolution/upscale quality; use VQ-RES.
- Deciding whether the most important character or object is artistically
  centered when no focus metadata exists.

## Check

- `fit`, `anchor_x`, and `anchor_y` resolve to integer source, scale,
  crop/pad, and output coordinates in every compiled `IRSegment`.
- `VQ-GEOMETRY` blocks transforms whose source facts disagree with ffprobe,
  whose output differs from the design resolution, or whose crop/pad lies
  outside the scaled frame.
- A center anchor (`0.5`, `0.5`) must produce the mathematical center crop.
- `dl2 preview` writes `data/review/geometry_report.json`; unresolved gameplay
  geometry is an error.
- If the desired subject is not at the source center, set an explicit anchor
  and verify a full-resolution frame. Do not create a manually pre-cropped
  duplicate merely to hide the transform.

## Evidence required

- A clean `dl2 check`/preview pre-render gate.
- `data/review/geometry_report.json` from the exact compiled edit.
- For non-central anchors or subjective focus: one full-resolution frame that
  shows the intended subject placement.

## Not enough

- “Looks centered” based only on a low-resolution contact sheet.
- FFmpeg's implicit default crop position with no resolved IR coordinates.
- A pre-cropped/upscaled source file created only to silence a quality gate.
