"""Subtitle-phrase rasterizer (`beat.subtitles`, PLAN_STUDIO_V2 1.6).

One primitive, one position, one style: a wrapped, horizontally-centered
text block over a rounded semi-transparent backdrop pill, anchored in the
bottom safe zone. All knobs come from `Design.captions` (CaptionStyle);
there is deliberately no general titling system here.
"""
from __future__ import annotations

from PIL import Image, ImageDraw

from dlstudio.model import Design

from ._util import hex_to_rgb, load_font, text_box

# Backdrop pill paddings relative to the text size (visual constants of the
# one caption look, not per-project styling knobs).
_PAD_X_RATIO = 0.45
_PAD_Y_RATIO = 0.28
_RADIUS_RATIO = 0.35
_LINE_GAP_RATIO = 0.22


def _wrap(draw: ImageDraw.ImageDraw, text: str, font, max_width: int) -> list[str]:
    """Greedy word wrap by measured pixel width. A single word longer than
    max_width stays on its own line (never split mid-word)."""
    lines: list[str] = []
    cur = ""
    for word in text.split():
        candidate = f"{cur} {word}".strip()
        w, _ = text_box(draw, candidate, font)
        if cur and w > max_width:
            lines.append(cur)
            cur = word
        else:
            cur = candidate
    if cur:
        lines.append(cur)
    return lines


def render_caption(text: str, design: Design) -> Image.Image:
    style = design.captions
    width, height = design.resolution
    img = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)

    size = max(1, design.px(style.size))
    font = load_font(design, style.font, size)
    max_text_width = int(width * style.max_width_ratio)
    lines = _wrap(draw, text, font, max_text_width)

    line_gap = int(size * _LINE_GAP_RATIO)
    line_sizes = [text_box(draw, ln, font) for ln in lines]
    line_h = max((h for _, h in line_sizes), default=size) or size
    block_w = max((w for w, _ in line_sizes), default=0)
    block_h = len(lines) * line_h + max(0, len(lines) - 1) * line_gap

    center_y = int(height * style.y_ratio)
    top = center_y - block_h // 2
    # Clamp the whole block inside the frame's safe margin.
    margin = int(height * design.safe_margin_ratio)
    top = max(margin, min(top, height - margin - block_h))

    if style.bg_opacity > 0 and lines:
        pad_x = int(size * _PAD_X_RATIO)
        pad_y = int(size * _PAD_Y_RATIO)
        pill = [
            (width - block_w) // 2 - pad_x,
            top - pad_y,
            (width + block_w) // 2 + pad_x,
            top + block_h + pad_y,
        ]
        alpha = round(255 * min(1.0, max(0.0, style.bg_opacity)))
        bg_rgb = hex_to_rgb(design.palette.color("bg"))
        draw.rounded_rectangle(
            pill, radius=int(size * _RADIUS_RATIO), fill=(*bg_rgb, alpha))

    color = (*hex_to_rgb(design.palette.color(style.color)), 255)
    y = top
    for ln, (w, _h) in zip(lines, line_sizes):
        draw.text(((width - w) // 2, y), ln, font=font, fill=color)
        y += line_h + line_gap

    return img
