"""Direct ffmpeg beat composition — drop-in replacement for compose.py.

Pipeline: per-chunk PNGs pre-rendered via existing PIL code (plate, overlay,
image), then a single ffmpeg invocation builds the filter graph that:
  - normalizes each scene segment (video or image) to the design resolution
  - chains scenes with xfade transitions (0.6s)
  - overlays each chunk PNG at its time window with fade-in/out
  - applies Ken Burns zoom to image scenes
  - applies plate punch-in animation (1.04 -> 1.0 ease-out cubic)
  - muxes audio + writes MP4

Pros vs MoviePy compose:
  - No Python frame iteration (5-10x faster on 1080p, GPU encoding now useful)
  - One ffmpeg subprocess vs hundreds of Python callbacks
  - GPU encoding (nvenc) finally feeds at full speed

Maintains same on-disk output format and cache key as compose.py — drop-in.
"""
from __future__ import annotations
import json
import math
import subprocess
import tempfile
from pathlib import Path
import numpy as np
from PIL import Image

from devlog.types import Beat, Chunk, Design, Scene
from devlog.cache import get_cached, put_cached
from .plate import make_plate
from .overlay import make_overlay_badge, overlay_label
from .image import make_image_clip
from .effects import vignette


# ─── PNG pre-rendering ────────────────────────────────────────────

def _save_png_rgb(arr: np.ndarray, path: Path) -> None:
    Image.fromarray(arr).save(path)


def _save_png_rgba(arr: np.ndarray, path: Path) -> None:
    Image.fromarray(arr, mode="RGBA").save(path)


def _prerender_chunk_pngs(beat: Beat, design: Design, tmp_dir: Path) -> dict[int, dict]:
    """Render each chunk's visual layer to a PNG (rgb or rgba).
    Returns {chunk_index: {"path": Path, "kind": str, "rgba": bool}}.
    Skips kind=video (those come from the scene system) and overlay with empty text.
    """
    out = {}
    for i, ch in enumerate(beat.chunks):
        info = {"kind": ch.kind, "rgba": False, "path": None}
        if ch.kind == "plate":
            frame = make_plate(ch, design)
            p = tmp_dir / f"chunk_{i}.png"
            _save_png_rgb(frame, p)
            info["path"] = p
        elif ch.kind == "overlay":
            if not ch.text:
                out[i] = info                                   # scene-only chunk, no PNG
                continue
            rgba = make_overlay_badge(ch.text, design,
                                      subtitle=ch.subtitle,
                                      position=ch.position,
                                      style=ch.style)
            p = tmp_dir / f"chunk_{i}.png"
            _save_png_rgba(rgba, p)
            info["path"] = p
            info["rgba"] = True
        elif ch.kind == "image":
            inset_label = ch.label if ch.framed_card else None
            frame = make_image_clip(ch.src, design,
                                    fit=ch.fit,
                                    framed_card=ch.framed_card,
                                    inset_label=inset_label)
            if ch.vignette_overlay:
                pil = Image.fromarray(frame).convert("RGBA")
                pil.alpha_composite(vignette(design))
                frame = np.array(pil.convert("RGB"))
            if ch.label and not ch.framed_card:
                frame = overlay_label(frame, ch.label, design, style=ch.label_style)
            p = tmp_dir / f"chunk_{i}.png"
            _save_png_rgb(frame, p)
            info["path"] = p
        # kind == "video": no pre-render, fed live via scene input
        out[i] = info
    return out


# ─── Scene segment computation (mirrors compose.py) ───────────────

def _merge_scene_segments(chunks_with_time: list[dict],
                          default_scene: Scene | None,
                          audio_dur: float) -> list[tuple[float, float, Scene]]:
    segments: list[tuple[float, float, Scene]] = []
    current_scene = default_scene
    current_start = 0.0
    for ch in chunks_with_time:
        new_scene = ch.get("scene")
        if new_scene:
            same_src = current_scene is not None and new_scene.src == current_scene.src
            if not same_src:
                if current_scene is not None:
                    segments.append((current_start, ch["t_start"], current_scene))
                current_scene = new_scene
                current_start = ch["t_start"]
    if current_scene is not None:
        segments.append((current_start, audio_dur, current_scene))
    return segments


# ─── Filter graph builder ─────────────────────────────────────────

