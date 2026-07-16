"""Decoration passes: each takes the content raster (RGBA) and returns a
new RGBA raster with the decoration composited on top. Independent by
design — no reflow of the content underneath (v2 "composition over flags":
see docs/ARCHITECTURE_V2.md). Order is `chunk.decorations` list order.

Port mapping (v1 -> v2), each intentionally simplified to work over ANY
content raster rather than being coupled to one content renderer's layout:
- Underline   <- plate.py red_underline (fixed-width gold bar under text).
                 Uses `Layout.text_bottom` when available (Plate content);
                 falls back to a fixed frame-relative position otherwise.
- Badge       <- plate.py trophy/medal/silver_badge. Emoji icons dropped
                 (v2 Fonts has no emoji slot); ported as the silver-badge
                 medallion look (ring + inner disc + numeral), generalized
                 to any `name` via a small numeral lookup.
- FramedCard  <- image.py framed_card AND plate.py accent_card, unified:
                 both were "wrap the visual in an inset card on brand bg";
                 as a decoration it insets whatever raster it's given.
- Vignette    <- effects.py vignette / plate.py's always-on vignette.
                 Now opt-in (must be listed in decorations) instead of
                 automatically applied "if not accent_card". Vectorized —
                 see `_effects.py`.
- Label       <- overlay.py overlay_label (default/branded small pill,
                 bottom-left, used for B-roll captions).
- CaptionPill <- image.py's inset_label badge (top-left, red-accent bar +
                 gold text, used inside framed_card in v1). `variant` field
                 doesn't exist on CaptionPill in the model — always renders
                 the inset-badge look.
"""
from __future__ import annotations

from collections.abc import Callable

from PIL import Image, ImageDraw, ImageFilter

from dlstudio.model import Badge, CaptionPill, Decoration, Design, FramedCard, Label, Underline, Vignette

from ._effects import radial_alpha_mask, vignette_layer
from ._util import Layout, font_path, hex_to_rgb, load_font, text_box

# Badge name -> short numeral label. Not a brand constant (no colors/sizes)
# — just semantic mapping from a badge's name to its printed ordinal.
_BADGE_NUMERALS = {
    "trophy": "1", "gold": "1", "first": "1", "1st": "1",
    "silver": "2", "second": "2", "2nd": "2",
    "bronze": "3", "third": "3", "3rd": "3",
}


def apply_decoration(img: Image.Image, deco: Decoration, design: Design, layout: Layout) -> Image.Image:
    """Composite one decoration. Dispatch via DECORATION_RENDERERS (registered
    at module bottom) so a new Decoration type is one registry entry + its pass
    here, not an isinstance-ladder edit (finding L4)."""
    renderer = DECORATION_RENDERERS.get(type(deco))
    if renderer is None:  # pragma: no cover — union is closed
        raise TypeError(f"unknown decoration type: {type(deco).__name__}")
    return renderer(img, deco, design, layout)


def _underline(img: Image.Image, deco: Underline, design: Design, layout: Layout) -> Image.Image:
    W, H = img.size
    color = hex_to_rgb(design.palette.color(deco.color))
    width = max(1, round(W * deco.width_ratio))
    thickness = max(1, design.px(11))
    x = (W - width) // 2
    if layout.text_bottom is not None:
        y = layout.text_bottom + design.px(18)
    else:
        y = int(H * 0.62)  # generic fallback for non-text content
    out = img.copy()
    draw = ImageDraw.Draw(out)
    draw.rectangle((x, y, x + width, y + thickness), fill=(*color, 255))
    return out


