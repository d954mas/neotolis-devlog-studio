"""Full-screen text plate renderer.

A plate is centered headline + optional subtitle, optionally with:
- bg_image: blurred game screenshot tinted toward the brand bg
- red_underline: fixed-width gold bar below headline (design token)
- accent_card: rounded card behind text (palette-disciplined inset)
- red_accent: red underline below last text line (variable width)
- trophy / medal / silver_badge: decorative icon above headline

**Resolution independence:** all pixel values (chunk.size, design tokens,
internal paddings) are expressed at the 1920-baseline. The engine scales
them via `design.px()` at render time so the same Beat produces a
proportionally identical image at 540, 1080, or 4K. Write beats once,
render fast at 540 for iteration and final at 4K.
"""
from __future__ import annotations
import math
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from devlog.types import Chunk, Design
from .effects import vignette
from .text import has_cyrillic, pick_font


def make_plate(chunk: Chunk, design: Design) -> np.ndarray:
    """Render a plate-kind chunk to an RGB numpy array at design resolution."""
    W, H = design.W, design.H
    pal = design.palette
    S = design.px                                              # short alias: baseline-px → render-px

    text         = chunk.text
    color        = chunk.color or pal.gold
    bg           = chunk.bg or pal.bg
    size_px      = S(chunk.size)                               # scale baseline text height
    subtitle     = chunk.subtitle
    sub_ratio    = chunk.sub_ratio
    line_gap_ratio = chunk.line_gap_ratio
    red_underline  = chunk.red_underline
    red_accent     = chunk.red_accent
    accent_card    = chunk.accent_card
    has_trophy     = chunk.trophy
    has_medal      = chunk.medal
    silver_badge   = chunk.silver_badge
    subtitle_spaced = chunk.subtitle_spaced
    subtitle_color = chunk.subtitle_color
    bg_image       = chunk.bg_image
    bg_opacity     = chunk.bg_opacity

    # ── Background ──
    if bg_image and not (accent_card or red_accent):
        raw = Image.open(bg_image).convert("RGB").resize((W, H), Image.LANCZOS)
        raw = raw.filter(ImageFilter.GaussianBlur(S(14)))
        bg_base = np.array(pal.bg, dtype=np.float32)
        raw_arr = np.array(raw, dtype=np.float32)
        arr = bg_base + (raw_arr - bg_base) * bg_opacity
        arr = np.clip(arr, 0, 255)
        img = Image.fromarray(arr.astype(np.uint8))
    else:
        img = Image.new("RGB", (W, H), pal.bg if (accent_card or red_accent) else bg)
    draw = ImageDraw.Draw(img)

    font_path = pick_font(text, design)

    # ── Auto-shrink so widest line fits within safe area ──
    MAX_W = W - S(design.plate_margin)
    fitted_size = size_px
    for _ in range(8):
        font = ImageFont.truetype(font_path, fitted_size)
        widest = 0
        for line in text.split("\n"):
            bbox = draw.textbbox((0, 0), line, font=font, anchor="lt")
            widest = max(widest, bbox[2] - bbox[0])
        if widest <= MAX_W:
            break
        fitted_size = int(fitted_size * 0.92)
    size_px = fitted_size
    font = ImageFont.truetype(font_path, size_px)

    sub_font_path = pick_font(subtitle, design) if subtitle else font_path
    sub_size = max(S(36), int(size_px * sub_ratio))
    sub_font = ImageFont.truetype(sub_font_path, sub_size) if subtitle else None

    # ── Measure main text ──
    lines = text.split("\n")
    line_metrics: list[tuple[str, int]] = []
    total_h = 0
    line_gap = int(size_px * line_gap_ratio)

    ascent, descent = font.getmetrics()
    line_h = ascent + descent
    diacritic_pad = int(size_px * 0.32) if has_cyrillic(text) else 0
    line_h += diacritic_pad

    for line in lines:
        bbox = draw.textbbox((0, 0), line, font=font, anchor="lt")
        lw = bbox[2] - bbox[0]
        line_metrics.append((line, lw))
        total_h += line_h
    total_h += line_gap * (len(lines) - 1)

    sub_h = 0
    sub_metrics = None
    if subtitle:
        sub_bbox = draw.textbbox((0, 0), subtitle, font=sub_font, anchor="lt")
        sub_lw = sub_bbox[2] - sub_bbox[0]
        sub_ascent, sub_descent = sub_font.getmetrics()
        sub_h = sub_ascent + sub_descent
        sub_metrics = (subtitle, sub_lw, sub_h)
        total_h += sub_h + int(line_gap * 1.4)

    # ── Decorative icon above text ──
    t_w, t_h, t_bbox, ef = 0, 0, None, None
    icon_char = None
    badge_size = 0
    if has_trophy:
        icon_char = "🏆"
    elif has_medal:
        icon_char = "🥈"
    elif silver_badge:
        badge_size = int(size_px * 1.0)
        t_w = badge_size
        t_h = badge_size
        total_h += badge_size + int(line_gap * 1.6)
    if icon_char:
        trophy_size = int(size_px * 1.5)
        try:
            ef = ImageFont.truetype(design.fonts.emoji or "C:/Windows/Fonts/seguiemj.ttf", trophy_size)
            t_bbox = draw.textbbox((0, 0), icon_char, font=ef, anchor="lt")
            t_w = t_bbox[2] - t_bbox[0]
            t_h = t_bbox[3] - t_bbox[1]
            total_h += t_h + int(line_gap * 1.6)
        except Exception:
            icon_char = None

    # ── Accent card ──
    if accent_card:
        max_lw = max(lw for _, lw in line_metrics)
        if t_w > max_lw: max_lw = t_w
        if subtitle and sub_metrics[1] > max_lw: max_lw = sub_metrics[1]
        card_w = max_lw + int(size_px * 1.8)
        card_h = total_h + int(size_px * 1.2)
        card_x = (W - card_w) // 2
        card_y = (H - card_h) // 2
        shadow_layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow_layer)
        sd.rounded_rectangle(
            (card_x + S(12), card_y + S(24), card_x + card_w + S(12), card_y + card_h + S(24)),
            radius=S(24), fill=(0, 0, 0, 140),
        )
        shadow_layer = shadow_layer.filter(ImageFilter.GaussianBlur(S(20)))
        img.paste(shadow_layer, (0, 0), shadow_layer)
        draw.rounded_rectangle(
            (card_x, card_y, card_x + card_w, card_y + card_h),
            radius=S(24), fill=bg,
        )

    # ── Layout starting Y ──
    y_start = (H - total_h) // 2
    if has_cyrillic(text) and diacritic_pad > 0:
        y_start += S(40)                                       # bias down to compensate diacritic visual-center shift

    # ── Icon row ──
    if icon_char:
        tx = (W - t_w) // 2
        draw.text((tx, y_start), icon_char, font=ef, embedded_color=True, anchor="lt")
        y_start += t_h + int(line_gap * 1.6)
    elif silver_badge:
        bx = (W - badge_size) // 2
        by = y_start
        cx, cy = bx + badge_size // 2, by + badge_size // 2
        r = badge_size // 2
        draw.ellipse((cx - r, cy - r, cx + r, cy + r), fill=pal.gold)
        inner_r = int(r * 0.86)
        draw.ellipse((cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r), fill=pal.bg)
        badge_text = "#2"
        bf_size = int(badge_size * 0.5)
        bf = ImageFont.truetype(design.fonts.display, bf_size)
        bf_bbox = draw.textbbox((0, 0), badge_text, font=bf, anchor="lt")
        bw = bf_bbox[2] - bf_bbox[0]
        bf_ascent, bf_descent = bf.getmetrics()
        tx2 = cx - bw // 2
        ty2 = cy - (bf_ascent + bf_descent) // 2 + bf_ascent // 8
        draw.text((tx2 + S(3), ty2 + S(3)), badge_text, fill=(0, 0, 0), font=bf, anchor="lt")
        draw.text((tx2, ty2), badge_text, fill=pal.gold, font=bf, anchor="lt")
        y_start += badge_size + int(line_gap * 1.6)

    # ── Main text lines ──
    shadow_off = min(S(5), max(S(3), size_px // 70))
    for line, lw in line_metrics:
        x = (W - lw) // 2
        y_render = y_start + diacritic_pad
        draw.text((x + shadow_off, y_render + shadow_off), line, fill=(0, 0, 0), font=font, anchor="lt")
        draw.text((x, y_render), line, fill=color, font=font, anchor="lt")
        y_start += line_h + line_gap
    y_after_main = y_start - line_gap

    # ── Red underline ──
    if red_underline:
        ud = ImageDraw.Draw(img)
        line_w = S(design.underline_width)
        thickness = S(design.underline_thickness)
        line_x = (W - line_w) // 2
        line_y = y_after_main + S(18)
        ud.rectangle((line_x, line_y, line_x + line_w, line_y + thickness), fill=pal.red)
        y_start = max(y_start, line_y + thickness)

    # ── Subtitle ──
    if subtitle and sub_metrics:
        sub_text, sub_lw, _ = sub_metrics
        if subtitle_spaced:
            spaced_text = " ".join(list(sub_text))
            sub_bbox2 = draw.textbbox((0, 0), spaced_text, font=sub_font, anchor="lt")
            sub_lw = sub_bbox2[2] - sub_bbox2[0]
            sub_text_render = spaced_text
        else:
            sub_text_render = sub_text
        sub_x = (W - sub_lw) // 2
        y_start += S(22) if red_underline else int(line_gap * 0.5)
        if subtitle_color is not None:
            sc = subtitle_color
        else:
            sc = tuple(int(c * 0.7) for c in color) if isinstance(color, tuple) else color
        draw.text((sub_x + S(2), y_start + S(2)), sub_text_render, fill=(0, 0, 0), font=sub_font, anchor="lt")
        draw.text((sub_x, y_start), sub_text_render, fill=sc, font=sub_font, anchor="lt")

    # ── Red accent ──
    if red_accent:
        accent_draw = ImageDraw.Draw(img)
        last_line_w = line_metrics[-1][1]
        line_w = int(last_line_w * 0.95)
        line_x = (W - line_w) // 2
        line_y = y_after_main + S(22)
        accent_draw.rectangle((line_x, line_y, line_x + line_w, line_y + S(12)), fill=pal.red)

    # ── Vignette overlay ──
    if not accent_card:
        rgba = img.convert("RGBA")
        rgba.alpha_composite(vignette(design))
        img = rgba.convert("RGB")

    return np.array(img)
