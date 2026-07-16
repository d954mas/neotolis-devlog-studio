# VQ-ASSET — Asset Existence and Path Discipline

Every asset referenced by a beat exists, is readable, and was actually
verified in `data/` before being written into `beats.py` — never invented.

**Enforced by engine (v2):** `dlstudio.check._check_assets()` in
`common/dlstudio/src/dlstudio/check/__init__.py:59-74` errors on any
referenced asset that is missing, or present but unreadable (`AssetProbe
.readable is False` — set by `compile/probe.py` when ffprobe fails on an
existing file; see `docs/issues/dlstudio-phase1-followups.md` item 2).
Legacy v1 has no equivalent code gate.

## Use when

- Referencing any new `src=` path in `beats.py`.
- Swapping an image/scene/video asset during an improve-loop iteration.
- Working on a legacy v1 edit, where nothing catches a missing/invented
  path except an actual render attempt.

## Do not use for

- Whether the asset is the *right* one / authentically the real product —
  that authenticity judgment is VQ-PROOF's job. VQ-ASSET only proves the
  file is there and readable, and that the path wasn't invented.
- Overlay/plate text quality on top of the asset — that's VQ-SAFE/content
  concerns.

## Check

- v2: `dl2 check` reports no `VQ-ASSET` error (mechanical existence/
  readability part).
- v1: manually confirm the path exists — no automatic gate.
- The path was found via an actual `Glob`/`Read`/directory listing of
  `data/` **before** it was written into `beats.py` — never invented or
  guessed from a similar-sounding prior asset name. This is the
  orchestrator's explicit never-do in `AGENTS.md`/`common/PIPELINE.md`.
- The asset isn't a leftover scratch/placeholder file (e.g. a scaffold
  default) accidentally left in a final/upload render.
- `dl assets --width 4k` / `dl2 assets` run before final render to catch
  unused/low-res/missing assets as a batch, not just the one just added.

## Evidence required

- `dl check` / `dl2 check` clean output (no `VQ-ASSET` error), or the exact
  error text if one was raised and how it was fixed.
- The `Glob`/directory-listing result that showed the path existed before
  it was written into `beats.py`.

## Not enough

- "Asset renders" as proof alone — a render only proves the check ran and
  passed, not that the path was chosen from a verified `Glob` result rather
  than assumed to match a similar prior asset.
- Assuming a path exists because a previous, differently-named beat used
  something similar in the same `data/` folder.
- Skipping `dl assets` before a final render because the one new asset
  "obviously" exists — batch checks catch assets other than the one you're
  focused on.
