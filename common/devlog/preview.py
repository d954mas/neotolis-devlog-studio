"""Fast still previews for individual chunks."""
from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path

import numpy as np
from PIL import Image

from devlog.types import Design, Edit, Scene


def _blank(design: Design) -> np.ndarray:
    return np.array(Image.new("RGB", design.resolution, design.palette.bg))


def _video_frame(src: str, design: Design, *, offset: float = 0.0, fit: str = "cover") -> np.ndarray:
    from devlog.render.image import make_image_clip

    with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as handle:
        frame_path = Path(handle.name)
    try:
        subprocess.run(
            ["ffmpeg", "-y", "-ss", f"{max(0.0, offset):.3f}", "-i", src,
             "-frames:v", "1", "-q:v", "2", str(frame_path)],
            capture_output=True,
            check=True,
        )
        return make_image_clip(str(frame_path), design, fit=fit)
    finally:
        frame_path.unlink(missing_ok=True)


def _scene_frame(scene: Scene | None, design: Design) -> np.ndarray:
    if scene is None:
        return _blank(design)
    if scene.kind == "image":
        from devlog.render.image import make_image_clip
        return make_image_clip(scene.src, design, fit=scene.fit)
    if scene.kind == "video":
        return _video_frame(scene.src, design, offset=scene.offset, fit=scene.fit)
    return _blank(design)


def _image_chunk_frame(chunk, design: Design) -> np.ndarray:
    from devlog.render.effects import vignette
    from devlog.render.image import make_image_clip
    from devlog.render.overlay import overlay_label

    inset_label = chunk.label if chunk.framed_card else None
    frame = make_image_clip(
        chunk.src,
        design,
        fit=chunk.fit,
        framed_card=chunk.framed_card,
        inset_label=inset_label,
    )
    if chunk.vignette_overlay:
        pil = Image.fromarray(frame).convert("RGBA")
        pil.alpha_composite(vignette(design))
        frame = np.array(pil.convert("RGB"))
    if chunk.label and not chunk.framed_card:
        frame = overlay_label(frame, chunk.label, design, style=chunk.label_style)
    return frame


def _overlay_on(base: np.ndarray, overlay: np.ndarray) -> np.ndarray:
    bg = Image.fromarray(base).convert("RGBA")
    fg = Image.fromarray(overlay, mode="RGBA")
    bg.alpha_composite(fg)
    return np.array(bg.convert("RGB"))


def render_chunk_preview(edit: Edit, beat_id: str, chunk_index: int, out_path: str | Path) -> Path:
    if beat_id not in edit.beats:
        raise ValueError(f"unknown beat: {beat_id}")
    beat = edit.beats[beat_id]
    if chunk_index < 0 or chunk_index >= len(beat.chunks):
        raise ValueError(f"unknown chunk index for {beat_id}: {chunk_index}")

    chunk = beat.chunks[chunk_index]
    design = edit.design
    if chunk.kind == "plate":
        from devlog.render.plate import make_plate
        frame = make_plate(chunk, design)
    elif chunk.kind == "overlay":
        from devlog.render.overlay import make_overlay_badge
        base = _scene_frame(chunk.scene or beat.scene, design)
        if chunk.text:
            overlay = make_overlay_badge(
                chunk.text,
                design,
                subtitle=chunk.subtitle,
                position=chunk.position,
                style=chunk.style,
                size=chunk.size,
                sub_ratio=chunk.sub_ratio,
                line_gap_ratio=chunk.line_gap_ratio,
            )
            frame = _overlay_on(base, overlay)
        else:
            frame = base
    elif chunk.kind == "image":
        frame = _image_chunk_frame(chunk, design)
    elif chunk.kind == "video":
        frame = _video_frame(chunk.src, design, offset=chunk.offset, fit=chunk.fit)
    else:
        raise ValueError(f"unsupported chunk kind: {chunk.kind}")

    out = Path(out_path)
    out.parent.mkdir(parents=True, exist_ok=True)
    Image.fromarray(frame).save(out)
    return out
