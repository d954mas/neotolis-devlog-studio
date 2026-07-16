"""Per-beat render: one ffmpeg subprocess -> beat MP4 + sibling VO stem wav.

Consumes ONLY the IR (`IRBeat`) + `Design` (for resolution / bg color) — no
timing is re-derived from words here; compile already resolved every t0/t1.

Ported v1 invariants (see legacy common/devlog/render/compose_ffmpeg.py):

* setpts PTS-SHIFT (the 22-blind-iteration bug): every overlay source is
  `setpts=PTS+t0/TB` so its frames land at output time t0..t1 aligned with
  the overlay's `enable=between(t,t0,t1)` window. Without it, overlays whose
  t0>0 are already past EOF when enable fires and `eof_action=pass` silently
  drops them.
* eof_action=pass on every overlay + NO -shortest: a looped overlay PNG is
  shorter than the beat; eof_action=pass keeps the bg flowing after its
  window, and `-t duration` (never -shortest) caps to the VO length so an
  overlay EOF can't truncate the whole beat.
* xfade offset math (graph.build_xfade_chain), scene input matrix
  (graph.scene_input_args), Ken Burns time-based scale expression, the
  draft/preview/standard/upload/master x CPU/NVENC codec presets, and the
  *_ffmpeg_error.txt debug dump on non-zero rc.

Chunk resolution seam: `IROverlayItem` carries only `chunk_index`; the raster
renderer needs the source `Chunk`. The cli/compile integration wires a
resolver via `set_chunk_resolver`; tests inject one (and usually patch
`render_chunk_png`).
"""
from __future__ import annotations

import os
import shutil
import subprocess
import tempfile
from collections.abc import Callable
from pathlib import Path
from typing import TYPE_CHECKING

from dlstudio.ir import IRBeat, IROverlayItem, IRSegment, Timeline
from dlstudio.model import Chunk, Design
from dlstudio.render.graph import (
    XFADE_TRANSITION,
    Chain,
    FilterNode,
    Graph,
    InputList,
    build_xfade_chain,
    color_source,
    scene_input_args,
)
from dlstudio.render.raster import render_caption_png, render_chunk_png

if TYPE_CHECKING:                      # avoid a package<->submodule import cycle
    from dlstudio.render import RenderOpts

KB_ZOOM = 0.06                     # Ken Burns zoom-over-duration factor (legacy)
DEFAULT_VERIFY_TOL = 0.35          # local fallback duration tolerance (s)

# Common MP4 video timescale (ticks/sec) pinned on EVERY beat encode. assemble
# stream-copies non-boundary beats but RE-ENCODES the beats adjacent to a
# dip-to-black transition (assemble._reencode_fade_segment); a re-encode
# invents a fresh timebase, so a copied beat and a re-encoded beat could land
# in the same concat with different timescales and trip the concat demuxer
# (non-monotonic DTS / timestamp jitter). Pinning the SAME timescale here AND
# in _reencode_fade_segment keeps every segment on one timebase so copy+
# re-encode concat is provably clean. 12800 is ffmpeg's conventional MP4 video
# timescale and is shared via assemble importing this constant.
VIDEO_TIMESCALE = 12800


# ─── chunk resolver seam ───────────────────────────────────────────────────

_chunk_resolver: Callable[[str, int], Chunk] | None = None


def set_chunk_resolver(fn: Callable[[str, int], Chunk] | None) -> None:
    """Register how `(beat_id, chunk_index)` maps to the source `Chunk` that
    render.raster rasterises. cli/compile wire this at integration; tests
    inject a stub. Without it, a beat that has overlays raises a clear error."""
    global _chunk_resolver
    _chunk_resolver = fn


def _resolve_chunk(beat_id: str, chunk_index: int) -> Chunk:
    if _chunk_resolver is None:
        raise RuntimeError(
            "no chunk resolver set: render_beat needs IROverlayItem.chunk_index "
            "-> Chunk to rasterise overlays. Call render.beat.set_chunk_resolver()"
            " (cli/compile wires this; tests inject a stub)."
        )
    return _chunk_resolver(beat_id, chunk_index)


