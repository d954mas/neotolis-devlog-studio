"""Image scene rendering: cover/contain fit, optional framed-card composition.

`make_image_clip` returns a numpy RGB array at design resolution. Used both
for standalone image chunks and as the background frame under overlay chunks.

framed_card=True wraps the image in a ~78%-wide rounded card on the brand bg
with a gold border, drop shadow, and interior radial vignette — useful when
a B-roll screenshot would otherwise feel "raw" on dark brand backgrounds.

All pixel values are at 1920-baseline; scaling via `design.px()`.
"""
from __future__ import annotations
import os
import math
from pathlib import Path
import numpy as np
from PIL import Image, ImageDraw, ImageFont, ImageFilter

from devlog.types import Design
from .text import has_cyrillic, pick_font


def _placeholder(src_path: str, design: Design) -> np.ndarray:
    """Minimal 'missing asset' plate so a failed render still produces something visible."""
    W, H = design.W, design.H
    img = Image.new("RGB", (W, H), design.palette.bg)
    draw = ImageDraw.Draw(img)
    label = f"[MISSING:\n{Path(src_path).name}]"
    f = ImageFont.truetype(design.fonts.display, design.px(70))
    bbox = draw.multiline_textbbox((0, 0), label, font=f)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
    draw.multiline_text(((W - tw) // 2, (H - th) // 2), label,
                        fill=design.palette.fg_dim, font=f, align="center")
    return np.array(img)


def make_image_clip(
    src_path: str,
    design: Design,
    fit: str = "cover",
    framed_card: bool = False,
    inset_label: str | None = None,
) -> np.ndarray:
    """Load image and resize to design resolution.

    fit="cover"   → scale to fill, center-crop overflow
    fit="contain" → scale to fit, letterbox with brand bg
    framed_card=True → 78%-wide rounded card with gold border + drop shadow
    """
    W, H = design.W, design.H
    pal = design.palette
    S = design.px

    if not os.path.exists(src_path):
        print(f"[warn] missing image {src_path}, using placeholder")
        return _placeholder(src_path, design)
    pil = Image.open(src_path).convert("RGB")
    iw, ih = pil.size

    # ── Framed-card variant ──
    if framed_card:
        canvas = Image.new("RGB", (W, H), pal.bg)
        card_w = int(W * 0.78)
        card_h = int(card_w * 9 / 16)
        # Cover-fit source into the card frame
        src_ratio = iw / ih
        tgt_ratio = card_w / card_h
        if src_ratio > tgt_ratio:
            nh, nw = card_h, int(card_h * src_ratio)
        else:
            nw, nh = card_w, int(card_w / src_ratio)
        pil_card = pil.resize((nw, nh), Image.LANCZOS)
        lx = (nw - card_w) // 2
        ty = (nh - card_h) // 2
        pil_card = pil_card.crop((lx, ty, lx + card_w, ty + card_h))
        cx = (W - card_w) // 2
        cy = (H - card_h) // 2

        # Shadow under card
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        sd = ImageDraw.Draw(shadow)
        sd.rounded_rectangle((cx + S(8), cy + S(16), cx + card_w + S(8), cy + card_h + S(16)),
                             radius=S(18), fill=(0, 0, 0, 170))
        shadow = shadow.filter(ImageFilter.GaussianBlur(S(20)))
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.paste(shadow, (0, 0), shadow)
        canvas = canvas_rgba.convert("RGB")
        canvas.paste(pil_card, (cx, cy))

        # Gold border
        bd = ImageDraw.Draw(canvas)
        bd.rounded_rectangle((cx - S(3), cy - S(3), cx + card_w + S(3), cy + card_h + S(3)),
                             radius=S(18), outline=pal.gold, width=S(6))

        # Interior radial vignette
        step = max(1, S(2))
        card_vignette = Image.new("RGBA", (card_w, card_h), (0, 0, 0, 0))
        ccx, ccy = card_w // 2, card_h // 2
        max_r_card = math.hypot(ccx, ccy)
        for yy in range(0, card_h, step):
            for xx in range(0, card_w, step):
                r = math.hypot(xx - ccx, yy - ccy) / max_r_card
                alpha = int(140 * (r ** 1.5))
                card_vignette.paste((0, 0, 0, alpha), (xx, yy, xx + step, yy + step))
        card_vignette = card_vignette.filter(ImageFilter.GaussianBlur(S(8)))
        card_with_vignette = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        card_with_vignette.paste(card_vignette, (cx, cy))
        canvas_rgba = canvas.convert("RGBA")
        canvas_rgba.alpha_composite(card_with_vignette)
        canvas = canvas_rgba.convert("RGB")
        bd = ImageDraw.Draw(canvas)

        # Inset label badge
        if inset_label:
            label_font = ImageFont.truetype(pick_font(inset_label, design), S(64))
            lbbox = bd.textbbox((0, 0), inset_label, font=label_font, anchor="lt")
            lw = lbbox[2] - lbbox[0]
            lh = lbbox[3] - lbbox[1]
            pad_x, pad_y = S(36), S(20)
            badge_x = cx + S(24)
            badge_y = cy + S(24)
            badge_x2 = badge_x + lw + pad_x * 2 + S(22)
            badge_y2 = badge_y + lh + pad_y * 2
            shadow2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
            sd2 = ImageDraw.Draw(shadow2)
            sd2.rounded_rectangle((badge_x + S(4), badge_y + S(8), badge_x2 + S(4), badge_y2 + S(8)),
                                  radius=S(10), fill=(0, 0, 0, 180))
            shadow2 = shadow2.filter(ImageFilter.GaussianBlur(S(12)))
            canvas_rgba = canvas.convert("RGBA")
            canvas_rgba.paste(shadow2, (0, 0), shadow2)
            canvas = canvas_rgba.convert("RGB")
            bd = ImageDraw.Draw(canvas)
            bd.rounded_rectangle((badge_x, badge_y, badge_x2, badge_y2), radius=S(10), fill=pal.bg)
            bd.rectangle((badge_x + S(10), badge_y + S(12), badge_x + S(18), badge_y2 - S(12)),
                         fill=pal.red)
            tx = badge_x + S(22) + pad_x
            ty = badge_y + pad_y
            bd.text((tx + S(2), ty + S(2)), inset_label, fill=(0, 0, 0), font=label_font, anchor="lt")
            bd.text((tx, ty), inset_label, fill=pal.gold, font=label_font, anchor="lt")
        return np.array(canvas)

    # ── Plain cover/contain fit ──
    target_ratio = W / H
    src_ratio = iw / ih
    if fit == "cover":
        if src_ratio > target_ratio:
            new_h = H
            new_w = int(H * src_ratio)
        else:
            new_w = W
            new_h = int(W / src_ratio)
        pil = pil.resize((new_w, new_h), Image.LANCZOS)
        left = (new_w - W) // 2
        top = (new_h - H) // 2
        pil = pil.crop((left, top, left + W, top + H))
    else:
        if src_ratio > target_ratio:
            new_w = W
            new_h = int(W / src_ratio)
        else:
            new_h = H
            new_w = int(H * src_ratio)
        pil = pil.resize((new_w, new_h), Image.LANCZOS)
        bg = Image.new("RGB", (W, H), pal.bg)
        bg.paste(pil, ((W - new_w) // 2, (H - new_h) // 2))
        pil = bg
    return np.array(pil)