def _badge(img: Image.Image, deco: Badge, design: Design, layout: Layout) -> Image.Image:
    W, H = img.size
    ring_rgb = hex_to_rgb(design.palette.color("accent"))
    inner_rgb = hex_to_rgb(design.palette.color("bg"))

    diameter = layout.main_size_px if layout.main_size_px else design.px(160)
    radius = diameter // 2
    cx = layout.text_center_x if layout.text_center_x is not None else W // 2
    if layout.text_top is not None:
        cy = max(radius + design.px(40), layout.text_top - design.px(90) - radius)
    else:
        cy = design.px(140) + radius

    out = img.copy()
    draw = ImageDraw.Draw(out)
    draw.ellipse((cx - radius, cy - radius, cx + radius, cy + radius), fill=(*ring_rgb, 255))
    inner_r = int(radius * 0.86)
    draw.ellipse((cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r), fill=(*inner_rgb, 255))

    label = _badge_label(deco.name)
    font = load_font(design, "bold", int(diameter * 0.5))
    bbox = draw.textbbox((0, 0), label, font=font, anchor="lt")
    bw = bbox[2] - bbox[0]
    ascent, descent = font.getmetrics()
    tx = cx - bw // 2
    ty = cy - (ascent + descent) // 2 + ascent // 8
    shadow_off = max(1, design.px(3))
    draw.text((tx + shadow_off, ty + shadow_off), label, fill=(0, 0, 0, 255), font=font, anchor="lt")
    draw.text((tx, ty), label, fill=(*ring_rgb, 255), font=font, anchor="lt")
    return out


def _badge_label(name: str) -> str:
    key = name.strip().lower()
    if key in _BADGE_NUMERALS:
        return f"#{_BADGE_NUMERALS[key]}"
    return name[:3].upper() if name else "#1"


def _framed_card(img: Image.Image, deco: FramedCard, design: Design, layout: Layout) -> Image.Image:
    W, H = img.size
    bg_rgb = hex_to_rgb(design.palette.color("bg"))
    accent_rgb = hex_to_rgb(design.palette.color("accent"))

    pad = max(0.0, min(0.45, deco.pad_ratio))
    card_w = max(1, round(W * (1 - 2 * pad)))
    card_h = max(1, round(H * (1 - 2 * pad)))
    cx = (W - card_w) // 2
    cy = (H - card_h) // 2

    src = img.convert("RGBA")
    src_ratio = src.width / src.height if src.height else card_w / card_h
    box_ratio = card_w / card_h
    if src_ratio > box_ratio:
        nw = card_w
        nh = max(1, round(card_w / src_ratio))
    else:
        nh = card_h
        nw = max(1, round(card_h * src_ratio))
    resized = src.resize((nw, nh), Image.LANCZOS)

    canvas = Image.new("RGBA", (W, H), (*bg_rgb, 255))

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(
        (cx + design.px(8), cy + design.px(16), cx + card_w + design.px(8), cy + card_h + design.px(16)),
        radius=design.px(18), fill=(0, 0, 0, 170),
    )
    shadow = shadow.filter(ImageFilter.GaussianBlur(design.px(20)))
    canvas.alpha_composite(shadow)

    inset_x = cx + (card_w - nw) // 2
    inset_y = cy + (card_h - nh) // 2
    canvas.alpha_composite(resized, (inset_x, inset_y))

    # Interior radial vignette, vectorized (replaces legacy image.py's
    # nested-pixel-loop card vignette).
    mask = radial_alpha_mask(nw, nh, max_alpha=140, exponent=1.5, blur_radius=max(1, design.px(8)))
    dark = Image.new("RGBA", (nw, nh), (0, 0, 0, 255))
    transparent = Image.new("RGBA", (nw, nh), (0, 0, 0, 0))
    inner_vignette = Image.composite(dark, transparent, mask)
    canvas.alpha_composite(inner_vignette, (inset_x, inset_y))

    border = ImageDraw.Draw(canvas)
    border.rounded_rectangle(
        (cx - design.px(3), cy - design.px(3), cx + card_w + design.px(3), cy + card_h + design.px(3)),
        radius=design.px(18), outline=(*accent_rgb, 255), width=max(1, design.px(6)),
    )
    return canvas


def _vignette(img: Image.Image, deco: Vignette, design: Design, layout: Layout) -> Image.Image:
    out = img.convert("RGBA").copy()
    out.alpha_composite(vignette_layer(design, deco.strength))
    return out


