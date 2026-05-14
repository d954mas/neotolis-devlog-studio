"""Overlay text on scenes (B-roll video or image).

Two functions:
- overlay_label  → small caption pill stamped on an image (RGB → RGB)
- make_overlay_badge → full-width text band / centered card / hero text
                       returned as RGBA so it can composite over scene clips

All pixel values are at 1920-baseline; engine scales via `design.px()` so
the same overlay produces a proportionally identical image at any
resolution.
"""
from __future__ import annotations
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from devlog.types import Design
from .text import has_cyrillic, pick_font


# ─── Caption pill (small label stamped on B-roll image) ────────────

def overlay_label(
    img_arr: np.ndarray,
    text: str,
    design: Design,
    color: tuple[int, int, int] | None = None,
    position: str = "bottom-left",
    style: str = "default",
) -> np.ndarray:
    """Stamp a small label pill onto an RGB frame.

    style="default" → simple dark pill with gold text
    style="branded" → larger pill with red left-border accent
    """
    W, H = design.W, design.H
    pal = design.palette
    S = design.px
    color = color or pal.gold

    img = Image.fromarray(img_arr).convert("RGB")
    draw = ImageDraw.Draw(img)
    font_path = pick_font(text, design)

    font_size = S(90) if style == "branded" else S(70)
    pad_x = S(44) if style == "branded" else S(30)
    pad_y = S(26) if style == "branded" else S(18)
    edge_margin = S(90)

    font = ImageFont.truetype(font_path, font_size)
    bbox = draw.textbbox((0, 0), text, font=font, anchor="lt")
    tw = bbox[2] - bbox[0]
    th = bbox[3] - bbox[1]

    if position == "bottom-left":
        x, y = edge_margin, H - th - pad_y * 2 - edge_margin
    elif position == "top-left":
        x, y = edge_margin, edge_margin
    elif position == "bottom-right":
        x, y = W - tw - pad_x * 2 - edge_margin, H - th - pad_y * 2 - edge_margin
    else:
        x, y = W - tw - pad_x * 2 - edge_margin, edge_margin

    pill_x2 = x + tw + pad_x * 2
    pill_y2 = y + th + pad_y * 2

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((x + S(6), y + S(10), pill_x2 + S(6), pill_y2 + S(10)),
                         radius=S(16), fill=(0, 0, 0, 160))
    shadow = shadow.filter(ImageFilter.GaussianBlur(S(14)))
    img.paste(shadow, (0, 0), shadow)

    draw.rounded_rectangle((x, y, pill_x2, pill_y2), radius=S(16), fill=(20, 16, 12))

    if style == "branded":
        draw.rectangle((x + S(12), y + S(12), x + S(18), pill_y2 - S(12)), fill=pal.red)
        text_x = x + pad_x + S(18)
    else:
        text_x = x + pad_x

    draw.text((text_x + S(2), y + pad_y + S(2)), text, fill=(0, 0, 0), font=font, anchor="lt")
    draw.text((text_x, y + pad_y), text, fill=color, font=font, anchor="lt")
    return np.array(img)


# ─── Text band / card / hero overlay ───────────────────────────────

