"""Beat composition orchestrator.

`compose(beat, design, out_path)` is the main entry point: it reads the beat's
audio + Whisper words.json, computes chunk timings from word indices, builds
moviepy clips for all visual layers (scene backgrounds + per-chunk overlays),
composites them, and writes an MP4.

Behavior matches scripts/compose_beat.py (the legacy file this replaces):
- Chunks with the same scene.src merge into one continuous segment (no harsh
  cuts when only the overlay text changes mid-scene).
- Scene segments crossfade with 0.6s overlap (design.crossfade_dur).
- Plate chunks get a "punch-in" entrance (1.04× → 1.0 over 0.4s).
- Image chunks optionally get Ken Burns auto-zoom (1.0 → 1.06× over chunk).
- Video chunks are scene-styled (loop or freeze last frame if too short).
"""
from __future__ import annotations
import json
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter
from moviepy import (
    AudioFileClip, ImageClip, ColorClip, CompositeVideoClip,
    concatenate_videoclips, VideoFileClip,
)
from moviepy.video.fx import FadeIn, FadeOut

from devlog.types import Beat, Chunk, Design, Scene
from devlog.cache import get_cached, put_cached
from .plate import make_plate
from .overlay import make_overlay_badge, overlay_label
from .image import make_image_clip
from .effects import vignette


def _build_scene_clip(scene: Scene, seg_start: float, eff_dur: float, design: Design):
    """Build the background clip for one scene segment.

    For video sources: subclip from offset, loop or freeze if too short, then
    cover-crop to design resolution.
    For image sources: load via make_image_clip with Ken Burns auto-zoom if
    duration > 2s and scene.ken_burns is on (default True for images).
    """
    W, H, FPS = design.W, design.H, design.fps

    if scene.kind == "video":
        src_clip = VideoFileClip(scene.src).without_audio()
        end = min(scene.offset + eff_dur, src_clip.duration)
        sub = src_clip.subclipped(scene.offset, end)
        sub_dur = end - scene.offset
        if sub_dur < eff_dur - 0.05:
            if scene.loop:
                n_loops = int(math.ceil(eff_dur / sub_dur))
                sub = concatenate_videoclips([sub] * n_loops).subclipped(0, eff_dur)
            else:
                # Freeze last frame for remainder (prevents animation restart loops)
                last_frame = ImageClip(sub.get_frame(sub.duration - 1 / FPS))
                tail = last_frame.with_duration(eff_dur - sub_dur).with_fps(FPS)
                sub = concatenate_videoclips([sub, tail])
        # Cover-crop: scale to fill, center-crop overflow
        cw, ch = sub.size
        scale = max(W / cw, H / ch)
        nw, nh = int(cw * scale), int(ch * scale)
        sub = sub.resized((nw, nh))
        if nw != W or nh != H:
            x1, y1 = (nw - W) // 2, (nh - H) // 2
            sub = sub.cropped(x1=x1, y1=y1, x2=x1 + W, y2=y1 + H)
        return sub.with_duration(eff_dur).with_start(seg_start).with_fps(FPS)

    elif scene.kind == "image":
        scene_frame = make_image_clip(scene.src, design, fit=scene.fit)
        clip = ImageClip(scene_frame).with_duration(eff_dur).with_start(seg_start).with_fps(FPS)
        if scene.ken_burns and eff_dur > 2:
            kb_zoom = scene.kb_zoom
            def _kb(t, _dur=eff_dur, _z=kb_zoom):
                return 1.0 + _z * (t / max(_dur, 0.001))
            clip = clip.resized(_kb)
        return clip
    else:
        raise ValueError(f"Unknown scene kind: {scene.kind}")


def _merge_scene_segments(chunks_with_time: list[dict], default_scene: Scene | None, audio_dur: float):
    """Walk through chunks; consecutive chunks with same scene.src merge into
    one continuous segment so the same B-roll plays without a re-seek (avoids
    visible reset when only the overlay text changes mid-scene)."""
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
            # else: keep current segment running, ignore new offset
    if current_scene is not None:
        segments.append((current_start, audio_dur, current_scene))
    return segments


