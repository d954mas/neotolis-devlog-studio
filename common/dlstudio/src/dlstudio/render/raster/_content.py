"""Content renderers: Plate, Overlay, ImageShot, VideoShot -> RGBA raster.

Each returns `(Image.Image, Layout)`. The image is always RGBA at
`design.resolution`. `Layout` is a best-effort geometry hint consumed by
decoration passes (see `_util.Layout`).

Port notes (v1 -> v2), see raster-agent final report for the full list:
- Plate dropped subtitle/accent_card/red_accent/trophy/medal/silver_badge/
  automatic vignette — those are now independent Decoration passes
  (Underline, Badge, FramedCard, Vignette) or, for red_accent, dropped
  entirely (no equivalent Decoration in the v2 union).
- ImageShot dropped `framed_card` — that is FramedCard, a generic
  decoration over ANY content raster now, not an image-specific parameter.
- Motion (punch-in scale, Ken Burns) is never rasterized here — v2 renders
  the static frame; `graph.py` applies motion via ffmpeg.
- ImageShot AND VideoShot render a fully transparent frame (finding H1): the
  image/video pixels come from the ffmpeg scene segment, never from raster.
  A chunk's decorations composite over that transparent frame, so a decorated
  image/video chunk still gets its badges/captions without raster double-
  drawing a frozen copy over the moving segment.

Content dispatch is a registry (CONTENT_RENDERERS in __init__.py), not an
isinstance ladder — see that module's docstring for how to add a type.
"""
from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter

from dlstudio.model import Design, ImageShot, Overlay, Plate, VideoShot

from ._util import Layout, has_cyrillic, hex_to_rgb, load_font, text_box, text_ink_bottom, text_width


# ─── Plate ───────────────────────────────────────────────────────────────