class _Graph:
    """Accumulating ffmpeg filter_complex builder."""
    def __init__(self):
        self.parts: list[str] = []
        self.input_idx = 0

    def add_input(self) -> int:
        i = self.input_idx
        self.input_idx += 1
        return i

    def line(self, s: str) -> None:
        self.parts.append(s)

    def build(self) -> str:
        return ";".join(self.parts)


_duration_cache: dict[str, float] = {}


def _probe_duration(src: str) -> float:
    """Get duration in seconds of a video/image (image returns 0)."""
    if src in _duration_cache:
        return _duration_cache[src]
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", src],
        capture_output=True, text=True,
    )
    try:
        duration = float(r.stdout.strip())
    except ValueError:
        duration = 0.0
    _duration_cache[src] = duration
    return duration


def _scene_input_args(scene: Scene, eff_dur: float) -> tuple[list[str], float]:
    """ffmpeg input flags for one scene segment + pad_needed (seconds to
    freeze-extend if source is shorter than eff_dur).

    For videos shorter than eff_dur (e.g. a 5s animation needed for 6s),
    we still seek+read what's there but ALSO compute how much extra time
    needs to be padded with the last-frame clone in the normalize filter.
    """
    if scene.kind == "video":
        actual_dur = _probe_duration(scene.src)
        # Safety: if offset is past EOF, ffmpeg silently produces no video
        # stream and the whole pipeline silently fails. Clamp + warn.
        if scene.offset >= actual_dur - 0.1:
            print(f"[ff-compose] WARNING: scene offset {scene.offset:.2f}s "
                  f"is past source duration {actual_dur:.2f}s for {scene.src}. "
                  f"Falling back to offset=0.")
            scene = Scene(kind=scene.kind, src=scene.src, offset=0.0,
                          fit=scene.fit, loop=scene.loop,
                          ken_burns=scene.ken_burns, kb_zoom=scene.kb_zoom)
        available = max(0.0, actual_dur - scene.offset)
        if scene.loop:
            # Source explicitly marks "loop this": -stream_loop -1 keeps reading
            args = ["-stream_loop", "-1", "-ss", f"{scene.offset:.3f}",
                    "-t", f"{eff_dur:.3f}", "-i", scene.src]
            pad_needed = 0.0
        elif available < eff_dur - 0.05:
            # Source shorter than needed: read whole tail, freeze last frame for remainder
            args = ["-ss", f"{scene.offset:.3f}", "-i", scene.src]
            pad_needed = eff_dur - available
        else:
            # Source long enough: trim to eff_dur
            args = ["-ss", f"{scene.offset:.3f}", "-t", f"{eff_dur:.3f}", "-i", scene.src]
            pad_needed = 0.0
        return args, pad_needed
    elif scene.kind == "image":
        return ["-loop", "1", "-t", f"{eff_dur:.3f}", "-i", scene.src], 0.0
    raise ValueError(f"Unknown scene kind: {scene.kind}")


def _scene_normalize_filter(idx: int, seg_dur: float, eff_dur: float,
                            design: Design, scene: Scene, label: str,
                            pad_needed: float = 0.0) -> str:
    """Filter that scales/crops scene input to design size + applies Ken Burns
    if image with ken_burns enabled.

    If `pad_needed > 0`, the source video is shorter than eff_dur. We use
    `tpad=stop_mode=clone:stop_duration=pad_needed` to freeze the last frame
    for the remainder. Matches MoviePy compose.py freeze-last-frame behavior.

    Inputs: [idx:v]
    Output: [label]  — RGB stream at design resolution, eff_dur seconds long
    """
    W, H = design.W, design.H
    fps = design.fps
    base = f"[{idx}:v]"
    chain = []
    # If source is short, freeze last frame to fill the remainder. Must come
    # BEFORE scale/crop so we have native source frames to clone.
    if pad_needed > 0.01:
        chain.append(f"tpad=stop_mode=clone:stop_duration={pad_needed:.3f}")
    if scene.kind == "image" and scene.ken_burns and seg_dur > 2.0:
        # Ken Burns: scale up over time, crop centered. Use zoompan? Simpler: scale+crop with expr.
        z = scene.kb_zoom
        # zoom factor: 1.0 -> 1.0+z linearly over seg_dur
        chain.append(
            f"scale=w='if(gte(t,0),iw*(1.0+{z}*t/{seg_dur:.3f}),iw)'"
            f":h='if(gte(t,0),ih*(1.0+{z}*t/{seg_dur:.3f}),ih)':eval=frame"
        )
        # After zoom, ensure cover-crop to W×H
        chain.append(f"crop={W}:{H}")
    else:
        # Cover-crop: scale to cover then center-crop
        chain.append(f"scale={W}:{H}:force_original_aspect_ratio=increase")
        chain.append(f"crop={W}:{H}")
    chain.append(f"setsar=1")
    chain.append(f"fps={fps}")
    # Force opaque yuv420p — scenes are full-bleed, no alpha needed.
    # Keeping rgba here caused chunk overlays to render semi-transparent.
    chain.append(f"format=yuv420p")
    return base + ",".join(chain) + f"[{label}]"


