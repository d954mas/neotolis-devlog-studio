"""Chunk-window resolution and background-segment merging.

Both routines preserve v1 semantics verified against the legacy engine
(common/devlog/render/compose_ffmpeg.py) and its unit tests
(common/tests/test_scene_merge.py). What's preserved is documented inline so a
future reader can diff against v1 without re-deriving it.
"""
from __future__ import annotations

from dataclasses import dataclass

from dlstudio.ir import CheckIssue, IRSegment, WordSpan
from dlstudio.model import Chunk, Design, Scene

from .roles import BgSpec, content_role

_EPS = 1e-4

# A content-derived background is described by the same shape whether it comes
# from a Scene or a segment-role content variant (compile.roles.BgSpec).
_Bg = BgSpec


def _round(v: float) -> float:
    return round(v, 4)


def _clamp(v: float, lo: float, hi: float) -> float:
    return lo if v < lo else hi if v > hi else v


# ─── Chunk windows ─────────────────────────────────────────────────────────

def resolve_windows(
    chunks: list[Chunk],
    words: list[WordSpan],
    duration: float,
) -> tuple[list[tuple[float, float]], list[str], list[CheckIssue]]:
    """Resolve each chunk's word span to a beat-relative [t0, t1] window.

    Per-chunk base (v2 formula, adds pads v1 never had):
        t0 = words[i].start - pad_before
        t1 = words[j].end   + pad_after
    then, to TILE the beat (v1 semantics preserved):
        - the FIRST chunk's t0 is forced to 0.0            (beat start)
        - the LAST  chunk's t1 is forced to `duration`     (beat end)
        - each interior t1 is `max(padded_end, next_chunk_t0)`.

    The interior rule reproduces v1 exactly at the default pads: v1 used
    `t_end = words[next_chunk.first].start` (compose_ffmpeg.py L411-414), i.e.
    a chunk stays on screen until the next chunk begins, never leaving a blank
    gap. With pad_after == 0 the padded end equals `words[j].end`, which is
    <= the next chunk's start, so `max(...)` collapses to `next_chunk_t0` ==
    v1's boundary. A pad_after large enough to push past the next chunk's start
    yields t1 > next_t0 — a real overlap, surfaced as VQ-WORDS.

    Everything is clamped to [0, duration]. Out-of-range word indices are
    clamped (compile must not crash) and reported two ways: a "VQ-WORDS:"
    tagged string in the returned issue list (human display, -> Timeline.
    warnings) and a structured CheckIssue in the returned diagnostics list
    (-> Timeline.diagnostics; `where` is filled in by the caller with the
    beat id). Both carry the same message text.
    """
    n = len(chunks)
    issues: list[str] = []
    diagnostics: list[CheckIssue] = []
    if n == 0:
        return [], issues, diagnostics

    nw = len(words)

    def _word_start(idx: int) -> float:
        return 0.0 if nw == 0 else words[_clamp_idx(idx, nw)].t0

    def _word_end(idx: int) -> float:
        return duration if nw == 0 else words[_clamp_idx(idx, nw)].t1

    # word-span sanity: index range, i<=j per chunk, ordered/non-overlapping
    # across chunks. Both indices are validated here (not just where they're
    # consumed) — the last chunk's t1 is forced to `duration` so its end index
    # would otherwise never be range-checked.
    prev_j = None
    for ci, ch in enumerate(chunks):
        i, j = ch.words
        if nw == 0:
            msg = f"chunk {ci} references words but the transcript is empty"
            issues.append(f"VQ-WORDS: {msg}")
            diagnostics.append(CheckIssue(severity="error", code="VQ-WORDS", message=msg))
        else:
            if not (0 <= i < nw):
                msg = f"chunk {ci} start index {i} out of range [0,{nw - 1}]"
                issues.append(f"VQ-WORDS: {msg}")
                diagnostics.append(CheckIssue(severity="error", code="VQ-WORDS", message=msg))
            if not (0 <= j < nw):
                msg = f"chunk {ci} end index {j} out of range [0,{nw - 1}]"
                issues.append(f"VQ-WORDS: {msg}")
                diagnostics.append(CheckIssue(severity="error", code="VQ-WORDS", message=msg))
        if i > j:
            issues.append(f"VQ-WORDS: chunk {ci} has start index {i} > end "
                          f"index {j}")
        if prev_j is not None and i <= prev_j:
            issues.append(f"VQ-WORDS: chunk {ci} word range starts at {i} which "
                          f"overlaps/precedes previous chunk end {prev_j}")
        prev_j = j

    t0s: list[float] = []
    for ci, ch in enumerate(chunks):
        i, _ = ch.words
        if ci == 0:
            a = 0.0
        else:
            a = _word_start(i) - ch.pad_before
        t0s.append(_round(_clamp(a, 0.0, duration)))

    windows: list[tuple[float, float]] = []
    for ci, ch in enumerate(chunks):
        _, j = ch.words
        t0 = t0s[ci]
        if ci == n - 1:
            t1 = duration
        else:
            padded_end = _word_end(j) + ch.pad_after
            t1 = max(padded_end, t0s[ci + 1])
        t1 = _round(_clamp(t1, 0.0, duration))
        if t1 < t0:
            t1 = t0
        windows.append((t0, t1))

    # time-window overlap (pad-induced): t1[k] strictly past next t0
    for k in range(n - 1):
        if windows[k][1] > t0s[k + 1] + _EPS:
            issues.append(f"VQ-WORDS: chunk {k} window ends at "
                          f"{windows[k][1]:.3f}s, overlapping chunk {k + 1} "
                          f"which starts at {t0s[k + 1]:.3f}s")
    return windows, issues, diagnostics


