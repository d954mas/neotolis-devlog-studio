"""Edit-level assembly — the full Phase-2 mix graph.

`assemble` turns the per-beat MP4s (each `render_beat`'s video + a sibling
`<beat>_vo_stem.wav`) into the final edit MP4 with a real audio mix laid across
beat boundaries. Two paths:

FAST PATH — no music, no SFX, no non-cut transitions. Two sub-cases, gated on
quality so iterate speed and final quality don't fight:

- draft/preview/standard: pure stream-copy concat of the beat MP4s (video +
  their own VO audio), exactly the Phase-1 behaviour. Nothing is re-encoded,
  no mix graph, no loudness pass — the iterate-speed path.
- upload/master: ARCHITECTURE_V2 promises finals at `mix.target_lufs` (-14
  LUFS). A silent stream-copy would ship whatever loudness the raw VO takes
  happened to have, so for these FINAL tiers we still stream-copy the VIDEO
  (fast) but re-encode ONLY the audio through the same two-pass loudnorm the
  mix path uses (`_fast_concat_normalized`). Video quality/speed is untouched;
  only the audio gets normalized.

The trigger that forces the mix path deliberately IGNORES a `transition_out`
carried solely by the LAST beat: a beat's transition fades INTO the next beat,
and the last beat has no next beat, so its tail transition is a no-op that must
neither dip the finale to black nor drag the edit onto the (slower) mix path.

MIX PATH — anything else. Three stages:

1. VIDEO TRACK. If no transitions, the beat videos are concat-copied into a
   single video-only track (still no re-encode). If any beat carries a non-cut
   `transition_out`, ONLY the beats adjacent to a boundary are re-encoded (with
   the boundary fades below); every other beat is stream-copied and all
   segments are concat-copied together. Concat-copy of copied + freshly
   re-encoded segments is compatible because both keep the render_beat codec
   params (libx264/yuv420p, same resolution, `-r fps` timebase) AND the SAME
   pinned video timescale (`render.beat.VIDEO_TIMESCALE`, set on both the beat
   encode and `_reencode_fade_segment`) — without a common timescale a copied
   and a re-encoded segment can carry different timebases and trip the concat
   demuxer.

2. AUDIO MIX (the core). One ffmpeg `-filter_complex` built from the typed AST
   in graph.py — no string templating. On one ABSOLUTE edit timeline:
     - each VO stem is `adelay`-ed to its `BeatPlacement.t0` and summed into a
       VO bus (`amix normalize=0`);
     - the VO bus is `asplit` into the final-mix tap plus one sidechain key per
       ducked span;
     - each `IRMusicSpan` is seeked (`-ss offset`), trimmed to `[t0,t1]`, gain
       + fade in/out applied, `adelay`-ed to `t0`, and — when `duck=True` —
       `sidechaincompress`-ed under a VO key (see graph.duck_params for the
       Duck->sidechaincompress mapping);
     - each `IRSfx` is gain-ed and `adelay`-ed to `placement.t0 + sfx.t`;
     - everything sums into one bus rendered to a float-PCM raw wav.

3. MUX + LOUDNESS. Two-pass `loudnorm` (measure then apply with `linear=true`,
   the legacy pattern in common/devlog/audio/process.py) normalizes the raw mix
   to `mix.target_lufs` / `mix.true_peak_db`, muxed over the copied video track.
   Draft/preview quality uses a single dynamic pass.

TRANSITION SEMANTICS (decision): transitions are implemented as NON-OVERLAPPING
fade-through-black (dip-to-black) at the boundary. A beat's `transition_out.dur`
splits in half: the outgoing beat fades to black over its last `dur/2`, the
incoming beat fades in from black over its first `dur/2`. This preserves every
beat's duration exactly, so absolute `BeatPlacement` times and the word-anchored
audio never desync — unlike a true overlapping `xfade`, which shortens total
duration by the overlap. `fade` and `slide_*` therefore also degrade to
dip-to-black in Phase 2; true overlapping crossfades/slides (with the audio
retiming they force) are deferred to a later phase.

POSTCONDITIONS: VQ-SYNC duration (scaled tolerance) + an audio-stream presence
check. `measure_loudness()` (a loudnorm measure pass) is exposed for tests /
future VQ-AUDIO gating.
"""
from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path
from typing import TYPE_CHECKING