def _chain_xfade(scene_labels: list[str], seg_durs: list[float],
                 crossfade_dur: float, design: Design) -> tuple[str, str]:
    """Build xfade chain across all scene normalized streams.

    Each xfade's `offset` = sum of seg_durs[0..i-1] (the OUTPUT timestamp
    where the transition begins). The transition then runs for
    `crossfade_dur` seconds — matching MoviePy's behaviour where scene N
    starts at chunk_N.t_start with a 0.6s fade-in overlapping scene N-1's
    fade-out.

    Returns (filter_string, final_label).
    """
    if len(scene_labels) == 1:
        return "", scene_labels[0]
    parts = []
    prev_label = scene_labels[0]
    cumulative = 0.0
    for i in range(1, len(scene_labels)):
        cumulative += seg_durs[i - 1]                          # transition starts here in output time
        next_label = scene_labels[i]
        out_label = f"xf{i}"
        parts.append(
            f"[{prev_label}][{next_label}]xfade=transition=fade:"
            f"duration={crossfade_dur:.3f}:offset={cumulative:.3f}[{out_label}]"
        )
        prev_label = out_label
    return ";".join(parts), prev_label


def _chunk_overlay_filter(bg_label: str, chunk_input_idx: int,
                          t_start: float, t_end: float,
                          fade_in: float, fade_out: float,
                          out_label: str,
                          rgba: bool, ken_burns: bool, design: Design,
                          punch_in: bool) -> str:
    """Build the per-chunk overlay filter chain.

    Applies (if rgba) format=rgba, optional plate punch-in scale, fade-in/out
    via alpha (rgba) or fade filter (rgb), then overlay onto bg with `enable`.
    Returns one big chain ending in [out_label].
    """
    W, H = design.W, design.H
    dur = t_end - t_start
    src = f"[{chunk_input_idx}:v]"
    chain = []
    # No explicit format conversion — PIL-saved PNG is already RGBA. Letting
    # ffmpeg auto-pick keeps overlay alpha composition correct (forcing
    # yuva420p or rgba upstream broke band opacity).

    # Punch-in for plates: input PNG is at design size, scale up to 1.04 then ease back to 1.0
    # over 0.4s, then keep at 1.0. Use scale w/h with conditional expressions.
    if punch_in:
        entrance = 0.40
        # ease-out cubic: scale = 1.04 - 0.04 * (1 - (1 - t/entrance)^3) for t < entrance, else 1.0
        # = 1.04 - 0.04 * (1 - pow(1 - clip(t,0,entrance)/entrance, 3))
        expr = (f"if(lt(t,{entrance}),"
                f"1.04-0.04*(1-pow(1-t/{entrance},3)),"
                f"1.0)")
        chain.append(f"scale=w='iw*{expr}':h='ih*{expr}':eval=frame")
        # After scaling, center the result back to design size via crop
        chain.append(f"crop={W}:{H}")

    # Ken Burns for image chunks (1.0 -> 1.06 over duration)
    if ken_burns and not punch_in:
        z = 0.06
        chain.append(
            f"scale=w='iw*(1.0+{z}*t/{dur:.3f})':h='ih*(1.0+{z}*t/{dur:.3f})':eval=frame"
        )
        chain.append(f"crop={W}:{H}")

    # Per-chunk fade-in/out via `fade=alpha=1`. Speedup vs `geq`: ~7× per beat.
    #
    # CRITICAL: `setpts=PTS+{t_start}/TB` shifts the chunk stream's PTS so its
    # frames arrive at output time `t_start..t_end`, aligned with the overlay's
    # `enable=between(t,t_start,t_end)` window. Without this shift the chunk
    # stream runs 0..dur in output time and is past EOF by the time enable
    # activates → `eof_action=pass` drops the overlay entirely → every chunk
    # whose t_start > 0 silently rendered as scene-only. Only chunk 0 happened
    # to work because t_start = 0 aligned by accident.
    fi = max(fade_in, 0.001)
    fo = max(fade_out, 0.001)
    fade_out_start = max(0.0, dur - fo)
    chain.append("format=rgba")
    chain.append(f"fade=t=in:st=0:d={fi:.3f}:alpha=1")
    chain.append(f"fade=t=out:st={fade_out_start:.3f}:d={fo:.3f}:alpha=1")
    chain.append(f"setpts=PTS+{t_start:.3f}/TB")

    chunk_label = f"ch{chunk_input_idx}"
    # If chain has no filters (rare — only when no animations/fades), pass through.
    src_chain = (src + ",".join(chain) + f"[{chunk_label}]") if chain else f"{src}null[{chunk_label}]"

    # eof_action=pass: when the chunk PNG source ends (it's looped for chunk_dur,
    # which is shorter than the full beat audio), DO NOT terminate the bg stream
    # — just pass through bg alone after the chunk's enable window. Critical:
    # without this, the first chunk's EOF would truncate the whole beat output.
    overlay = (f"[{bg_label}][{chunk_label}]"
               f"overlay=enable='between(t,{t_start:.3f},{t_end:.3f})'"
               f":x=0:y=0:eof_action=pass[{out_label}]")
    return src_chain + ";" + overlay


