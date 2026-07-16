"""compile — DSL + words.json + ffprobe facts -> Timeline IR.

OWNER: compile-agent (implementation may restructure submodules freely,
but this public signature is the contract).

Responsibilities:
- parse Whisper words JSON (v1 schema — see legacy common/devlog/audio/transcribe.py)
- probe referenced assets via ffprobe (skippable for unit tests)
- resolve chunk word-index windows to beat-relative seconds (+ pads)
- merge consecutive same-source scenes into segments (v1 semantics:
  first offset wins; see legacy tests common/tests/test_scene_merge.py)
- clamp offsets past EOF with a warning (v1 trap: silent audio-only render)
- compute beat durations (VO audio is authoritative), absolute placements
- resolve MusicRegions/SfxEvents onto the timeline

Structured diagnostics: word-index out-of-range and offset-past-EOF clamps
are the two facts not otherwise recoverable from the resolved IR (raw word
indices and pre-clamp offsets aren't stored — contract freeze). compile
appends a `CheckIssue` for each straight to `Timeline.diagnostics` (`where`
set to the beat id) alongside the human-readable "VQ-WORDS:"/"VQ-OFFSET:"
tagged string in `Timeline.warnings`; check/ merges diagnostics directly,
no regex parsing.

Submodules: words.py (transcript parsing), probe.py (ffprobe facts),
segments.py (window resolution + same-source merge). Overlay/placement/mix
resolution lives here.
"""
from __future__ import annotations

import hashlib

from dlstudio.ir import (
    AssetProbe,
    BeatPlacement,
    CheckIssue,
    IRAnim,
    IRBeat,
    IRCaption,
    IRMix,
    IRMusicSpan,
    IROverlayItem,
    IRSfx,
    Timeline,
    WordSpan,
)
from dlstudio.model import Beat, Chunk, Edit

from .probe import Kind, build_registry
from .roles import content_role
from .segments import build_segments, resolve_windows
from .words import load_words

__all__ = ["build_timeline"]


def build_timeline(
    edit: Edit,
    *,
    probe: bool = True,
    probes: dict[str, AssetProbe] | None = None,
) -> Timeline:
    """Compile an Edit into a Timeline.

    probe=True  -> ffprobe every referenced asset (durations, resolutions).
    probe=False -> skip ffprobe; inject facts via `probes` (path -> AssetProbe).
                   The `probes` keyword is a compile-agent addition for tests
                   (allowed: additive, no contract field renamed/retyped).

    Words JSON is always read from disk (the transcript is the master clock);
    only media *facts* are probe-gated.
    """
    assets = build_registry(_referenced_paths(edit), probe=probe, injected=probes)

    warnings: list[str] = []
    diagnostics: list[CheckIssue] = []
    ir_beats: list[IRBeat] = []
    for beat_id in edit.order:
        beat = edit.beats[beat_id]
        ir_beat, beat_warnings, beat_diagnostics = _compile_beat(beat_id, beat, edit, assets)
        ir_beats.append(ir_beat)
        warnings.extend(beat_warnings)
        diagnostics.extend(beat_diagnostics)

    placements = _placements(edit.order, ir_beats)
    mix = _build_mix(edit, placements, ir_beats)

    return Timeline(
        edit_name=edit.name,
        design=edit.design,
        beats=ir_beats,
        placements=placements,
        mix=mix,
        assets=assets,
        output=edit.output,
        warnings=warnings,
        diagnostics=diagnostics,
    )


# ─── beat compilation ───────────────────────────────────────────────────────

def _compile_beat(
    beat_id: str,
    beat: Beat,
    edit: Edit,
    assets: dict[str, AssetProbe],
) -> tuple[IRBeat, list[str], list[CheckIssue]]:
    words = load_words(beat.words)
    duration = _beat_duration(beat, assets)

    windows, word_issues, word_diags = resolve_windows(beat.chunks, words, duration)
    segments, seg_warnings, seg_diags = build_segments(
        beat.chunks, windows, beat.scene, duration, edit.design, assets)
    overlays = _build_overlays(beat.chunks, windows)
    sfx = _build_sfx(beat, words)
    captions = _build_captions(words, duration) if beat.subtitles else []

    ir_beat = IRBeat(
        id=beat_id,
        duration=duration,
        audio=beat.audio,
        words_path=beat.words,
        words=words,
        segments=segments,
        overlays=overlays,
        face=beat.face,
        sfx=sfx,
        transition_out=beat.transition_out,
        captions=captions,
    )
    warnings = [f"[{beat_id}] {w}" for w in (*word_issues, *seg_warnings)]
    diagnostics = [
        d.model_copy(update={"where": beat_id}) for d in (*word_diags, *seg_diags)
    ]
    return ir_beat, warnings, diagnostics