from dlstudio.ir import IRBeat, Timeline
from dlstudio.render.beat import VIDEO_TIMESCALE, codec_args
from dlstudio.render.graph import (
    FilterNode,
    Graph,
    InputList,
    amix_sum_node,
    asplit_node,
    db_to_linear,
    music_span_chain,
    sfx_chain,
    sidechain_duck_node,
    vo_stem_chain,
)

if TYPE_CHECKING:                      # avoid a package<->submodule import cycle
    from dlstudio.render import RenderOpts

# VQ-SYNC tolerance for the concatenated edit. Concat is stream-copy (no
# re-encode), but each per-beat MP4 that went into it carries its own
# ~0.02-0.05s of AAC priming/rounding slack; that drift accumulates roughly
# linearly with beat count. A fixed single-beat tolerance (check.verify_output's
# default 0.25s) produces spurious VQ-SYNC failures on long edits, so the
# effective tolerance here scales with `n_beats` instead. MIN_VERIFY_TOL is
# the floor for small edits (1-10 beats); PER_BEAT_VERIFY_TOL is the added
# slack per beat beyond that.
MIN_VERIFY_TOL = 0.5
PER_BEAT_VERIFY_TOL = 0.05

# loudnorm loudness-range target (matches legacy common/devlog/audio/process.py).
_LOUDNORM_LRA = 11.0
# Quality tiers that skip the (heavier) two-pass measured loudnorm and use a
# single dynamic pass — acceptable for draft-quality previews.
_DRAFT_QUALITIES = {"draft", "preview"}
# FINAL quality tiers. Per ARCHITECTURE_V2 these ship at -14 LUFS, so even a
# no-music/no-sfx/no-transition edit runs the loudnorm audio pass (video still
# stream-copies). draft/preview/standard keep the pure fast path.
_FINAL_QUALITIES = {"upload", "master"}


def _scaled_tolerance(n_beats: int) -> float:
    """VQ-SYNC duration tolerance for an edit with `n_beats` concatenated
    beats: `max(MIN_VERIFY_TOL, PER_BEAT_VERIFY_TOL * n_beats)`."""
    return max(MIN_VERIFY_TOL, PER_BEAT_VERIFY_TOL * n_beats)


def _postcondition(path: Path, expected: float, tolerance: float) -> None:
    """VQ-SYNC duration postcondition. check.verify_output is fully
    implemented (compile-agent) -- call it directly with the scaled
    tolerance; there is no fallback path left to catch."""
    from dlstudio.check import verify_output
    verify_output(str(path), expected, tolerance=tolerance)


def _run(cmd: list[str], out_path: Path, what: str) -> None:
    """Run an ffmpeg command; on failure dump the argv + stderr next to the
    output (the *_ffmpeg_error.txt convention beat.py uses) and raise."""
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        dbg = out_path.parent / f"{out_path.stem}_ffmpeg_error.txt"
        dbg.write_text(f"STAGE: {what}\n\nCMD:\n" + " ".join(cmd)
                       + "\n\nSTDERR:\n" + r.stderr, encoding="utf-8")
        raise RuntimeError(f"ffmpeg {what} failed (rc={r.returncode}). Debug: {dbg}")


def _concat_list(files: list[Path], list_file: Path) -> None:
    """Write a concat-demuxer list file (forward slashes + escaped quotes keep
    Windows paths happy under `-safe 0`)."""
    lines = []
    for p in files:
        ap = str(Path(p).resolve()).replace("\\", "/").replace("'", "'\\''")
        lines.append(f"file '{ap}'")
    list_file.write_text("\n".join(lines) + "\n", encoding="utf-8")


# ─── entry ─────────────────────────────────────────────────────────────────