# ─── ffprobe helper ────────────────────────────────────────────────────────

# Keyed by (path, size, mtime_ns) -- NOT path alone. A path-only key goes
# stale within a long-lived process (e.g. a future watch mode) the moment a
# source file is edited on disk: same path, different bytes, wrong cached
# duration served forever. Keying on identity (size+mtime_ns) makes an edited
# file a cache miss, same as dlstudio.cache/compile.probe's asset identity.
_duration_cache: dict[tuple[str, int, int], float] = {}


def _probe_duration(src: str) -> float:
    try:
        st = os.stat(src)
        key = (src, st.st_size, st.st_mtime_ns)
    except OSError:
        key = (src, -1, -1)
    if key in _duration_cache:
        return _duration_cache[key]
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", src],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    try:
        dur = float(r.stdout.strip())
    except ValueError:
        dur = 0.0
    _duration_cache[key] = dur
    return dur


# ─── codec presets (port of legacy _codec_args) ────────────────────────────

def codec_args(quality: str, gpu: bool) -> tuple[list[str], str]:
    """(video-codec argv, audio bitrate) for a quality preset x CPU/NVENC.

    Ports legacy compose_ffmpeg._codec_args: draft/preview/standard/upload/
    master, libx264 (CPU) or h264_nvenc (GPU). NVENC uses -rc vbr + -cq;
    CPU uses -crf. pix_fmt yuv420p everywhere."""
    q = quality or "standard"

    def _v(preset_cpu: str, preset_gpu: str, cq: int, crf: int) -> list[str]:
        return [
            "-c:v", "h264_nvenc" if gpu else "libx264",
            "-preset", preset_gpu if gpu else preset_cpu,
            *(["-rc", "vbr"] if gpu else []),
            *(["-cq", str(cq)] if gpu else ["-crf", str(crf)]),
            "-pix_fmt", "yuv420p",
        ]

    if q == "draft":
        return _v("ultrafast", "p1", 28, 28), "160k"
    if q == "preview":
        return _v("veryfast", "p3", 24, 22), "192k"
    if q == "master":
        return _v("slow", "p5", 16, 16), "320k"
    # standard / upload: old non-draft baseline; upload gets audio headroom
    return _v("medium", "p4", 20, 18), ("256k" if q == "upload" else "192k")


# ─── ease expressions (for anim props) ─────────────────────────────────────

def _ease(ease: str, p: str) -> str:
    """Eased fraction (0..1) as an ffmpeg expression, given progress expr `p`."""
    if ease == "linear":
        return f"({p})"
    if ease == "in":
        return f"(pow({p},3))"
    if ease == "out":
        return f"(1-pow(1-({p}),3))"
    if ease == "in_out":
        return f"(if(lt({p},0.5),4*pow({p},3),1-pow(-2*({p})+2,3)/2))"
    if ease == "back_out":
        return f"(1+2.70158*pow(({p})-1,3)+1.70158*pow(({p})-1,2))"
    return f"({p})"


def _progress(t_var: str, start: float, length: float) -> str:
    """clip((t_var - start)/length, 0, 1) — held at the endpoints."""
    length = max(length, 1e-4)
    return f"clip(({t_var}-{start:.4f})/{length:.4f},0,1)"


def _value_expr(start: float, end: float, ease: str, prog: str) -> str:
    return f"({start:.5f}+({end - start:.5f})*{_ease(ease, prog)})"


def _find_anim(overlay: IROverlayItem, prop: str):
    for a in overlay.anims:
        if a.prop == prop:
            return a
    return None


# ─── background (scene segment) construction ───────────────────────────────