def _beat_duration(beat: Beat, assets: dict[str, AssetProbe]) -> float:
    """Beat duration is authoritative from the VO audio (probe fact)."""
    probe = assets.get(beat.audio)
    if probe is None or probe.duration is None:
        raise ValueError(
            f"cannot determine duration for beat audio {beat.audio!r}: no probe "
            f"duration available (probe=True requires a readable file; "
            f"probe=False requires an injected AssetProbe with a duration)"
        )
    return float(probe.duration)


def _build_overlays(
    chunks: list[Chunk],
    windows: list[tuple[float, float]],
) -> list[IROverlayItem]:
    """Resolve chunks to z-ordered IROverlayItems (see compile.roles).

    - overlay-role content (Plate/Overlay) is its own raster visual -> always
      an overlay item.
    - segment-role content (ImageShot/VideoShot) is an ffmpeg background, so it
      is an overlay item ONLY when the chunk carries decorations (H1): the
      decorations composite over a TRANSPARENT frame, letting the moving scene
      segment supply the image/video pixels (raster must not double-draw a
      static copy over the Ken Burns segment).

    Each item gets `content_hash` = sha1(chunk model_dump_json)[:16] so the
    beat cache key (which hashes the IRBeat) changes whenever rasterized
    content — text, style, decorations, bg — changes, even though the Chunk
    itself reaches the rasterizer out-of-band via the chunk resolver.
    `asset_paths` lists the files the raster pass reads (Plate.bg_image) so the
    cache tracks their identity too. Anim `t` (normalized 0..1 within the
    window) resolves to beat-relative absolute seconds."""
    overlays: list[IROverlayItem] = []
    z = 0
    for ci, ch in enumerate(chunks):
        role = content_role(ch.content)
        if role is None:
            continue
        if role.role != "overlay" and not ch.decorations:
            continue
        t0, t1 = windows[ci]
        dur = t1 - t0
        anims = [
            IRAnim(
                prop=a.prop, start=a.start, end=a.end, ease=a.ease,
                t0=round(t0 + a.t[0] * dur, 4),
                t1=round(t0 + a.t[1] * dur, 4),
            )
            for a in ch.anims
        ]
        content_hash = hashlib.sha1(ch.model_dump_json().encode("utf-8")).hexdigest()[:16]
        overlays.append(IROverlayItem(
            chunk_index=ci, z=z, t0=t0, t1=t1,
            anims=anims, transition_in=ch.transition,
            content_hash=content_hash,
            asset_paths=role.raster_asset_paths(ch.content),
        ))
        z += 1
    return overlays


# Phrase grouping for `beat.subtitles` (PLAN_STUDIO_V2 1.6). Tuned for
# spoken-word reels: split on a real breath pause, cap the line length so a
# phrase always fits one wrapped caption in the bottom safe zone.
CAPTION_PAUSE_SPLIT = 0.6     # inter-word gap (s) that starts a new phrase
CAPTION_MAX_CHARS = 34        # max joined text length before a forced split
CAPTION_LAST_TAIL = 0.3       # how long the final phrase lingers after its word


def _build_captions(words: list[WordSpan], duration: float) -> list[IRCaption]:
    """Group the beat's words into phrase-level caption windows.

    A new phrase starts at a pause > CAPTION_PAUSE_SPLIT or when the joined
    text would exceed CAPTION_MAX_CHARS. Each caption HOLDS until the next
    phrase begins (no flicker between words); the last one lingers
    CAPTION_LAST_TAIL, clamped to the beat duration."""
    phrases: list[list[WordSpan]] = []
    cur: list[WordSpan] = []
    for w in words:
        if cur:
            gap = w.t0 - cur[-1].t1
            joined_len = len(" ".join(x.text for x in cur)) + 1 + len(w.text)
            if gap > CAPTION_PAUSE_SPLIT or joined_len > CAPTION_MAX_CHARS:
                phrases.append(cur)
                cur = []
        cur.append(w)
    if cur:
        phrases.append(cur)

    captions: list[IRCaption] = []
    for i, ph in enumerate(phrases):
        t0 = ph[0].t0
        if i + 1 < len(phrases):
            t1 = phrases[i + 1][0].t0
        else:
            t1 = min(duration, ph[-1].t1 + CAPTION_LAST_TAIL)
        if t1 <= t0:                      # degenerate transcript timing
            continue
        captions.append(IRCaption(
            text=" ".join(w.text for w in ph),
            t0=round(t0, 4), t1=round(t1, 4),
        ))
    return captions