def assemble(timeline: Timeline, beat_files: dict[str, Path],
             opts: "RenderOpts") -> Path:
    """Assemble rendered beats into `timeline.output`. Beats are ordered by
    `timeline.beats` (concat order). Verifies total duration and (mix path) an
    audio stream before returning. See the module docstring for the two paths."""
    out_path = Path(timeline.output)
    out_path.parent.mkdir(parents=True, exist_ok=True)

    beats = timeline.beats
    if not beats:
        raise RuntimeError("assemble: timeline has no beats")
    ordered = [beat_files[b.id] for b in beats]

    has_music = bool(timeline.mix.music)
    has_sfx = any(b.sfx for b in beats)

    def _is_transition(b: IRBeat) -> bool:
        t = b.transition_out
        return bool(t and t.kind != "cut" and t.dur > 0)

    # A transition_out on the LAST beat has no next beat to transition into: it
    # would only fade the finale to black AND needlessly force the mix path.
    # Drop it (with a warning) — the trigger only counts transitions on
    # non-last beats, and _boundary_fades independently zeroes the last tail.
    if beats and _is_transition(beats[-1]):
        print(f"[assemble] WARNING: last beat {beats[-1].id!r} transition_out "
              f"({beats[-1].transition_out.kind}) has no next beat to transition "
              f"into — dropping it (no tail fade, no mix-path trigger).")
    has_transition = any(_is_transition(b) for b in beats[:-1])

    # Quality gate: draft/preview/standard keep the pure fast path (iterate
    # speed); upload/master finals always run the loudnorm audio pass so they
    # hit ARCHITECTURE_V2's -14 LUFS promise even with nothing else to mix.
    if not (has_music or has_sfx or has_transition):
        if opts.quality in _FINAL_QUALITIES:
            return _fast_concat_normalized(ordered, timeline, opts, out_path)
        return _fast_concat(ordered, timeline, out_path)

    print(f"[assemble] mix path: music={len(timeline.mix.music)} "
          f"sfx={sum(len(b.sfx) for b in beats)} "
          f"transitions={sum(1 for b in beats[:-1] if _is_transition(b))}")

    temps: list[Path] = []
    try:
        video_track = _build_video_track(timeline, beat_files, opts, out_path, temps)
        mix_raw = _build_audio_mix(timeline, beat_files, opts, out_path, temps)
        _mux_final(video_track, mix_raw, timeline, opts, out_path)
    finally:
        for t in temps:
            try:
                t.unlink()
            except OSError:
                pass

    _postcondition(out_path, timeline.duration, _scaled_tolerance(len(ordered)))
    _verify_audio_stream(out_path)
    return out_path


# ─── fast path (Phase-1 parity) ────────────────────────────────────────────

def _fast_concat(ordered: list[Path], timeline: Timeline, out_path: Path) -> Path:
    """Stream-copy concat of the beat MP4s (video + their own VO audio). No
    re-encode, no mix graph — the iterate-speed path."""
    list_file = out_path.parent / f".{out_path.stem}_concat.txt"
    _concat_list(ordered, list_file)
    cmd = ["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
           "-c", "copy", "-movflags", "+faststart", str(out_path)]
    try:
        _run(cmd, out_path, "fast concat")
    finally:
        try:
            list_file.unlink()
        except OSError:
            pass
    _postcondition(out_path, timeline.duration, _scaled_tolerance(len(ordered)))
    return out_path