def _bg_color(design: Design) -> str:
    try:
        hexv = design.palette.color("bg")
    except Exception:
        hexv = "#000000"
    hexv = hexv.lstrip("#")
    if len(hexv) == 3:
        # 3->6 digit shorthand expansion (e.g. "#abc" -> "aabbcc"), duplicated
        # from render.raster._util.hex_to_rgb -- kept inline rather than
        # imported so beat.py doesn't reach into raster/ (layering: raster is
        # owned separately and beat.py must not depend on it).
        hexv = "".join(ch * 2 for ch in hexv)
    if len(hexv) == 6:
        return "0x" + hexv.upper()
    return "0x000000"


def _normalize_segment(idx: int, seg: IRSegment, seg_dur: float,
                       pad_needed: float, design: Design,
                       bg_color: str, label: str) -> Chain:
    """Scale/crop the raw scene input to design resolution, freeze-pad short
    sources, apply Ken Burns, force yuv420p. Ports legacy
    `_scene_normalize_filter`."""
    w, h = design.resolution
    fps = design.fps
    filters: list[FilterNode] = []

    # tpad must precede scale so there are native frames to clone.
    if pad_needed > 0.01:
        filters.append(FilterNode("tpad", args={"stop_mode": "clone",
                                                 "stop_duration": pad_needed}))

    ken = seg.ken_burns and seg_dur > 2.0
    if seg.fit == "contain" and not ken:
        filters.append(FilterNode("scale", positional=[w, h],
                                  args={"force_original_aspect_ratio": "decrease"}))
        filters.append(FilterNode("pad", positional=[w, h, "(ow-iw)/2", "(oh-ih)/2"],
                                  args={"color": bg_color}))
    elif ken:
        # cover-fit first, then time-based zoom, then re-crop to WxH.
        filters.append(FilterNode("scale", positional=[w, h],
                                  args={"force_original_aspect_ratio": "increase"}))
        z = f"(1.0+{KB_ZOOM}*t/{seg_dur:.3f})"
        filters.append(FilterNode("scale", args={"w": f"iw*{z}", "h": f"ih*{z}",
                                                  "eval": "frame"}))
        filters.append(FilterNode("crop", positional=[w, h]))
    else:  # cover
        filters.append(FilterNode("scale", positional=[w, h],
                                  args={"force_original_aspect_ratio": "increase"}))
        filters.append(FilterNode("crop", positional=[w, h]))

    filters.append(FilterNode("setsar", positional=[1]))
    filters.append(FilterNode("fps", positional=[fps]))
    filters.append(FilterNode("format", positional=["yuv420p"]))
    return Chain(inputs=[f"{idx}:v"], filters=filters, outputs=[label])


def _build_background(beat: IRBeat, design: Design, graph: Graph,
                      inputs: InputList, bg_color: str) -> str:
    """Register scene inputs, normalize each, chain xfades. Returns bg label."""
    w, h = design.resolution
    fps = design.fps
    audio_dur = beat.duration

    # No scenes at all -> solid color base across the whole beat.
    if not beat.segments:
        return color_source(graph, bg_color, w, h, audio_dur, fps,
                            graph.new_label("bg"))

    # Renderable segments: an optional leading color gap, then real scenes.
    # Each entry: (is_color, ir_seg_or_None, seg_dur)
    render: list[tuple[bool, IRSegment | None, float]] = []
    gap = beat.segments[0].t0
    if gap > 0.05:
        render.append((True, None, gap))
    for s in beat.segments:
        render.append((False, s, s.t1 - s.t0))

    n = len(render)
    # Per-boundary crossfade dur/transition (boundary i is between i and i+1).
    b_durs: list[float] = []
    b_trans: list[str] = []
    for i in range(n - 1):
        _, left_ir, _ = render[i]
        if left_ir is not None and left_ir.xfade is not None:
            tr = left_ir.xfade
            if tr.kind == "cut":
                b_durs.append(0.0)
                b_trans.append("fade")
            else:
                b_durs.append(tr.dur)
                b_trans.append(XFADE_TRANSITION.get(tr.kind, "fade"))
        else:
            b_durs.append(design.crossfade_dur)
            b_trans.append("fade")

    seg_durs = [d for _, _, d in render]
    labels: list[str] = []
    for i, (is_color, ir_seg, seg_dur) in enumerate(render):
        # eff_dur adds the crossfade tail INTO the next segment (material to
        # fade with); last segment gets no tail.
        eff_dur = seg_dur + (b_durs[i] if i < n - 1 else 0.0)
        if is_color:
            labels.append(color_source(graph, bg_color, w, h, eff_dur, fps,
                                       graph.new_label("gap")))
            continue
        assert ir_seg is not None
        src_dur = _probe_duration(ir_seg.src) if ir_seg.kind == "video" else None
        args, pad_needed = scene_input_args(
            kind=ir_seg.kind, src=ir_seg.src, offset=ir_seg.offset,
            eff_dur=eff_dur, loop=ir_seg.loop, source_duration=src_dur,
        )
        idx = inputs.add(args)
        lbl = graph.new_label("s")
        graph.add(_normalize_segment(idx, ir_seg, seg_dur, pad_needed,
                                     design, bg_color, lbl))
        labels.append(lbl)

    return build_xfade_chain(graph, labels, seg_durs, b_durs, b_trans)