def _label(img: Image.Image, deco: Label, design: Design, layout: Layout) -> Image.Image:
    """Small pill stamped bottom-left. `variant="branded"` adds the accent
    left-border bar; anything else uses the plain look."""
    W, H = img.size
    branded = deco.variant == "branded"
    accent_rgb = hex_to_rgb(design.palette.color("accent"))
    bg_rgb = hex_to_rgb(design.palette.color("bg"))

    font_size = design.px(90) if branded else design.px(70)
    pad_x = design.px(44) if branded else design.px(30)
    pad_y = design.px(26) if branded else design.px(18)
    edge_margin = design.px(90)

    canvas = img.convert("RGBA").copy()
    font = load_font(design, "bold", font_size)
    draw = ImageDraw.Draw(canvas)
    tw, th = text_box(draw, deco.text, font)

    x = edge_margin
    y = H - th - pad_y * 2 - edge_margin
    x2 = x + tw + pad_x * 2
    y2 = y + th + pad_y * 2

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((x + design.px(6), y + design.px(10), x2 + design.px(6), y2 + design.px(10)),
                          radius=design.px(16), fill=(0, 0, 0, 160))
    shadow = shadow.filter(ImageFilter.GaussianBlur(design.px(14)))
    canvas.alpha_composite(shadow)

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((x, y, x2, y2), radius=design.px(16), fill=(*bg_rgb, 235))

    if branded:
        draw.rectangle((x + design.px(12), y + design.px(12), x + design.px(18), y2 - design.px(12)),
                        fill=(*accent_rgb, 255))
        text_x = x + pad_x + design.px(18)
    else:
        text_x = x + pad_x

    draw.text((text_x + design.px(2), y + pad_y + design.px(2)), deco.text, fill=(0, 0, 0, 255), font=font, anchor="lt")
    draw.text((text_x, y + pad_y), deco.text, fill=(*accent_rgb, 255), font=font, anchor="lt")
    return canvas


def _caption_pill(img: Image.Image, deco: CaptionPill, design: Design, layout: Layout) -> Image.Image:
    """Top-left inset badge: red/accent left bar + gold-ish text on a dark
    pill. Ported from legacy image.py's `inset_label` (used inside
    framed_card there; here it's an independent, composable pass)."""
    W, H = img.size
    accent_rgb = hex_to_rgb(design.palette.color("accent"))
    bg_rgb = hex_to_rgb(design.palette.color("bg"))

    font = load_font(design, "bold", design.px(64))
    canvas = img.convert("RGBA").copy()
    draw = ImageDraw.Draw(canvas)
    tw, th = text_box(draw, deco.text, font)

    pad_x, pad_y = design.px(36), design.px(20)
    margin = design.px(24)
    x, y = margin, margin
    x2 = x + tw + pad_x * 2 + design.px(22)
    y2 = y + th + pad_y * 2

    shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle((x + design.px(4), y + design.px(8), x2 + design.px(4), y2 + design.px(8)),
                          radius=design.px(10), fill=(0, 0, 0, 180))
    shadow = shadow.filter(ImageFilter.GaussianBlur(design.px(12)))
    canvas.alpha_composite(shadow)

    draw = ImageDraw.Draw(canvas)
    draw.rounded_rectangle((x, y, x2, y2), radius=design.px(10), fill=(*bg_rgb, 255))
    draw.rectangle((x + design.px(10), y + design.px(12), x + design.px(18), y2 - design.px(12)),
                   fill=(*accent_rgb, 255))
    tx = x + design.px(22) + pad_x
    ty = y + pad_y
    draw.text((tx + design.px(2), ty + design.px(2)), deco.text, fill=(0, 0, 0, 255), font=font, anchor="lt")
    draw.text((tx, ty), deco.text, fill=(*accent_rgb, 255), font=font, anchor="lt")
    return canvas


# ─── Registry ──────────────────────────────────────────────────────────────
# Decoration type -> pass. Dead-simple dict dispatch (no plugin framework):
# adding a decoration is one line here plus its `_<x>` pass above.
DecorationPass = Callable[[Image.Image, Decoration, Design, Layout], Image.Image]

DECORATION_RENDERERS: dict[type, DecorationPass] = {
    Underline: _underline,
    Badge: _badge,
    FramedCard: _framed_card,
    Vignette: _vignette,
    Label: _label,
    CaptionPill: _caption_pill,
}