def render_plate(content: Plate, design: Design) -> tuple[Image.Image, Layout]:
    W, H = design.resolution
    style = design.style(content.style)

    text = content.text.upper() if style.caps else content.text
    color = hex_to_rgb(design.palette.color(style.color))
    bg_rgb = hex_to_rgb(design.palette.color("bg"))

    img = _plate_background(content, design, bg_rgb)
    draw = ImageDraw.Draw(img)

    size_px = design.px(content.size if content.size is not None else style.size)
    line_gap_ratio = (
        content.line_gap_ratio if content.line_gap_ratio is not None else style.line_gap_ratio
    )

    lines = text.split("\n")

    # Auto-shrink so the widest line fits within the safe area. v1 used a
    # fixed `design.plate_margin` (240px @ 1920 baseline); v2's Design has
    # no such token (raster must not add engine fields), so this uses the
    # model's ratio-based `safe_margin_ratio` instead — reserving that
    # fraction of the frame width on each side. Noted as an intentional
    # v1->v2 substitution in the raster-agent report.
    max_w = max(1, W - 2 * round(W * design.safe_margin_ratio))
    fitted_size = size_px
    font = load_font(design, style.font, fitted_size)
    for _ in range(8):
        font = load_font(design, style.font, fitted_size)
        widest = max((text_width(draw, ln, font) for ln in lines), default=0)
        if widest <= max_w:
            break
        fitted_size = max(1, int(fitted_size * 0.92))
    size_px = fitted_size

    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    cyrillic = has_cyrillic(text)
    diacritic_pad = int(size_px * 0.32) if cyrillic else 0
    line_h_total = line_h + diacritic_pad
    line_gap = int(size_px * line_gap_ratio)

    line_metrics: list[tuple[str, int]] = []
    total_h = 0
    for ln in lines:
        lw = text_width(draw, ln, font)
        line_metrics.append((ln, lw))
        total_h += line_h_total
    total_h += line_gap * (len(lines) - 1)

    y_start = (H - total_h) // 2
    text_top = y_start
    if cyrillic and diacritic_pad > 0:
        y_start += design.px(40)  # bias down to compensate diacritic visual-center shift

    shadow_off = min(design.px(5), max(design.px(3), size_px // 70))
    y = y_start
    for ln, lw in line_metrics:
        x = (W - lw) // 2
        y_render = y + diacritic_pad
        draw.text((x + shadow_off, y_render + shadow_off), ln, fill=(0, 0, 0, 255), font=font, anchor="lt")
        draw.text((x, y_render), ln, fill=(*color, 255), font=font, anchor="lt")
        y += line_h_total + line_gap
    text_bottom = y - line_gap

    layout = Layout(text_top=text_top, text_bottom=text_bottom, text_center_x=W // 2, main_size_px=size_px)
    return img, layout


def _plate_background(content: Plate, design: Design, bg_rgb: tuple[int, int, int]) -> Image.Image:
    W, H = design.resolution
    if content.bg_image:
        path = Path(content.bg_image)
        if path.exists():
            try:
                raw = Image.open(path).convert("RGB").resize((W, H), Image.LANCZOS)
                raw = raw.filter(ImageFilter.GaussianBlur(design.px(14)))
                opacity = content.bg_opacity if content.bg_opacity is not None else 0.28
                base = np.array(bg_rgb, dtype=np.float32)
                raw_arr = np.array(raw, dtype=np.float32)
                arr = base + (raw_arr - base) * opacity
                arr = np.clip(arr, 0, 255).astype(np.uint8)
                return Image.fromarray(arr).convert("RGBA")
            except Exception:
                pass  # fall through to solid bg — still produces something visible
        else:
            print(f"[dlstudio.raster] warn: missing plate bg_image {content.bg_image!r}, using solid bg")
    return Image.new("RGBA", (W, H), (*bg_rgb, 255))


# ─── Overlay ─────────────────────────────────────────────────────────────

def render_overlay(content: Overlay, design: Design) -> tuple[Image.Image, Layout]:
    W, H = design.resolution
    style = design.style(content.style)

    text = content.text.upper() if style.caps else content.text
    subtitle = content.subtitle
    if subtitle and style.caps:
        subtitle = subtitle.upper()

    main_rgb = hex_to_rgb(design.palette.color(style.color))
    sub_token = content.subtitle_color if content.subtitle_color else "accent"
    sub_rgb = hex_to_rgb(design.palette.color(sub_token))
    bg_rgb = hex_to_rgb(design.palette.color("bg"))
    accent_rgb = hex_to_rgb(design.palette.color("accent"))

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    base_size = design.px(style.size)
    sub_ratio = content.sub_ratio if content.sub_ratio is not None else 0.25

    if content.variant == "hero":
        _overlay_hero(canvas, design, style, text, subtitle, main_rgb, sub_rgb, accent_rgb, bg_rgb, base_size, sub_ratio)
    elif content.variant == "card":
        _overlay_card(canvas, design, style, text, subtitle, main_rgb, sub_rgb, accent_rgb, bg_rgb, base_size, sub_ratio)
    else:
        _overlay_band(canvas, design, style, text, subtitle, main_rgb, sub_rgb, accent_rgb, bg_rgb, base_size, sub_ratio,
                       content.position)

    return canvas, Layout()  # overlay content carries no plate-style text geometry hint


def _soft_backdrop(canvas: Image.Image, design: Design, box: tuple[int, int, int, int],
                    radius: int, bg_rgb: tuple[int, int, int], accent_rgb: tuple[int, int, int],
                    fill_alpha: int, outline_alpha: int = 95, outline_width: int | None = None) -> None:
    W, H = canvas.size
    x1, y1, x2, y2 = box
    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((x1 + design.px(10), y1 + design.px(18), x2 + design.px(10), y2 + design.px(18)),
                          radius=radius, fill=(0, 0, 0, 180))
    shadow = shadow.filter(ImageFilter.GaussianBlur(design.px(30)))
    canvas.alpha_composite(shadow)
    gd = ImageDraw.Draw(canvas)
    gd.rounded_rectangle(box, radius=radius, fill=(*bg_rgb, fill_alpha))
    gd.rounded_rectangle(box, radius=radius, outline=(*accent_rgb, outline_alpha),
                          width=outline_width or max(1, design.px(2)))


def _overlay_band(canvas, design, style, text, subtitle, main_rgb, sub_rgb, accent_rgb, bg_rgb,
                   base_size, sub_ratio, position) -> None:
    W, H = canvas.size
    draw = ImageDraw.Draw(canvas)

    text_size = base_size
    sub_size = max(design.px(32), int(text_size * sub_ratio)) if subtitle else design.px(36)
    max_w = W - design.px(300)
    font = load_font(design, style.font, text_size)
    sub_font = load_font(design, style.font, sub_size) if subtitle else None
    tw = th = sw = sh = 0
    for _ in range(9):
        font = load_font(design, style.font, text_size)
        sub_font = load_font(design, style.font, sub_size) if subtitle else None
        tw, th = text_box(draw, text, font)
        sw, sh = text_box(draw, subtitle, sub_font) if subtitle and sub_font else (0, 0)
        if max(tw, sw) <= max_w:
            break
        text_size = max(design.px(52), int(text_size * 0.90))
        sub_size = max(design.px(24), int(sub_size * 0.90))

    pad_x = design.px(72)
    pad_y = design.px(42)
    gap = max(design.px(12), int(text_size * style.line_gap_ratio)) if subtitle else 0
    accent_safe_w = design.px(112)
    box_w = max(design.px(860), min(W - design.px(200), max(tw, sw) + pad_x * 2 + accent_safe_w))
    box_h = th + sh + gap + pad_y * 2

    if position == "bottom":
        y = H - box_h - design.px(78)
    elif position == "top":
        y = design.px(78)
    else:
        y = (H - box_h) // 2
    x = (W - box_w) // 2

    _soft_backdrop(canvas, design, (x, y, x + box_w, y + box_h), design.px(24), bg_rgb, accent_rgb, fill_alpha=205)
    draw = ImageDraw.Draw(canvas)
    text_area_x = x + design.px(34)
    text_area_w = box_w - design.px(68)
    tx = text_area_x + max(0, (text_area_w - tw) // 2)
    ty = y + pad_y
    draw.text((tx + design.px(3), ty + design.px(4)), text, fill=(0, 0, 0, 255), font=font, anchor="lt")
    draw.text((tx, ty), text, fill=(*main_rgb, 255), font=font, anchor="lt")

    if subtitle and sub_font:
        sx = text_area_x + max(0, (text_area_w - sw) // 2)
        sy = ty + th + gap
        draw.text((sx + design.px(2), sy + design.px(3)), subtitle, fill=(0, 0, 0, 255), font=sub_font, anchor="lt")
        draw.text((sx, sy), subtitle, fill=(*sub_rgb, 255), font=sub_font, anchor="lt")


def _overlay_card(canvas, design, style, text, subtitle, main_rgb, sub_rgb, accent_rgb, bg_rgb,
                   base_size, sub_ratio) -> None:
    W, H = canvas.size
    draw = ImageDraw.Draw(canvas)

    text_size = base_size
    sub_size = max(design.px(28), int(text_size * sub_ratio)) if subtitle else design.px(40)
    pad_x = design.px(120)
    ml = "\n" in text
    line_spacing = int(text_size * 0.22)
    max_card_w = W - design.px(160)
    max_card_h = H - design.px(200)
    font = load_font(design, style.font, text_size)
    sub_font = load_font(design, style.font, sub_size) if subtitle else None
    tw = th = 0
    for _ in range(8):
        font = load_font(design, style.font, text_size)
        sub_font = load_font(design, style.font, sub_size) if subtitle else None
        bbox = draw.multiline_textbbox((0, 0), text, font=font, spacing=line_spacing) if ml \
            else draw.textbbox((0, 0), text, font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        sub_h = sub_size + design.px(20) if subtitle else 0
        if tw + pad_x * 2 <= max_card_w and th + sub_h + design.px(160) <= max_card_h:
            break
        text_size = int(text_size * 0.88)
        sub_size = int(sub_size * 0.88)
        line_spacing = int(text_size * 0.22)

    sub_h = sub_size + design.px(20) if subtitle else 0
    pad_y = design.px(80)
    card_w = max(tw + pad_x * 2, design.px(900))
    card_h = th + sub_h + pad_y * 2
    cx = (W - card_w) // 2
    cy = (H - card_h) // 2

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((cx + design.px(8), cy + design.px(16), cx + card_w + design.px(8), cy + card_h + design.px(16)),
                          radius=design.px(24), fill=(0, 0, 0, 220))
    shadow = shadow.filter(ImageFilter.GaussianBlur(design.px(28)))
    canvas.alpha_composite(shadow)

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((cx, cy, cx + card_w, cy + card_h), radius=design.px(24), fill=(*bg_rgb, 235))
    draw.rounded_rectangle((cx, cy, cx + card_w, cy + card_h), radius=design.px(24),
                            outline=(*accent_rgb, 255), width=design.px(5))

    tx = (W - tw) // 2
    ty = cy + pad_y
    if ml:
        draw.multiline_text((tx + design.px(5), ty + design.px(5)), text, fill=(0, 0, 0, 255), font=font,
                             spacing=line_spacing, align="center")
        draw.multiline_text((tx, ty), text, fill=(*main_rgb, 255), font=font, spacing=line_spacing, align="center")
    else:
        draw.text((tx + design.px(5), ty + design.px(5)), text, fill=(0, 0, 0, 255), font=font)
        draw.text((tx, ty), text, fill=(*main_rgb, 255), font=font)

    if subtitle and sub_font:
        sbbox = draw.textbbox((0, 0), subtitle, font=sub_font, anchor="lt")
        sw = sbbox[2] - sbbox[0]
        sx = (W - sw) // 2
        sy = ty + bbox[3] + design.px(20)  # bbox[3]: true ink-bottom offset, not ink height (see text_ink_bottom)
        draw.text((sx + design.px(3), sy + design.px(3)), subtitle, fill=(0, 0, 0, 255), font=sub_font, anchor="lt")
        draw.text((sx, sy), subtitle, fill=(*sub_rgb, 255), font=sub_font, anchor="lt")


def _overlay_hero(canvas, design, style, text, subtitle, main_rgb, sub_rgb, accent_rgb, bg_rgb,
                   base_size, sub_ratio) -> None:
    W, H = canvas.size
    draw = ImageDraw.Draw(canvas)

    text_size = base_size
    sub_size = max(design.px(28), int(text_size * sub_ratio)) if subtitle else design.px(40)
    max_w = W - design.px(260)
    max_h = int(H * 0.54)
    ml = "\n" in text
    font = load_font(design, style.font, text_size)
    sub_font = load_font(design, style.font, sub_size) if subtitle else None
    tw = th = sw = sh = 0
    line_spacing = int(text_size * 0.16)
    for _ in range(10):
        font = load_font(design, style.font, text_size)
        sub_font = load_font(design, style.font, sub_size) if subtitle else None
        line_spacing = int(text_size * 0.16)
        tw, th = text_box(draw, text, font, line_spacing)
        sw, sh = text_box(draw, subtitle, sub_font) if subtitle and sub_font else (0, 0)
        sub_h = sh + design.px(26) if subtitle else 0
        if max(tw, sw) <= max_w and th + sub_h <= max_h:
            break
        text_size = max(design.px(76), int(text_size * 0.90))
        sub_size = max(design.px(34), int(sub_size * 0.90))

    sub_h = sh + design.px(26) if subtitle else 0
    block_h = th + sub_h + design.px(20)
    block_y = (H - block_h) // 2
    tx = (W - tw) // 2
    ty = block_y

    box_w = min(W - design.px(180), max(tw, sw) + design.px(180))
    box_h = block_h + design.px(118)
    bx = (W - box_w) // 2
    by = max(design.px(110), block_y - design.px(60))

    glow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((bx - design.px(120), by - design.px(80), bx + box_w + design.px(120), by + box_h + design.px(100)),
               fill=(*accent_rgb, 42))
    glow = glow.filter(ImageFilter.GaussianBlur(design.px(70)))
    canvas.alpha_composite(glow)

    _soft_backdrop(canvas, design, (bx, by, bx + box_w, by + box_h), design.px(30), bg_rgb, accent_rgb, fill_alpha=145)

    draw = ImageDraw.Draw(canvas)
    stroke_w = design.px(7)
    step = max(1, design.px(2))
    for dx in range(-stroke_w, stroke_w + 1, step):
        for dy in range(-stroke_w, stroke_w + 1, step):
            if dx * dx + dy * dy <= stroke_w * stroke_w:
                if ml:
                    draw.multiline_text((tx + dx, ty + dy), text, fill=(0, 0, 0, 255), font=font,
                                         spacing=line_spacing, align="center")
                else:
                    draw.text((tx + dx, ty + dy), text, fill=(0, 0, 0, 255), font=font, anchor="lt")
    if ml:
        draw.multiline_text((tx, ty), text, fill=(*main_rgb, 255), font=font, spacing=line_spacing, align="center")
    else:
        draw.text((tx, ty), text, fill=(*main_rgb, 255), font=font, anchor="lt")

    if subtitle and sub_font:
        sb = draw.textbbox((0, 0), subtitle, font=sub_font, anchor="lt")
        sw = sb[2] - sb[0]
        sx = (W - sw) // 2
        # Single-line main text is drawn with anchor="lt" (th already == ink-bottom
        # offset); multiline_text has no anchor support and uses PIL's default
        # ascender-relative placement, where ink height != ink-bottom offset
        # (see text_ink_bottom) — use the right one per branch.
        main_bottom = text_ink_bottom(draw, text, font, line_spacing) if ml else th
        sy = ty + main_bottom + design.px(24)
        sub_stroke = design.px(4)
        for dx in range(-sub_stroke, sub_stroke + 1, step):
            for dy in range(-sub_stroke, sub_stroke + 1, step):
                draw.text((sx + dx, sy + dy), subtitle, fill=(0, 0, 0, 255), font=sub_font, anchor="lt")
        draw.text((sx, sy), subtitle, fill=(*sub_rgb, 255), font=sub_font, anchor="lt")


# ─── ImageShot / VideoShot ─────────────────────────────────────────────────

def render_image_shot(content: ImageShot, design: Design) -> tuple[Image.Image, Layout]:
    """Raster renders nothing for the image itself — the ffmpeg scene layer
    composites the (possibly Ken Burns-moving) image as a background segment.
    Rastering a static copy here would double-draw a frozen image over the
    moving segment (finding H1). Returns a fully transparent frame; a chunk's
    decorations then composite over it in render_chunk_image."""
    W, H = design.resolution
    return Image.new("RGBA", (W, H), (0, 0, 0, 0)), Layout()


def render_video_shot(content: VideoShot, design: Design) -> tuple[Image.Image, Layout]:
    """Raster renders nothing for video content — the ffmpeg scene layer
    supplies the actual video pixels. Fully transparent placeholder frame;
    decorations composite over it (finding H1)."""
    W, H = design.resolution
    return Image.new("RGBA", (W, H), (0, 0, 0, 0)), Layout()