# ─── overlay construction ──────────────────────────────────────────────────

def _overlay_source_chain(idx: int, overlay: IROverlayItem, dur: float,
                          design: Design, out_label: str) -> Chain:
    """Overlay PNG -> format=rgba, scale anim, opacity/entrance fades,
    PTS-shift. Ken Burns/scale via time-based scale expr; opacity via the
    fast `fade` alpha filter (legacy proved fade >> geq)."""
    w, h = design.resolution
    filters: list[FilterNode] = [FilterNode("format", positional=["rgba"])]

    if _find_anim(overlay, "rotate") is not None:
        raise NotImplementedError(
            "rotate anim is not supported in Phase 1 "
            f"(overlay chunk_index={overlay.chunk_index}); deferred to Phase 2."
        )

    # scale anim: local stream time (0..dur). scale up then re-crop to WxH so
    # the full-frame overlay stays centered (matches legacy plate punch-in).
    sa = _find_anim(overlay, "scale")
    if sa is not None:
        local_start = sa.t0 - overlay.t0
        prog = _progress("t", local_start, sa.t1 - sa.t0)
        val = _value_expr(sa.start, sa.end, sa.ease, prog)
        filters.append(FilterNode("scale", args={"w": f"iw*{val}",
                                                  "h": f"ih*{val}",
                                                  "eval": "frame"}))
        filters.append(FilterNode("crop", positional=[w, h]))

    # opacity anim (local time) drives fades if present; else default entrance/
    # exit fades derived from transition_in.
    oa = _find_anim(overlay, "opacity")
    if oa is not None:
        st = max(0.0, oa.t0 - overlay.t0)
        d = max(oa.t1 - oa.t0, 0.001)
        direction = "in" if oa.start <= oa.end else "out"
        filters.append(FilterNode("fade", args={"t": direction, "st": st,
                                                 "d": d, "alpha": 1}))
    else:
        ti = overlay.transition_in
        if ti is not None and ti.kind == "cut":
            fi = 0.001
        elif ti is not None and ti.kind == "fade":
            fi = ti.dur
        else:
            fi = min(0.20, dur * 0.25)
        fo = min(0.20, dur * 0.20)
        fi = max(fi, 0.001)
        fo = max(fo, 0.001)
        filters.append(FilterNode("fade", args={"t": "in", "st": 0.0,
                                                 "d": fi, "alpha": 1}))
        filters.append(FilterNode("fade", args={"t": "out",
                                                 "st": max(0.0, dur - fo),
                                                 "d": fo, "alpha": 1}))

    # PTS-SHIFT invariant: align frames to output time t0..t1.
    filters.append(FilterNode("setpts", positional=[f"PTS+{overlay.t0:.3f}/TB"]))
    return Chain(inputs=[f"{idx}:v"], filters=filters, outputs=[out_label])