# ─── Main entry ────────────────────────────────────────────────────

def _codec_args(gpu: bool, draft: bool, quality: str | None) -> tuple[list[str], str]:
    """Return (video codec args, audio bitrate) for a render quality preset."""
    q = quality or ("draft" if draft else "standard")
    if q == "draft":
        return ([
            "-c:v", "h264_nvenc" if gpu else "libx264",
            "-preset", "p1" if gpu else "ultrafast",
            *([] if not gpu else ["-rc", "vbr"]),
            *("-cq 28".split() if gpu else "-crf 28".split()),
            "-pix_fmt", "yuv420p",
        ], "160k")
    if q == "preview":
        return ([
            "-c:v", "h264_nvenc" if gpu else "libx264",
            "-preset", "p3" if gpu else "veryfast",
            *([] if not gpu else ["-rc", "vbr"]),
            *("-cq 24".split() if gpu else "-crf 22".split()),
            "-pix_fmt", "yuv420p",
        ], "192k")
    if q == "master":
        return ([
            "-c:v", "h264_nvenc" if gpu else "libx264",
            "-preset", "p5" if gpu else "slow",
            *([] if not gpu else ["-rc", "vbr"]),
            *("-cq 16".split() if gpu else "-crf 16".split()),
            "-pix_fmt", "yuv420p",
        ], "320k")
    # standard/upload: preserve the old non-draft baseline unless upload is
    # explicitly requested, in which case audio gets a little more headroom.
    return ([
        "-c:v", "h264_nvenc" if gpu else "libx264",
        "-preset", "p4" if gpu else "medium",
        *([] if not gpu else ["-rc", "vbr"]),
        *("-cq 20".split() if gpu else "-crf 18".split()),
        "-pix_fmt", "yuv420p",
    ], "256k" if q == "upload" else "192k")