def _fast_concat_normalized(ordered: list[Path], timeline: Timeline,
                            opts: "RenderOpts", out_path: Path) -> Path:
    """Quality-gated fast path for FINAL tiers (upload/master): the VIDEO is
    still stream-copy concatenated (fast, no re-encode), but the concatenated
    audio is re-encoded through the SAME two-pass loudnorm the mix path uses so
    finals land at `mix.target_lufs` (ARCHITECTURE_V2's -14 LUFS promise). No
    mix graph is built — there's nothing to mix, only to normalize."""
    tmp = out_path.parent
    combined = tmp / f".{out_path.stem}_fastcat.mp4"
    list_file = tmp / f".{out_path.stem}_concat.txt"
    _concat_list(ordered, list_file)
    try:
        # 1. stream-copy concat (video + the beats' own VO audio), no re-encode.
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
              "-c", "copy", "-movflags", "+faststart", str(combined)],
             out_path, "fast concat (pre-loudnorm)")
        # 2. copy the video, re-encode ONLY the audio through loudnorm.
        _, abitrate = codec_args(opts.quality, opts.gpu)
        ln = _loudnorm_apply_arg(timeline, opts, combined)
        _run(["ffmpeg", "-y", "-i", str(combined), "-map", "0:v", "-map", "0:a",
              "-c:v", "copy", "-af", ln, "-c:a", "aac", "-b:a", abitrate,
              "-ar", "48000", "-movflags", "+faststart", str(out_path)],
             out_path, "fast concat loudnorm mux")
    finally:
        for t in (combined, list_file):
            try:
                t.unlink()
            except OSError:
                pass
    _postcondition(out_path, timeline.duration, _scaled_tolerance(len(ordered)))
    _verify_audio_stream(out_path)
    return out_path


# ─── video track ───────────────────────────────────────────────────────────

def _boundary_fades(beats: list[IRBeat]) -> list[tuple[float, float]]:
    """Per-beat `(fade_in, fade_out)` durations from the dip-to-black model:
    a beat's own non-cut `transition_out.dur` splits in half between its tail
    (fade-out) and the NEXT beat's head (fade-in).

    The LAST beat's tail fade is forced to 0: its `transition_out` would fade
    into a next beat that doesn't exist, so honouring it would dip the finale
    to black. (assemble() already warns and drops it from the mix-path
    trigger; this is the defensive twin so a last-beat transition can never
    produce a tail fade even when the mix path is reached for other reasons.)"""
    def half(b: IRBeat) -> float:
        t = b.transition_out
        if t is not None and t.kind != "cut" and t.dur > 0:
            return t.dur / 2.0
        return 0.0

    last = len(beats) - 1
    fades: list[tuple[float, float]] = []
    for i, b in enumerate(beats):
        fade_in = half(beats[i - 1]) if i > 0 else 0.0
        fade_out = 0.0 if i == last else half(b)
        fades.append((fade_in, fade_out))
    return fades


def _build_video_track(timeline: Timeline, beat_files: dict[str, Path],
                       opts: "RenderOpts", out_path: Path,
                       temps: list[Path]) -> Path:
    """A single video-only track for the edit. No transitions -> one
    concat-copy of the beat videos. With transitions -> per-beat video-only
    segments (stream-copied, or re-encoded with dip-to-black fades only for the
    beats adjacent to a boundary), concat-copied together."""
    beats = timeline.beats
    ordered = [beat_files[b.id] for b in beats]
    fades = _boundary_fades(beats)
    tmp = out_path.parent

    if not any(fi or fo for fi, fo in fades):
        vtrack = tmp / f".{out_path.stem}_vtrack.mp4"
        temps.append(vtrack)
        list_file = tmp / f".{out_path.stem}_vconcat.txt"
        _concat_list(ordered, list_file)
        temps.append(list_file)
        _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
              "-map", "0:v", "-c:v", "copy", "-an", "-movflags", "+faststart",
              str(vtrack)], out_path, "video concat")
        return vtrack

    segs: list[Path] = []
    for b, (fade_in, fade_out) in zip(beats, fades):
        src = beat_files[b.id]
        seg = tmp / f".{out_path.stem}_vseg_{b.id}.mp4"
        temps.append(seg)
        if fade_in or fade_out:
            _reencode_fade_segment(src, seg, b.duration, fade_in, fade_out,
                                   timeline.design, opts, out_path)
        else:
            _run(["ffmpeg", "-y", "-i", str(src), "-map", "0:v",
                  "-c:v", "copy", "-an", str(seg)], out_path, "video copy segment")
        segs.append(seg)

    vtrack = tmp / f".{out_path.stem}_vtrack.mp4"
    temps.append(vtrack)
    list_file = tmp / f".{out_path.stem}_vconcat.txt"
    _concat_list(segs, list_file)
    temps.append(list_file)
    _run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", str(list_file),
          "-c", "copy", "-an", "-movflags", "+faststart", str(vtrack)],
         out_path, "video segment concat")
    return vtrack


