# VQ-WORDS — Word-Index / Chunk-Window Validity

Chunk word-index ranges are in-range against the transcript, non-
overlapping, and in order — and, on top of that, actually split at a good
point in the spoken line.

**Enforced by engine (v2):** `dlstudio.check._check_words()` in
`common/dlstudio/src/dlstudio/check/__init__.py:79-102` catches overlapping
or out-of-order overlay windows directly from the IR. Out-of-range word
indices and offset-past-EOF clamps are recorded by `compile` as structured
`CheckIssue`s on `Timeline.diagnostics` and merged in by
`_promote_warnings()` (`check/__init__.py:136-141`) — see also
`docs/issues/dlstudio-phase1-followups.md` item 1 for how this replaced a
regex-based warning parse. Legacy v1 has no equivalent code gate.

## Use when

- Writing or editing chunk `words=(a, b)` ranges in `beats.py`, especially
  on reels/shorts where pacing is tight.
- Reviewing a beats.py plan before the first render (`video-reviewer` plan
  mode).

## Do not use for

- Style-only chunk edits (`size`, `bg_opacity`, `position`, `subtitle_color`)
  that don't touch word ranges.
- Judging whether the *visual* shown during a word window matches — that's
  a plan-review pacing concern, not this rule's numeric gate (though both
  are often checked together).

## Check

- v2: `dl2 check` reports no `VQ-WORDS` error/warning (engine-enforced
  overlap/order/out-of-range part).
- v1: manually cross-reference `words.json` against each chunk's `words=`
  range — no code gate exists to catch overlap or out-of-range indices.
- Beyond the mechanical check: split points land at natural speech pauses
  or clause boundaries, not mid-phrase — the code only proves windows
  don't overlap, not that the split is a *good* one.
- Overlay/subtitle text actually matches what's said in that word window
  (read the transcript segment, don't assume from the beat's summary).

## Evidence required

- `dl check` / `dl2 check` clean output (no `VQ-WORDS` issue), or the
  specific `CheckIssue` text if one was raised and how it was resolved.
- The `words.json` segment text for the chunk's word range, quoted
  alongside the chunk's overlay/subtitle text, to show the split lands on
  a real boundary.

## Not enough

- "Chunks compile fine" without checking the split lands on a
  sentence/clause boundary — a passing mechanical check says nothing about
  whether the cut is mid-word-of-thought.
- Trusting a plan-mode review that didn't open `words.json` and only read
  the chunk summary in `beats.py`.
- Assuming a v1 edit's chunk ranges are valid because it rendered
  successfully — v1 has no overlap/range gate at all.