def _build_sfx(beat: Beat, words: list[WordSpan]) -> list[IRSfx]:
    """SfxEvent word anchors -> IRSfx beat-relative t (word start time)."""
    out: list[IRSfx] = []
    nw = len(words)
    for ev in beat.sfx:
        if 0 <= ev.word < nw:
            t = words[ev.word].t0
        else:
            t = 0.0     # out-of-range anchor: VQ-WORDS surfaces the bad index
        out.append(IRSfx(src=ev.src, t=round(t, 4), gain_db=ev.gain_db))
    return out


# ─── edit-level resolution ──────────────────────────────────────────────────

def _placements(order: list[str], ir_beats: list[IRBeat]) -> list[BeatPlacement]:
    """Absolute beat starts by summing durations in concat order."""
    placements: list[BeatPlacement] = []
    t = 0.0
    for beat_id, ir_beat in zip(order, ir_beats):
        placements.append(BeatPlacement(beat_id=beat_id, t0=round(t, 4)))
        t += ir_beat.duration
    return placements


def _build_mix(
    edit: Edit,
    placements: list[BeatPlacement],
    ir_beats: list[IRBeat],
) -> IRMix:
    """Resolve MusicRegions to absolute edit-timeline spans.

    from_beat/to_beat are beat ids, inclusive; None means the edit boundary.
    A region spans [start_of(from_beat), end_of(to_beat)].
    """
    start_by_id = {p.beat_id: p.t0 for p in placements}
    dur_by_id = {b.id: b.duration for b in ir_beats}
    total = placements[-1].t0 + ir_beats[-1].duration if ir_beats else 0.0

    spans: list[IRMusicSpan] = []
    for region in edit.mix.music:
        if region.from_beat is None:
            t0 = 0.0
        elif region.from_beat in start_by_id:
            t0 = start_by_id[region.from_beat]
        else:
            raise ValueError(
                f"MusicRegion from_beat {region.from_beat!r} is not an edit beat")

        if region.to_beat is None:
            t1 = total
        elif region.to_beat in start_by_id:
            t1 = start_by_id[region.to_beat] + dur_by_id[region.to_beat]
        else:
            raise ValueError(
                f"MusicRegion to_beat {region.to_beat!r} is not an edit beat")

        spans.append(IRMusicSpan(
            src=region.src, t0=round(t0, 4), t1=round(t1, 4),
            offset=region.offset, gain_db=region.gain_db,
            fade_in=region.fade_in, fade_out=region.fade_out, duck=region.duck,
        ))

    return IRMix(
        music=spans,
        duck=edit.mix.duck,
        target_lufs=edit.mix.target_lufs,
        true_peak_db=edit.mix.true_peak_db,
    )


# ─── asset collection ───────────────────────────────────────────────────────

def _referenced_paths(edit: Edit) -> dict[str, Kind]:
    """Every path an Edit references, mapped to its expected probe kind.
    First kind seen for a path wins (paths are deduped)."""
    paths: dict[str, Kind] = {}

    def add(path: str | None, kind: Kind) -> None:
        if path and path not in paths:
            paths[path] = kind

    # design fonts (once)
    add(edit.design.fonts.main, "font")
    add(edit.design.fonts.bold, "font")
    add(edit.design.fonts.accent, "font")

    # edit-level music
    for region in edit.mix.music:
        add(region.src, "audio")

    for beat in edit.beats.values():
        add(beat.audio, "audio")
        add(beat.words, "other")
        if beat.scene is not None:
            add(beat.scene.src, beat.scene.kind)
        for ev in beat.sfx:
            add(ev.src, "audio")
        for ch in beat.chunks:
            if ch.scene is not None:
                add(ch.scene.src, ch.scene.kind)
            role = content_role(ch.content)
            if role is not None:
                for path, kind in role.referenced_paths(ch.content):
                    add(path, kind)
    return paths