def _overlay_position(overlay: IROverlayItem) -> tuple[str, str]:
    """x/y overlay expressions. x/y anims use OUTPUT (main/bg) time, so their
    progress is over absolute beat-relative seconds (not local stream time)."""
    def axis(prop: str) -> str:
        a = _find_anim(overlay, prop)
        if a is None:
            return "0"
        prog = _progress("t", a.t0, a.t1 - a.t0)
        return _value_expr(a.start, a.end, a.ease, prog)

    return axis("x"), axis("y")


def _build_overlays(beat: IRBeat, design: Design, graph: Graph,
                    inputs: InputList, tmp_dir: Path, bg_label: str) -> str:
    """Rasterise each overlay PNG and composite it. Returns final bg label."""
    for overlay in sorted(beat.overlays, key=lambda o: o.z):
        chunk = _resolve_chunk(beat.id, overlay.chunk_index)
        png = tmp_dir / f"ov_{overlay.chunk_index}.png"
        render_chunk_png(chunk, design, png)

        dur = overlay.t1 - overlay.t0
        idx = inputs.add(["-loop", "1", "-t", f"{dur:.3f}", "-i", str(png)])

        src_label = graph.new_label("ov")
        graph.add(_overlay_source_chain(idx, overlay, dur, design, src_label))

        x_expr, y_expr = _overlay_position(overlay)
        out_label = graph.new_label("cb")
        enable = f"between(t,{overlay.t0:.3f},{overlay.t1:.3f})"
        graph.add(FilterNode(
            "overlay",
            args={"x": x_expr, "y": y_expr, "enable": enable,
                  "eof_action": "pass"},
            inputs=[bg_label, src_label],
            outputs=[out_label],
        ))
        bg_label = out_label
    return bg_label


def _build_captions(beat: IRBeat, design: Design, graph: Graph,
                    inputs: InputList, tmp_dir: Path, bg_label: str) -> str:
    """Composite the beat's subtitle phrases (compiled from words when
    `beat.subtitles` is set) ABOVE all chunk overlays. Each caption is a
    full-frame RGBA PNG (raster) with a quick alpha fade in/out and the
    standard PTS-shift/enable-window placement. Returns final label."""
    fade = 0.08
    for i, cap in enumerate(beat.captions):
        png = tmp_dir / f"cap_{i}.png"
        render_caption_png(cap.text, design, png)

        dur = max(cap.t1 - cap.t0, 0.05)
        idx = inputs.add(["-loop", "1", "-t", f"{dur:.3f}", "-i", str(png)])

        src_label = graph.new_label("cap")
        fi = min(fade, dur * 0.4)
        graph.add(Chain(
            inputs=[f"{idx}:v"],
            filters=[
                FilterNode("format", positional=["rgba"]),
                FilterNode("fade", args={"t": "in", "st": 0.0, "d": fi, "alpha": 1}),
                FilterNode("fade", args={"t": "out", "st": max(0.0, dur - fi),
                                         "d": fi, "alpha": 1}),
                # PTS-SHIFT invariant (same as overlays): frames land at t0..t1.
                FilterNode("setpts", positional=[f"PTS+{cap.t0:.3f}/TB"]),
            ],
            outputs=[src_label],
        ))
        out_label = graph.new_label("cc")
        enable = f"between(t,{cap.t0:.3f},{cap.t1:.3f})"
        graph.add(FilterNode(
            "overlay",
            args={"x": 0, "y": 0, "enable": enable, "eof_action": "pass"},
            inputs=[bg_label, src_label],
            outputs=[out_label],
        ))
        bg_label = out_label
    return bg_label


# ─── postcondition ─────────────────────────────────────────────────────────

def _postcondition(path: Path, expected: float) -> None:
    """VQ-SYNC duration postcondition. check.verify_output is fully
    implemented (compile-agent) -- call it directly with this module's
    looser single-beat tolerance (a beat is one ffmpeg encode's worth of
    AAC priming/rounding, not the accumulated concat drift assemble.py has
    to budget for)."""
    from dlstudio.check import verify_output
    verify_output(str(path), expected, tolerance=DEFAULT_VERIFY_TOL)