def _clamp_idx(idx: int, n: int) -> int:
    return 0 if idx < 0 else n - 1 if idx >= n else idx


# ─── Background segments ────────────────────────────────────────────────────

def _bg_from_scene(scene: Scene) -> _Bg:
    return _Bg(kind=scene.kind, src=scene.src, offset=scene.offset,
               ken_burns=scene.ken_burns, loop=scene.loop, fit=scene.fit)


def _content_bg(chunk: Chunk) -> _Bg | None:
    """The chunk's own visual as a background segment, if its content is a
    segment-role variant (ImageShot/VideoShot). Returns None for overlay-role
    content (Plate/Overlay), which use a scene. Dispatch via compile.roles so a
    new content variant registers its background once (finding L4)."""
    role = content_role(chunk.content)
    return role.background(chunk.content) if role is not None else None


def resolve_backgrounds(
    chunks: list[Chunk],
    beat_scene: Scene | None,
) -> list[_Bg | None]:
    """Per-chunk effective background, preserving v1's stateful inheritance.

    v1 (_merge_scene_segments) seeds `current = beat.scene` and only switches
    it when a chunk carries its own scene; a scene-less Plate/Overlay inherits
    whatever scene is current (NOT necessarily beat.scene — see
    test_plate_chunks_between_scenes_extend_current). ImageShot/VideoShot
    content overrides the background for that chunk's window ONLY and does not
    disturb the inherited scene (v1 drew image/video over the running scene, so
    the scene resumes after).
    """
    current = _bg_from_scene(beat_scene) if beat_scene is not None else None
    out: list[_Bg | None] = []
    for ch in chunks:
        content_bg = _content_bg(ch)
        if content_bg is not None:
            out.append(content_bg)                 # window-local override
            continue
        if ch.scene is not None:
            current = _bg_from_scene(ch.scene)      # switch running scene
        out.append(current)
    return out


def build_segments(
    chunks: list[Chunk],
    windows: list[tuple[float, float]],
    beat_scene: Scene | None,
    duration: float,
    design: Design,
    assets: dict,
) -> tuple[list[IRSegment], list[str], list[CheckIssue]]:
    """Merge consecutive same-`src` backgrounds into IRSegments.

    v1 same-source merge preserved (test_scene_merge.py matrix):
      - consecutive chunks with the same background src -> ONE segment;
        the FIRST chunk's spec wins (first offset used, later offsets ignored).
      - a scene-less chunk does not break the current segment (it inherits).
      - segment ends at the next segment's start (== next chunk t0); the last
        segment ends at `duration`. First segment starts at its first chunk's
        t0 (0.0 for chunk 0; a later t0 leaves a gap the renderer fills with
        the design bg colour, matching v1's gap0 injection).

    Segment boundaries get a crossfade Transition (design.crossfade_dur) to the
    next segment, unless the chunk that OPENS the next segment carries its own
    `transition`, which then wins.

    Video offsets at/past the probed source EOF are clamped to
    max(0, duration_src - window_length) with a "VQ-OFFSET:" warning (v1 trap:
    a silent offset-past-EOF produced audio-only video). The clamp is also
    recorded as a structured CheckIssue in the returned diagnostics list
    (`where` is filled in by the caller with the beat id); `warnings` keeps
    the tagged string for human display.
    """
    from dlstudio.model.content import Transition

    bgs = resolve_backgrounds(chunks, beat_scene)
    warnings: list[str] = []
    diagnostics: list[CheckIssue] = []

    # group consecutive same-src runs
    @dataclass
    class _Run:
        bg: _Bg
        t0: float
        t1: float
        open_chunk: int

    runs: list[_Run] = []
    for ci, bg in enumerate(bgs):
        wt0, wt1 = windows[ci]
        if bg is None:
            continue
        if runs and runs[-1].bg.src == bg.src:
            runs[-1].t1 = wt1                       # extend; first spec wins
        else:
            runs.append(_Run(bg=bg, t0=wt0, t1=wt1, open_chunk=ci))

    segments: list[IRSegment] = []
    for ri, run in enumerate(runs):
        bg = run.bg
        seg_t0 = _round(run.t0)
        seg_t1 = _round(duration if ri == len(runs) - 1 else run.t1)
        seg_dur = max(0.0, seg_t1 - seg_t0)
        offset = bg.offset

        if bg.kind == "video":
            probe = assets.get(bg.src)
            src_dur = probe.duration if probe is not None else None
            if src_dur is not None and offset >= src_dur - _EPS:
                new_offset = _round(max(0.0, src_dur - seg_dur))
                msg = (f"scene offset {offset:.2f}s is at/past source "
                       f"duration {src_dur:.2f}s for {bg.src}; clamped to "
                       f"{new_offset:.2f}s (v1 trap: silent audio-only render)")
                warnings.append(f"VQ-OFFSET: {msg}")
                diagnostics.append(CheckIssue(severity="warn", code="VQ-OFFSET", message=msg))
                offset = new_offset

        # xfade to the NEXT segment (None on the last)
        xfade: Transition | None = None
        if ri < len(runs) - 1:
            next_open = runs[ri + 1].open_chunk
            override = chunks[next_open].transition
            xfade = override if override is not None else Transition(
                kind="fade", dur=design.crossfade_dur)

        segments.append(IRSegment(
            kind=bg.kind, src=bg.src, offset=_round(offset),
            t0=seg_t0, t1=seg_t1,
            ken_burns=bg.ken_burns, loop=bg.loop, fit=bg.fit,
            xfade=xfade,
        ))
    return segments, warnings, diagnostics