def _probe_segment_duration(path: Path) -> float | None:
    """Actual container duration of a rendered segment (seconds), or None if
    ffprobe fails/returns nothing parseable. Used to anchor the tail fade to
    the segment's REAL length rather than the IR's nominal beat duration —
    render_beat's `-t` and AAC priming can leave the encoded segment a frame
    or two off the IR value, and a fade-out anchored to the IR duration would
    then start slightly early or late relative to the actual last frame."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def _reencode_fade_segment(src: Path, dst: Path, dur: float, fade_in: float,
                           fade_out: float, design, opts: "RenderOpts",
                           out_path: Path) -> None:
    """Re-encode one beat video (audio dropped) with dip-to-black fades. Filter
    strings come from the graph AST (`FilterNode.render_filter`), not templates.

    The tail fade is anchored to the segment's ACTUAL probed duration (falling
    back to the IR `dur` on probe failure), and the encode pins the same
    `VIDEO_TIMESCALE` as render_beat so this re-encoded segment shares a
    timebase with the stream-copied segments it's concatenated with."""
    nodes: list[FilterNode] = []
    if fade_in > 0:
        nodes.append(FilterNode("fade", args={"t": "in", "st": 0.0,
                                              "d": round(fade_in, 3), "color": "black"}))
    if fade_out > 0:
        actual = _probe_segment_duration(src)
        anchor = actual if actual is not None else dur
        st = round(max(0.0, anchor - fade_out), 3)
        nodes.append(FilterNode("fade", args={"t": "out", "st": st,
                                              "d": round(fade_out, 3), "color": "black"}))
    vf = ",".join(n.render_filter() for n in nodes)
    vcodec, _ = codec_args(opts.quality, opts.gpu)
    _run(["ffmpeg", "-y", "-i", str(src), "-an", "-vf", vf, *vcodec,
          "-r", str(design.fps),
          "-video_track_timescale", str(VIDEO_TIMESCALE),
          "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
          str(dst)], out_path, f"fade re-encode {src.name}")


# ─── audio mix graph ───────────────────────────────────────────────────────

def _vo_stem_path(beat_file: Path) -> Path:
    """`render_beat` drops `<beat>_vo_stem.wav` next to each beat MP4."""
    return beat_file.with_name(beat_file.stem + "_vo_stem.wav")


def _extract_vo_stem(beat_file: Path, tmp: Path, out_path: Path,
                     temps: list[Path]) -> Path:
    """Fallback when a beat's VO stem is absent (e.g. the MP4 came straight
    from the cache, which stores only the video): pull the audio back out of
    the beat MP4, with a warning."""
    print(f"[assemble] WARNING: VO stem missing for {beat_file.name}; "
          f"extracting audio from the beat MP4 (fallback).")
    dst = tmp / f".{out_path.stem}_voext_{beat_file.stem}.wav"
    temps.append(dst)
    _run(["ffmpeg", "-y", "-i", str(beat_file), "-vn", "-ac", "1",
          "-ar", "48000", str(dst)], out_path, f"VO stem extract {beat_file.name}")
    return dst