def _chunk_to_visual_clip(ch_dict: dict, chunk: Chunk, design: Design):
    """Render one chunk to a moviepy clip layer, or None if scene-only."""
    W, H, FPS = design.W, design.H, design.fps
    t_start = ch_dict["t_start"]
    dur = ch_dict["t_end"] - t_start
    if dur <= 0:
        return None

    if chunk.kind == "plate":
        frame = make_plate(chunk, design)
    elif chunk.kind == "image":
        # If framed_card AND label, render label INSIDE card (no orphan overlay)
        inset_label = chunk.label if chunk.framed_card else None
        frame = make_image_clip(
            chunk.src, design,
            fit=chunk.fit,
            framed_card=chunk.framed_card,
            inset_label=inset_label,
        )
        if chunk.vignette_overlay:
            img_pil = Image.fromarray(frame).convert("RGBA")
            img_pil.alpha_composite(vignette(design))
            frame = np.array(img_pil.convert("RGB"))
        if chunk.label and not chunk.framed_card:
            frame = overlay_label(frame, chunk.label, design, style=chunk.label_style)
    elif chunk.kind == "video":
        # Live video background instead of static plate (e.g. mid-beat gameplay)
        src_clip = VideoFileClip(chunk.src).without_audio()
        src_dur = src_clip.duration
        end = min(chunk.offset + dur, src_dur)
        seg = src_clip.subclipped(chunk.offset, end)
        seg_dur = end - chunk.offset
        if seg_dur < dur - 0.05:
            n_loops = int(math.ceil(dur / seg_dur))
            seg = concatenate_videoclips([seg] * n_loops).subclipped(0, dur)
        seg = seg.resized((W, H))
        clip = seg.with_duration(dur).with_start(t_start).with_fps(FPS)
        fade_in = min(0.28, dur * 0.18)
        fade_out = min(0.22, dur * 0.18)
        return clip.with_effects([FadeIn(fade_in), FadeOut(fade_out)])
    elif chunk.kind == "overlay":
        if not chunk.text:
            return None                                      # scene-only chunk
        rgba = make_overlay_badge(
            chunk.text, design,
            subtitle=chunk.subtitle,
            position=chunk.position,
            style=chunk.style,
        )
        rgb = rgba[:, :, :3]
        alpha = rgba[:, :, 3].astype(np.float32) / 255.0
        from moviepy import ImageClip as _IC
        overlay_clip = _IC(rgb).with_duration(dur).with_start(t_start).with_fps(FPS)
        mask_clip = _IC(alpha, is_mask=True).with_duration(dur).with_fps(FPS)
        overlay_clip = overlay_clip.with_mask(mask_clip)
        fade_in = min(0.25, dur * 0.20)
        fade_out = min(0.20, dur * 0.20)
        return overlay_clip.with_effects([FadeIn(fade_in), FadeOut(fade_out)])
    else:
        raise ValueError(f"Unknown chunk kind: {chunk.kind}")

    # ── Plate / image: build clip from numpy frame + entrance motion + fades ──
    clip = ImageClip(frame).with_duration(dur).with_start(t_start).with_fps(FPS)

    if chunk.kind == "plate":
        # Plate punch-in: 1.04 → 1.0 over 0.4s with ease-out cubic
        entrance = 0.40
        def plate_scale(t, _entrance=entrance):
            if t < _entrance:
                p = t / _entrance
                eased = 1 - (1 - p) ** 3
                return 1.04 - 0.04 * eased
            return 1.0
        clip = clip.resized(plate_scale)
        fade_in = min(0.20, dur * 0.25)
        fade_out = min(0.18, dur * 0.20)
    else:
        # Image: optional slow Ken Burns (1.0 → 1.06 over duration)
        if chunk.ken_burns:
            def kb_scale(t, _dur=dur):
                return 1.0 + 0.06 * (t / max(_dur, 0.001))
            clip = clip.resized(kb_scale)
        fade_in = min(0.28, dur * 0.18)
        fade_out = min(0.22, dur * 0.18)

    return clip.with_effects([FadeIn(fade_in), FadeOut(fade_out)])


