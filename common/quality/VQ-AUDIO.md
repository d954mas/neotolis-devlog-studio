# VQ-AUDIO — Loudness, Ducking, Mix Targets

The audio mix (VO loudness, music presence, ducking, cross-beat
consistency) meets numeric targets, not vibes. No code gate exists yet for
this rule (`render/assemble.py`'s full mix graph — music beds, sidechain
ducking, -14 LUFS loudnorm — is the Phase 2 scope in
`docs/ARCHITECTURE_V2.md`); until that ships, this is entirely
judgment/measurement.

## Use when

- A beat or edit has background music, VO takes, ducking, or any new/
  changed audio asset.
- Reviewing a full video or reel before ship — loudness consistency across
  beat joins is part of the orchestrator regression checklist.
- Evaluating a recorded VO take (`vo-reviewer` scope).

## Do not use for

- Silent, text-only visual changes (plate size, bg_opacity, position) that
  don't touch audio.
- Judging whether a VO's *content*/delivery style fits the hook — that's
  VQ-HOOK's job even though it also cites LUFS/LRA as supporting evidence.

## Check

- VO take integrated loudness: **-14 to -16 LUFS**, true peak **≤ -1.0
  dBFS**, LRA **≥ 3.0** (flat/monotone speech shows as LRA < 2.0).
- Final mix loudness normalization target: **-14 LUFS** (the full-mix
  graph target for v2 per `docs/ARCHITECTURE_V2.md`).
- Loudness consistency across beat boundaries in a full video: **±0.5
  LUFS** (spot-check via loudnorm probe at each join).
- Background music must be audible but not distracting, and audibly duck
  under VO when both play (sidechain ducking keyed by the VO stem, not a
  static music level).
- No abrupt phrase cuts at beat boundaries or edited joins.
- Internal pause budget for a VO take: natural pause 0.3-0.8s, emphasis
  pause 1.0-1.5s, drama pause 2.0s+ only at an explicit climax — pauses
  outside these bands are a re-record signal, not a mixing fix.

## Evidence required

- `ffmpeg -i FILE -af loudnorm=I=-16:TP=-1.5:LRA=11:print_format=json -f
  null -` output (I/TP/LRA numbers), or the equivalent `dl audio`/take
  analysis numbers.
- A loudnorm probe at each beat boundary for full-video loudness
  consistency, with the delta stated in LUFS.
- Explicit note that music is present and audibly ducks under VO (not just
  "music exists").

## Not enough

- "Audio sounds fine" or "mix seems balanced" with no LUFS/TP/LRA numbers.
- Confirming music exists without checking it ducks or that it doesn't
  fight the VO.
- Checking loudness once at the start of a full video and assuming later
  beats match — beat-to-beat drift is exactly what the ±0.5 LUFS check
  catches.