def _build_audio_mix(timeline: Timeline, beat_files: dict[str, Path],
                     opts: "RenderOpts", out_path: Path,
                     temps: list[Path]) -> Path:
    """Build the full mix `-filter_complex` and render it to a float-PCM raw
    wav spanning the whole edit (pre-loudnorm)."""
    graph = Graph()
    inputs = InputList()
    tmp = out_path.parent
    beats = timeline.beats
    placements = {p.beat_id: p.t0 for p in timeline.placements}

    # 1. VO bus: every stem delayed to its beat start, summed.
    vo_labels: list[str] = []
    for b in beats:
        stem = _vo_stem_path(beat_files[b.id])
        if not stem.exists():
            stem = _extract_vo_stem(beat_files[b.id], tmp, out_path, temps)
        idx = inputs.add(["-i", str(stem)])
        lbl = graph.new_label("vo")
        graph.add(vo_stem_chain(f"{idx}:a", lbl, placements[b.id]))
        vo_labels.append(lbl)
    vo_sum = graph.new_label("vosum")
    graph.add(amix_sum_node(vo_labels, vo_sum))

    # 2. Fan the VO bus out: one final-mix tap + one sidechain key per ducked
    #    span. apad each key so it never runs short under sidechaincompress.
    ducked = [s for s in timeline.mix.music if s.duck]
    if ducked:
        taps = [graph.new_label("vofin")] + [graph.new_label("vok") for _ in ducked]
        graph.add(asplit_node(vo_sum, taps))
        vo_final, raw_keys = taps[0], taps[1:]
        keys: list[str] = []
        for k in raw_keys:
            kp = graph.new_label("vokp")
            graph.add(FilterNode("apad", inputs=[k], outputs=[kp]))
            keys.append(kp)
    else:
        vo_final, keys = vo_sum, []

    # 3. Music spans: seek + trim + gain/fade + place; duck against a VO key.
    music_labels: list[str] = []
    ki = 0
    for span in timeline.mix.music:
        span_len = max(0.0, span.t1 - span.t0)
        flags: list[str] = []
        if span.offset > 0:
            flags += ["-ss", f"{span.offset:.3f}"]
        flags += ["-t", f"{span_len:.3f}", "-i", span.src]
        idx = inputs.add(flags)
        pre = graph.new_label("mus")
        graph.add(music_span_chain(
            f"{idx}:a", pre, span_len=span_len, gain_db=span.gain_db,
            fade_in=span.fade_in, fade_out=span.fade_out, delay_t=span.t0))
        if span.duck:
            out = graph.new_label("musd")
            graph.add(sidechain_duck_node(pre, keys[ki], out, timeline.mix.duck))
            ki += 1
            music_labels.append(out)
        else:
            music_labels.append(pre)

    # 4. SFX one-shots: gain + place at placement.t0 + sfx.t. Each SFX is
    #    capped with atrim so a clip that would naturally run past the edit end
    #    can't extend the mixed audio (and thus the muxed output) beyond the
    #    video track — max length = timeline total minus the SFX's absolute
    #    anchor.
    total = timeline.duration
    sfx_labels: list[str] = []
    for b in beats:
        for s in b.sfx:
            anchor = placements[b.id] + s.t
            idx = inputs.add(["-i", s.src])
            lbl = graph.new_label("sfx")
            graph.add(sfx_chain(f"{idx}:a", lbl, gain_db=s.gain_db,
                                delay_t=anchor, max_len=max(0.0, total - anchor)))
            sfx_labels.append(lbl)

    # 5. Sum every bus. A single input (e.g. transitions-only, no music/sfx)
    #    needs no amix node.
    final_inputs = [vo_final, *music_labels, *sfx_labels]
    if len(final_inputs) == 1:
        mix_out = final_inputs[0]
    else:
        mix_out = graph.new_label("mix")
        graph.add(amix_sum_node(final_inputs, mix_out))

    mix_raw = tmp / f".{out_path.stem}_mixraw.wav"
    temps.append(mix_raw)
    _run(["ffmpeg", "-y", *inputs.args(), "-filter_complex", graph.render(),
          "-map", f"[{mix_out}]", "-c:a", "pcm_f32le", "-ar", "48000",
          str(mix_raw)], out_path, "audio mix")
    return mix_raw


# ─── loudness + mux ────────────────────────────────────────────────────────

_LOUDNORM_JSON_RE = re.compile(r'\{[^{}]*"input_i"[^{}]*\}', re.DOTALL)


def _limiter_prefix(true_peak_db: float) -> str:
    """A documented `alimiter` node (comma-terminated so it prefixes a
    filterchain) capping the summed bus to the true-peak target as a LINEAR
    amplitude (`db_to_linear(true_peak_db)`; e.g. -1 dBTP -> ~0.891).

    It sits BEFORE loudnorm in BOTH the measure and the apply passes so heavy
    VO+music+SFX overlap can't drive the loudnorm input into clipping, and —
    critically — loudnorm measures the exact post-limiter signal it will
    normalize, keeping the two passes on one identical chain for predictable
    output. `measure_loudness()` (ground-truth diagnostics on a finished file)
    deliberately does NOT use this prefix."""
    return f"alimiter=limit={round(db_to_linear(true_peak_db), 6)},"