def compose_ffmpeg(beat: Beat, design: Design, out_path: str,
                   draft: bool = False, gpu: bool = False,
                   no_cache: bool = False,
                   quality: str | None = None) -> None:
    """Render one beat via direct ffmpeg filter graph.

    Same signature + semantics as compose() in compose.py — drop-in replacement.
    """
    # Cache short-circuit
    if not no_cache and get_cached(beat, design, out_path, draft=draft, gpu=gpu, quality=quality):
        return

    # Load audio duration
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", beat.audio],
        capture_output=True, text=True,
    )
    audio_dur = float(r.stdout.strip())

    # Load words + compute chunk timings
    with open(beat.words, "r", encoding="utf-8") as f:
        words_data = json.load(f)
    words = words_data["words"]

    chunks_with_time = []
    for i, ch in enumerate(beat.chunks):
        wi_start, _ = ch.words
        t_start = words[wi_start]["start"]
        if i + 1 < len(beat.chunks):
            t_end = words[beat.chunks[i + 1].words[0]]["start"]
        else:
            t_end = audio_dur
        chunks_with_time.append({"chunk": ch, "t_start": t_start, "t_end": t_end,
                                  "scene": ch.scene})

    # Scene segments with same-src merging
    scene_segments = _merge_scene_segments(chunks_with_time, beat.scene, audio_dur)

    # Pre-render chunk PNGs to tmp dir
    tmp_dir = Path(tempfile.mkdtemp(prefix="devlog_ff_"))
    try:
        chunk_pngs = _prerender_chunk_pngs(beat, design, tmp_dir)

        # ── Build ffmpeg inputs ──
        cmd: list[str] = ["ffmpeg", "-y", "-i", beat.audio]
        input_idx = 1                                            # 0 = audio
        scene_inputs: list[tuple[int, Scene, float, float, float]] = []     # (idx, scene, seg_dur, eff_dur, pad_needed)
        for seg_idx, (seg_start, seg_end, scene) in enumerate(scene_segments):
            seg_dur = seg_end - seg_start
            is_last = (seg_idx == len(scene_segments) - 1)
            eff_dur = seg_dur + (design.crossfade_dur if not is_last else 0)
            args, pad_needed = _scene_input_args(scene, eff_dur)
            cmd += args
            scene_inputs.append((input_idx, scene, seg_dur, eff_dur, pad_needed))
            input_idx += 1

        chunk_inputs: dict[int, int] = {}                        # chunk_index -> input_idx
        for ci, info in chunk_pngs.items():
            if info["path"] is None:
                continue
            dur = chunks_with_time[ci]["t_end"] - chunks_with_time[ci]["t_start"]
            cmd += ["-loop", "1", "-t", f"{dur:.3f}", "-i", str(info["path"])]
            chunk_inputs[ci] = input_idx
            input_idx += 1

        # ── Build filter_complex ──
        filter_parts: list[str] = []

        # Step 1: normalize each scene to design resolution + Ken Burns
        scene_labels: list[str] = []
        seg_durs: list[float] = []
        for seg_idx, (idx, scene, seg_dur, eff_dur, pad_needed) in enumerate(scene_inputs):
            label = f"s{seg_idx}"
            filter_parts.append(
                _scene_normalize_filter(idx, seg_dur, eff_dur, design, scene, label, pad_needed)
            )
            scene_labels.append(label)
            seg_durs.append(seg_dur)

        # If the first scene doesn't start at t=0 (e.g. finale opens with a
        # full-screen plate before the daily_views animation), inject a solid
        # color base for the gap. Without this, the first real scene would
        # play in the wrong slot (its first frame at output t=0, animation
        # finishing before its associated plate even disappears).
        gap_start = scene_segments[0][0] if scene_segments else 0.0
        if gap_start > 0.05 and scene_labels:
            # gap is followed by at least 1 real scene -> needs crossfade tail
            gap_eff_dur = gap_start + design.crossfade_dur
            bg_color = "0x{:02x}{:02x}{:02x}".format(*design.palette.bg)
            filter_parts.insert(0,
                f"color=c={bg_color}:s={design.W}x{design.H}"
                f":d={gap_eff_dur:.3f}:r={design.fps},format=yuv420p[gap0]"
            )
            scene_labels.insert(0, "gap0")
            seg_durs.insert(0, gap_start)

        # Step 2: xfade chain across scenes
        if scene_labels:
            xfade_str, bg_label = _chain_xfade(scene_labels, seg_durs,
                                                design.crossfade_dur, design)
            if xfade_str:
                filter_parts.append(xfade_str)
        else:
            # No scenes at all — solid color base across whole audio
            bg_color = "0x{:02x}{:02x}{:02x}".format(*design.palette.bg)
            filter_parts.append(
                f"color=c={bg_color}:s={design.W}x{design.H}:d={audio_dur:.3f}:r={design.fps}[bg0]"
            )
            bg_label = "bg0"

        # bg is already yuv420p (forced in scene normalize); chunks overlay cleanly.

        # Step 3: chain chunk overlays
        for ci in sorted(chunk_inputs.keys()):
            cwt = chunks_with_time[ci]
            ch = cwt["chunk"]
            t_start = cwt["t_start"]
            t_end = cwt["t_end"]
            dur = t_end - t_start
            info = chunk_pngs[ci]

            # Per-chunk fade timings (mirrors compose.py)
            if ch.kind == "plate":
                fi = min(0.20, dur * 0.25)
                fo = min(0.18, dur * 0.20)
                punch = True
                ken = False
            elif ch.kind == "image":
                fi = min(0.28, dur * 0.18)
                fo = min(0.22, dur * 0.18)
                punch = False
                ken = ch.ken_burns
            elif ch.kind == "overlay":
                fi = min(0.25, dur * 0.20)
                fo = min(0.20, dur * 0.20)
                punch = False
                ken = False
            else:
                fi = fo = 0.1
                punch = ken = False

            out_label = f"v{ci}"
            filter_parts.append(_chunk_overlay_filter(
                bg_label, chunk_inputs[ci],
                t_start, t_end, fi, fo,
                out_label, info["rgba"], ken, design, punch,
            ))
            bg_label = out_label

        # Step 4: video chunks (kind=video) — overlay live video sub-clip
        for ci, cwt in enumerate(chunks_with_time):
            ch = cwt["chunk"]
            if ch.kind != "video":
                continue
            # Add as new input
            t_start = cwt["t_start"]
            t_end = cwt["t_end"]
            dur = t_end - t_start
            cmd += ["-ss", f"{ch.offset:.3f}", "-t", f"{dur:.3f}", "-i", ch.src]
            vid_idx = input_idx
            input_idx += 1
            tmp_label = f"vc{ci}_norm"
            fi = min(0.28, dur * 0.18)
            fo = min(0.22, dur * 0.18)
            filter_parts.append(
                f"[{vid_idx}:v]scale={design.W}:{design.H}:force_original_aspect_ratio=increase,"
                f"crop={design.W}:{design.H},setsar=1,fps={design.fps},"
                f"format=yuva420p,"
                f"fade=t=in:st=0:d={fi:.3f}:alpha=1,"
                f"fade=t=out:st={dur - fo:.3f}:d={fo:.3f}:alpha=1,"
                f"setpts=PTS-STARTPTS+{t_start:.3f}/TB[{tmp_label}]"
            )
            out_label = f"v_vid_{ci}"
            filter_parts.append(
                f"[{bg_label}][{tmp_label}]overlay=enable='between(t,{t_start:.3f},{t_end:.3f})'"
                f":x=0:y=0:format=auto:eof_action=pass[{out_label}]"
            )
            bg_label = out_label

        filter_complex = ";".join(filter_parts)

        # ── Codec args ──
        codec_args, audio_bitrate = _codec_args(gpu=gpu, draft=draft, quality=quality)

        # ── Final command ──
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        flags = []
        if draft: flags.append("draft")
        if gpu: flags.append("gpu")
        print(f"[ff-compose] {beat.audio} -> {out_path}"
              f"{' [' + ', '.join(flags) + ']' if flags else ''}"
              f"  ({len(scene_inputs)} scenes, {len(chunk_inputs)} text chunks)")

        cmd += [
            "-filter_complex", filter_complex,
            "-map", f"[{bg_label}]",
            "-map", "0:a",
            *codec_args,
            # Force 48kHz audio output — otherwise mismatched sample rates
            # across beats (e.g. outro processed at 96kHz) break demuxer
            # concat downstream by introducing inconsistent packet timing.
            "-c:a", "aac", "-b:a", audio_bitrate, "-ar", "48000",
            "-movflags", "+faststart",
            "-color_primaries", "bt709", "-color_trc", "bt709", "-colorspace", "bt709",
            "-t", f"{audio_dur:.3f}",
            # NOTE: NO `-shortest`. Each chunk PNG is `-loop 1 -t chunk_dur`
            # which is shorter than the audio. With -shortest, overlay's EOF
            # on the chunk source could terminate the whole pipeline early,
            # truncating output to first-chunk duration. -t audio_dur caps
            # to audio length explicitly, which is what we actually want.
            out_path,
        ]

        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode != 0:
            # Write filter graph + stderr to debug file
            dbg = Path(out_path).parent / f"{Path(out_path).stem}_ffmpeg_error.txt"
            dbg.write_text(
                "FILTER_COMPLEX:\n" + filter_complex + "\n\nCMD:\n" + " ".join(cmd)
                + "\n\nSTDERR:\n" + r.stderr,
                encoding="utf-8"
            )
            raise RuntimeError(f"ffmpeg failed (rc={r.returncode}). Debug: {dbg}")

        print(f"[ff-compose] done -> {out_path}")
        if not no_cache:
            put_cached(beat, design, out_path, draft=draft, gpu=gpu, quality=quality)
    finally:
        # Cleanup tmp PNG dir
        import shutil
        shutil.rmtree(tmp_dir, ignore_errors=True)