# ─── main entry ────────────────────────────────────────────────────────────

def render_beat(beat: IRBeat, design: Design, _timeline: Timeline | None,
                opts: "RenderOpts") -> Path:
    """Render one beat to MP4 (+ sibling `<stem>_vo_stem.wav`). Returns MP4.

    One ffmpeg subprocess: background (scene xfade chain) -> overlays
    (composited in z order) -> VO audio (aac). Verifies output duration vs
    `beat.duration` before returning.

    `_timeline` is ACCEPTED BUT IGNORED: render_beat only ever needs the one
    `IRBeat` + `Design` (compile already resolved every t0/t1 onto the beat
    itself; nothing here is re-derived across beat boundaries). It stays in
    the signature -- positionally, third -- only so existing Phase-1 call
    sites that still pass a real `Timeline` object don't break; callers
    should pass `None` (the cli does). Shipping the *whole* Timeline to every
    `-j N` worker process was itself the bug (O(N^2) IPC: N workers each
    pickling all N beats) -- see cli._compose_worker/_render_targets, which
    no longer carry a timeline argument at all. Slated to be dropped from
    this signature entirely in Phase 2."""
    workdir = Path(opts.workdir)
    workdir.mkdir(parents=True, exist_ok=True)
    out_path = workdir / f"{beat.id}.mp4"
    audio_dur = beat.duration
    bg_color = _bg_color(design)

    tmp_dir = Path(tempfile.mkdtemp(prefix="dlstudio_beat_"))
    try:
        graph = Graph()
        inputs = InputList()
        inputs.add(["-i", beat.audio])                 # index 0 == VO audio

        bg_label = _build_background(beat, design, graph, inputs, bg_color)
        bg_label = _build_overlays(beat, design, graph, inputs, tmp_dir, bg_label)
        bg_label = _build_captions(beat, design, graph, inputs, tmp_dir, bg_label)

        filter_complex = graph.render()
        vcodec, abitrate = codec_args(opts.quality, opts.gpu)

        cmd = ["ffmpeg", "-y", *inputs.args(),
               "-filter_complex", filter_complex,
               "-map", f"[{bg_label}]", "-map", "0:a",
               *vcodec,
               # Force 48kHz aac so beats concat cleanly (v1: mismatched
               # sample rates broke the demuxer's packet timing downstream).
               "-c:a", "aac", "-b:a", abitrate, "-ar", "48000",
               "-movflags", "+faststart",
               # Pin a common video timescale so assemble's copy+re-encode
               # concat stays on one timebase (see VIDEO_TIMESCALE).
               "-video_track_timescale", str(VIDEO_TIMESCALE),
               "-color_primaries", "bt709", "-color_trc", "bt709",
               "-colorspace", "bt709",
               # -t caps to VO length; NEVER -shortest (an overlay PNG EOF
               # would otherwise truncate the whole beat).
               "-t", f"{audio_dur:.3f}",
               str(out_path)]

        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
        if r.returncode != 0:
            dbg = out_path.parent / f"{out_path.stem}_ffmpeg_error.txt"
            dbg.write_text(
                "FILTER_COMPLEX:\n" + filter_complex
                + "\n\nCMD:\n" + " ".join(cmd)
                + "\n\nSTDERR:\n" + r.stderr,
                encoding="utf-8",
            )
            raise RuntimeError(f"ffmpeg failed (rc={r.returncode}). Debug: {dbg}")

        # Copy the raw VO wav next to the MP4 for Phase-2 assemble ducking.
        stem_wav = out_path.parent / f"{out_path.stem}_vo_stem.wav"
        try:
            shutil.copyfile(beat.audio, stem_wav)
        except OSError:
            pass

        _postcondition(out_path, audio_dur)
        return out_path
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