def _loudnorm_measure(audio: Path, target_lufs: float, true_peak: float,
                      *, prefix: str = "") -> dict:
    """loudnorm pass 1: measure the input's loudness (JSON to stderr). `prefix`
    (e.g. the alimiter chain) is prepended to the `-af` filterchain so the
    measure pass sees the same signal the apply pass will normalize."""
    r = subprocess.run(
        ["ffmpeg", "-i", str(audio), "-af",
         f"{prefix}loudnorm=I={target_lufs}:TP={true_peak}:LRA={_LOUDNORM_LRA}:print_format=json",
         "-f", "null", "-"],
        capture_output=True, text=True,
    )
    m = _LOUDNORM_JSON_RE.search(r.stderr or r.stdout)
    if not m:
        raise RuntimeError(
            "assemble: loudnorm measure pass produced no JSON "
            f"(rc={r.returncode}); tail: {(r.stderr or r.stdout)[-400:]}")
    return json.loads(m.group(0))


def _loudnorm_apply_arg(timeline: Timeline, opts: "RenderOpts",
                        mix_raw: Path) -> str:
    """The `-af` argument for the mux: an `alimiter` headroom cap (see
    `_limiter_prefix`) followed by loudnorm. Non-draft = two-pass (measured
    values + linear=true, the legacy pattern), where the measure pass is fed
    the SAME limiter+loudnorm chain; draft = single dynamic pass."""
    target, tp = timeline.mix.target_lufs, timeline.mix.true_peak_db
    limiter = _limiter_prefix(tp)
    base = f"{limiter}loudnorm=I={target}:TP={tp}:LRA={_LOUDNORM_LRA}"
    if opts.quality in _DRAFT_QUALITIES:
        return base
    m = _loudnorm_measure(mix_raw, target, tp, prefix=limiter)
    return (f"{base}:measured_I={m['input_i']}:measured_TP={m['input_tp']}:"
            f"measured_LRA={m['input_lra']}:measured_thresh={m['input_thresh']}:"
            f"offset={m['target_offset']}:linear=true")


def _mux_final(video_track: Path, mix_raw: Path, timeline: Timeline,
               opts: "RenderOpts", out_path: Path) -> None:
    """Normalize the raw mix (loudnorm) and mux it over the copied video."""
    _, abitrate = codec_args(opts.quality, opts.gpu)
    ln = _loudnorm_apply_arg(timeline, opts, mix_raw)
    _run(["ffmpeg", "-y", "-i", str(video_track), "-i", str(mix_raw),
          "-map", "0:v", "-map", "1:a", "-c:v", "copy",
          "-af", ln, "-c:a", "aac", "-b:a", abitrate, "-ar", "48000",
          "-movflags", "+faststart", str(out_path)], out_path, "mux + loudnorm")


# ─── postconditions / measurement ──────────────────────────────────────────

def _verify_audio_stream(path: Path) -> None:
    """VQ-AUDIO precondition-of-a-mix: the final file must carry an audio
    stream (a mixed edit with no audio track means the graph silently
    dropped the mix)."""
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a",
         "-show_entries", "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    if "audio" not in (r.stdout or ""):
        raise RuntimeError(
            f"VQ-AUDIO: {path} has no audio stream after the mix pass")


def measure_loudness(path: str | Path, *, target_lufs: float = -14.0,
                     true_peak: float = -1.0) -> dict:
    """Run a loudnorm measure pass over `path` and return the parsed JSON
    (``input_i`` = integrated LUFS, ``input_tp`` = true peak, ...). Exposed for
    integration tests and future VQ-AUDIO loudness gating."""
    return _loudnorm_measure(Path(path), target_lufs, true_peak)