def make_overlay_badge(
    text: str,
    design: Design,
    subtitle: str | None = None,
    position: str = "bottom",
    style: str = "band",
) -> np.ndarray:
    """Render an overlay-kind chunk's visual layer (RGBA).

    Styles:
      band  — full-width text band at top/bottom with red left-border
      card  — centered prominent card with gold border and red accent
      hero  — centered large white text with thick black stroke (Veritasium-style)
    """
    W, H = design.W, design.H
    pal = design.palette
    S = design.px

    canvas = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)

    # ── HERO style ──
    if style == "hero":
        text_size = S(140)
        sub_size = S(64)
        f_main = ImageFont.truetype(pick_font(text, design), text_size)
        f_sub = ImageFont.truetype(pick_font(subtitle, design), sub_size) if subtitle else None
        bbox = draw.textbbox((0, 0), text, font=f_main, anchor="lt")
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        sub_h = sub_size + S(24) if subtitle else 0
        block_h = th + sub_h + S(20)
        block_y = (H - block_h) // 2
        tx = (W - tw) // 2
        ty = block_y
        stroke_w = S(8)
        for dx in range(-stroke_w, stroke_w + 1, max(1, S(2))):
            for dy in range(-stroke_w, stroke_w + 1, max(1, S(2))):
                if dx * dx + dy * dy <= stroke_w * stroke_w:
                    draw.text((tx + dx, ty + dy), text, fill=(0, 0, 0, 255), font=f_main, anchor="lt")
        draw.text((tx, ty), text, fill=(255, 255, 255, 255), font=f_main, anchor="lt")
        if subtitle and f_sub:
            sb = draw.textbbox((0, 0), subtitle, font=f_sub, anchor="lt")
            sw = sb[2] - sb[0]
            sx = (W - sw) // 2
            sy = ty + th + S(24)
            sub_stroke = S(4)
            for dx in range(-sub_stroke, sub_stroke + 1, max(1, S(2))):
                for dy in range(-sub_stroke, sub_stroke + 1, max(1, S(2))):
                    draw.text((sx + dx, sy + dy), subtitle, fill=(0, 0, 0, 255), font=f_sub, anchor="lt")
            draw.text((sx, sy), subtitle, fill=(*pal.gold, 255), font=f_sub, anchor="lt")
        return np.array(canvas)

    # ── CARD style ──
    if style == "card":
        text_size = S(180)
        sub_size = S(80)
        f_main = ImageFont.truetype(pick_font(text, design), text_size)
        f_sub = ImageFont.truetype(pick_font(subtitle, design), sub_size) if subtitle else None

        pad_x = S(design.overlay_card_pad_x)
        ml = "\n" in text
        line_spacing = int(text_size * 0.22)
        MAX_CARD_W = W - S(160)
        MAX_CARD_H = H - S(200)
        for _ in range(8):
            bbox = draw.multiline_textbbox((0, 0), text, font=f_main, spacing=line_spacing) if ml \
                else draw.textbbox((0, 0), text, font=f_main)
            tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
            sub_h = sub_size + S(20) if subtitle else 0
            if tw + pad_x * 2 <= MAX_CARD_W and th + sub_h + S(160) <= MAX_CARD_H:
                break
            text_size = int(text_size * 0.88)
            sub_size = int(sub_size * 0.88)
            line_spacing = int(text_size * 0.22)
            f_main = ImageFont.truetype(pick_font(text, design), text_size)
            f_sub = ImageFont.truetype(pick_font(subtitle, design), sub_size) if subtitle else None
        bbox = draw.multiline_textbbox((0, 0), text, font=f_main, spacing=line_spacing) if ml \
            else draw.textbbox((0, 0), text, font=f_main)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        sub_h = sub_size + S(20) if subtitle else 0
        pad_y = S(80)
        card_w = max(tw + pad_x * 2, S(900))
        card_h = th + sub_h + pad_y * 2
        cx = (W - card_w) // 2
        cy = (H - card_h) // 2
        # Shadow
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle((cx + S(8), cy + S(16), cx + card_w + S(8), cy + card_h + S(16)),
                             radius=S(24), fill=(0, 0, 0, 220))
        shadow = shadow.filter(ImageFilter.GaussianBlur(S(28)))
        canvas.alpha_composite(shadow)
        draw = ImageDraw.Draw(canvas)
        # Card body + gold border
        draw.rounded_rectangle((cx, cy, cx + card_w, cy + card_h),
                               radius=S(24), fill=(20, 16, 12, 235))
        draw.rounded_rectangle((cx, cy, cx + card_w, cy + card_h),
                               radius=S(24), outline=(*pal.gold, 255), width=S(5))
        # Red left accent bar
        draw.rectangle((cx, cy + S(30), cx + S(14), cy + card_h - S(30)), fill=(*pal.red, 255))
        # Text
        tx = (W - tw) // 2
        ty = cy + pad_y
        if ml:
            draw.multiline_text((tx + S(5), ty + S(5)), text, fill=(0, 0, 0, 255), font=f_main,
                                spacing=line_spacing, align="center")
            draw.multiline_text((tx, ty), text, fill=(*pal.gold, 255), font=f_main,
                                spacing=line_spacing, align="center")
        else:
            draw.text((tx + S(5), ty + S(5)), text, fill=(0, 0, 0, 255), font=f_main)
            draw.text((tx, ty), text, fill=(*pal.gold, 255), font=f_main)
        if subtitle and f_sub:
            sbbox = draw.textbbox((0, 0), subtitle, font=f_sub, anchor="lt")
            sw = sbbox[2] - sbbox[0]
            sx = (W - sw) // 2
            sy = ty + th + S(20)
            draw.text((sx + S(3), sy + S(3)), subtitle, fill=(0, 0, 0, 255), font=f_sub, anchor="lt")
            draw.text((sx, sy), subtitle, fill=(*pal.gold_dim, 255), font=f_sub, anchor="lt")
        return np.array(canvas)

    # ── BAND style (default) ──
    text_size = S(96)
    sub_size = S(44)
    f_main = ImageFont.truetype(pick_font(text, design), text_size)
    f_sub = ImageFont.truetype(pick_font(subtitle, design), sub_size) if subtitle else None
    bbox = draw.textbbox((0, 0), text, font=f_main)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    sub_h = sub_size + S(20) if subtitle else 0

    pad_v = S(design.overlay_band_pad_v)
    margin = S(60)
    red_bar_w = S(12)
    band_h = th + pad_v + sub_h

    if position == "bottom":
        band_y = H - band_h - margin
    elif position == "top":
        band_y = margin
    else:
        band_y = (H - band_h) // 2

    draw.rectangle((0, band_y, W, band_y + band_h), fill=(20, 16, 12, 240))
    draw.line([(red_bar_w + S(2), band_y), (W, band_y)], fill=(*pal.gold, 100), width=max(1, S(2)))
    draw.rectangle((0, band_y, red_bar_w, band_y + band_h), fill=pal.red)

    fade_px = S(12)
    for yy in range(fade_px):
        alpha = int(240 * (yy / max(1, fade_px)))
        draw.line([(red_bar_w + S(2), band_y + yy), (W, band_y + yy)], fill=(20, 16, 12, alpha))

    tx = (W - tw) // 2
    ty = band_y + S(40)
    draw.text((tx + S(3), ty + S(3)), text, fill=(0, 0, 0, 255), font=f_main, anchor="lt")
    draw.text((tx, ty), text, fill=(*pal.gold, 255), font=f_main, anchor="lt")

    if subtitle and f_sub:
        sbbox = draw.textbbox((0, 0), subtitle, font=f_sub, anchor="lt")
        sw = sbbox[2] - sbbox[0]
        sx = (W - sw) // 2
        sy = ty + th + S(22)
        draw.text((sx + S(2), sy + S(2)), subtitle, fill=(0, 0, 0, 255), font=f_sub, anchor="lt")
        draw.text((sx, sy), subtitle, fill=(*pal.gold_dim, 255), font=f_sub, anchor="lt")

    return np.array(canvas)