def compose(beat: Beat, design: Design, out_path: str,
            draft: bool = False, gpu: bool = False, no_cache: bool = False) -> None:
    """Render one beat to an MP4 at design resolution.

    Reads beat.audio + beat.words (path to words.json), computes chunk timings
    from word indices, builds all visual layers, writes MP4 to `out_path`.

    draft=True uses libx264 ultrafast preset + CRF 28 — roughly 4-6x faster
    encode at the cost of ~2x larger file and slightly more compression
    artifacts. Use for iteration; turn off for final render.

    gpu=True uses h264_nvenc instead of libx264 (NVIDIA hardware encoding,
    5-10x faster at final quality). Requires an NVENC-capable GPU.

    no_cache=True forces a re-render even if a cached version exists for the
    same content hash. Otherwise compose copies from cache on hit.
    """
    if not no_cache and get_cached(beat, design, out_path, draft=draft, gpu=gpu):
        return
    audio = AudioFileClip(beat.audio)
    audio_dur = audio.duration
    print(f"[compose] audio {audio_dur:.2f}s")

    with open(beat.words, "r", encoding="utf-8") as f:
        words_data = json.load(f)
    words = words_data["words"]

    # ── Compute chunk timings from word ranges ──
    chunks_with_time: list[dict] = []
    for i, ch in enumerate(beat.chunks):
        wi_start, wi_end = ch.words
        t_start = words[wi_start]["start"]
        # Chunk extends to next chunk's start (or audio end for last)
        if i + 1 < len(beat.chunks):
            next_start = words[beat.chunks[i + 1].words[0]]["start"]
            t_end = next_start
        else:
            t_end = audio_dur
        chunks_with_time.append({"chunk": ch, "t_start": t_start, "t_end": t_end,
                                  "scene": ch.scene})
        print(f"  chunk {i}: {t_start:.2f}-{t_end:.2f}s  ({t_end - t_start:.2f}s)  {ch.kind}")

    # ── Scene segments (same-src merging + crossfade) ──
    visual_clips = []
    scene_segments = _merge_scene_segments(chunks_with_time, beat.scene, audio_dur)
    CROSSFADE_DUR = design.crossfade_dur
    for idx, (seg_start, seg_end, scene) in enumerate(scene_segments):
        seg_dur = seg_end - seg_start
        if seg_dur <= 0:
            continue
        is_last = (idx == len(scene_segments) - 1)
        eff_dur = seg_dur + (CROSSFADE_DUR if not is_last else 0)
        scene_clip = _build_scene_clip(scene, seg_start, eff_dur, design)
        fx = []
        if seg_start > 0:
            fx.append(FadeIn(CROSSFADE_DUR))
        if not is_last:
            fx.append(FadeOut(CROSSFADE_DUR))
        if fx:
            scene_clip = scene_clip.with_effects(fx)
        visual_clips.append(scene_clip)

    # ── Initial black background if first chunk doesn't start at t=0 and no scene ──
    if not beat.scene and chunks_with_time[0]["t_start"] > 0 and not scene_segments:
        bg_init = ColorClip(size=(design.W, design.H), color=design.palette.bg,
                            duration=chunks_with_time[0]["t_start"]).with_start(0)
        visual_clips.append(bg_init)

    # ── Per-chunk visual layers ──
    for cwt in chunks_with_time:
        clip = _chunk_to_visual_clip(cwt, cwt["chunk"], design)
        if clip is not None:
            visual_clips.append(clip)

    # ── Composite + write ──
    base = ColorClip(size=(design.W, design.H), color=design.palette.bg,
                     duration=audio_dur).with_fps(design.fps)
    final = CompositeVideoClip([base] + visual_clips, size=(design.W, design.H)).with_duration(audio_dur)
    final = final.with_audio(audio)

    flags = []
    if draft: flags.append("draft")
    if gpu: flags.append("gpu")
    print(f"[compose] writing {out_path}{' [' + ', '.join(flags) + ']' if flags else ''}...")
    Path(out_path).parent.mkdir(parents=True, exist_ok=True)

    if gpu:
        # NVENC: preset p1=fastest..p7=slowest, cq=constant quality (~CRF)
        codec = "h264_nvenc"
        nvenc_preset = "p4" if not draft else "p1"
        cq = "28" if draft else "20"            # nvenc cq is slightly different scale than libx264 crf
        ffmpeg_params = ["-preset", nvenc_preset, "-cq", cq, "-rc", "vbr",
                         "-pix_fmt", "yuv420p"]
    else:
        codec = "libx264"
        x264_preset = "ultrafast" if draft else "medium"
        crf = "28" if draft else "18"
        ffmpeg_params = ["-preset", x264_preset, "-crf", crf, "-pix_fmt", "yuv420p"]

    final.write_videofile(
        out_path,
        fps=design.fps,
        codec=codec,
        audio_codec="aac",
        audio_bitrate="192k",
        threads=8,
        ffmpeg_params=ffmpeg_params,
    )
    print(f"[compose] done -> {out_path}")
    if not no_cache:
        put_cached(beat, design, out_path, draft=draft, gpu=gpu)
