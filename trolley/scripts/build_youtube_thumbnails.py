from pathlib import Path
from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageEnhance


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "thumbnails"
OUT.mkdir(parents=True, exist_ok=True)

W, H = 1280, 720
FONT_BLACK = Path("C:/Windows/Fonts/arialbd.ttf")
FONT_HEAVY = Path("C:/Windows/Fonts/impact.ttf")
FONT_UI = Path("C:/Windows/Fonts/bahnschrift.ttf")


def font(path, size):
    return ImageFont.truetype(str(path), size=size)


def cover(img, size=(W, H), focus=(0.5, 0.5)):
    sw, sh = img.size
    tw, th = size
    scale = max(tw / sw, th / sh)
    nw, nh = int(sw * scale), int(sh * scale)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    fx, fy = focus
    left = max(0, min(nw - tw, int(nw * fx - tw / 2)))
    top = max(0, min(nh - th, int(nh * fy - th / 2)))
    return img.crop((left, top, left + tw, top + th))


def add_gradient_dark(base, left_strength=210, right_strength=35):
    overlay = Image.new("RGBA", base.size, (0, 0, 0, 0))
    px = overlay.load()
    for x in range(W):
        a = int(left_strength + (right_strength - left_strength) * (x / (W - 1)))
        for y in range(H):
            px[x, y] = (0, 0, 0, max(0, a))
    return Image.alpha_composite(base.convert("RGBA"), overlay)


def text_bbox(draw, xy, text, fnt, stroke_width=0):
    return draw.textbbox(xy, text, font=fnt, stroke_width=stroke_width)


def draw_text(draw, xy, text, fnt, fill, stroke=(0, 0, 0), sw=8, anchor=None):
    draw.text(xy, text, font=fnt, fill=fill, stroke_width=sw, stroke_fill=stroke, anchor=anchor)


def fit_font(text, path, max_w, start, min_size=32, stroke=8):
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    for size in range(start, min_size - 1, -2):
        f = font(path, size)
        box = probe.textbbox((0, 0), text, font=f, stroke_width=stroke)
        if box[2] - box[0] <= max_w:
            return f
    return font(path, min_size)


def rounded_panel(draw, box, fill, outline=None, width=6, radius=24):
    draw.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def paste_with_shadow(base, img, xy, scale=1.0, shadow=18):
    img = img.convert("RGBA")
    if scale != 1.0:
        img = img.resize((int(img.width * scale), int(img.height * scale)), Image.Resampling.LANCZOS)
    alpha = img.getchannel("A")
    sh = Image.new("RGBA", img.size, (0, 0, 0, 180))
    sh.putalpha(alpha.filter(ImageFilter.GaussianBlur(shadow)))
    base.alpha_composite(sh, (xy[0] + 12, xy[1] + 16))
    base.alpha_composite(img, xy)


def make_money_first():
    bg = Image.open(ROOT / "data" / "promo_itch" / "banner_v2_source.png")
    bg = cover(bg, focus=(0.68, 0.48))
    bg = ImageEnhance.Contrast(bg).enhance(1.08)
    bg = ImageEnhance.Color(bg).enhance(1.12)
    base = add_gradient_dark(bg, left_strength=245, right_strength=45)
    draw = ImageDraw.Draw(base)

    rounded_panel(draw, (38, 34, 420, 150), (255, 206, 55, 255), (10, 10, 10, 255), 8, 18)
    draw_text(draw, (58, 42), "ВСЁ ИИ", font(FONT_BLACK, 78), (10, 10, 10), sw=0)

    draw_text(draw, (48, 156), "30 000", font(FONT_HEAVY, 126), (255, 255, 255), sw=9)
    draw_text(draw, (54, 282), "СТРОК КОДА", fit_font("СТРОК КОДА", FONT_BLACK, 565, 78), (255, 255, 255), sw=7)

    rounded_panel(draw, (42, 408, 580, 645), (12, 12, 12, 220), (244, 42, 42, 255), 8, 26)
    draw_text(draw, (74, 408), "$1000", font(FONT_HEAVY, 184), (61, 255, 117), stroke=(0, 0, 0), sw=10)
    draw_text(draw, (85, 596), "ЗА ДЖЕМ", font(FONT_BLACK, 52), (255, 226, 82), sw=5)

    draw.line((610, 380, 805, 448), fill=(255, 50, 45, 255), width=18)
    draw.polygon([(805, 448), (750, 405), (765, 488)], fill=(255, 50, 45, 255))
    return base


def make_recommended():
    bg = Image.open(ROOT / "data" / "promo_itch" / "banner_v2_source.png")
    bg = cover(bg, focus=(0.68, 0.48))
    bg = ImageEnhance.Contrast(bg).enhance(1.12)
    bg = ImageEnhance.Color(bg).enhance(1.12)
    base = add_gradient_dark(bg, left_strength=248, right_strength=38)
    draw = ImageDraw.Draw(base)

    rounded_panel(draw, (40, 34, 602, 214), (10, 10, 10, 235), (61, 255, 117, 255), 8, 24)
    draw_text(draw, (70, 22), "$1000", font(FONT_HEAVY, 176), (61, 255, 117), sw=10)

    draw_text(draw, (44, 232), "30 000", font(FONT_HEAVY, 126), (255, 255, 255), sw=9)
    draw_text(draw, (52, 354), "СТРОК КОДА", fit_font("СТРОК КОДА", FONT_BLACK, 560, 72), (255, 255, 255), sw=7)

    rounded_panel(draw, (42, 468, 392, 580), (244, 42, 42, 255), (255, 255, 255, 255), 5, 18)
    draw_text(draw, (64, 478), "ВСЁ ИИ", font(FONT_BLACK, 74), (255, 255, 255), sw=0)

    rounded_panel(draw, (414, 470, 622, 580), (255, 210, 57, 255), (8, 8, 8, 255), 6, 18)
    draw_text(draw, (436, 486), "13 ДНЕЙ", font(FONT_BLACK, 50), (8, 8, 8), sw=0)

    draw.line((620, 382, 806, 452), fill=(255, 50, 45, 255), width=18)
    draw.polygon([(806, 452), (752, 408), (764, 492)], fill=(255, 50, 45, 255))

    # Extra vignette keeps the readable area clean when YouTube shrinks the image.
    shade = Image.new("RGBA", base.size, (0, 0, 0, 0))
    sd = ImageDraw.Draw(shade)
    sd.rectangle((0, H - 92, W, H), fill=(0, 0, 0, 80))
    base = Image.alpha_composite(base, shade)
    return base


def make_ai_confession():
    bg = Image.open(ROOT / "data" / "itch" / "chaos_gameplay_clean.png")
    bg = cover(bg, focus=(0.50, 0.48))
    bg = ImageEnhance.Contrast(bg).enhance(1.16)
    bg = ImageEnhance.Color(bg).enhance(1.10)
    base = add_gradient_dark(bg, left_strength=230, right_strength=80)
    draw = ImageDraw.Draw(base)

    rounded_panel(draw, (42, 40, 370, 130), (244, 42, 42, 255), (255, 255, 255, 255), 5, 18)
    draw_text(draw, (68, 47), "НЕ ПИСАЛ", font(FONT_BLACK, 58), (255, 255, 255), sw=0)

    draw_text(draw, (46, 154), "30 000", font(FONT_HEAVY, 132), (255, 218, 69), sw=10)
    draw_text(draw, (54, 286), "СТРОК", font(FONT_HEAVY, 112), (255, 255, 255), sw=9)
    draw_text(draw, (54, 404), "ВСЁ ИИ", font(FONT_HEAVY, 116), (255, 255, 255), sw=9)

    rounded_panel(draw, (690, 42, 1218, 190), (255, 210, 57, 245), (8, 8, 8, 255), 8, 24)
    draw_text(draw, (722, 39), "$1000", font(FONT_HEAVY, 132), (8, 8, 8), sw=0)

    rounded_panel(draw, (720, 572, 1214, 668), (12, 12, 12, 230), (255, 210, 57, 255), 6, 18)
    draw_text(draw, (750, 587), "ЗА 13 ДНЕЙ", font(FONT_BLACK, 58), (255, 255, 255), sw=4)
    return base


def make_winner_proof():
    bg = Image.open(ROOT / "data" / "itch" / "wavedash_winners_mobile.jpg")
    bg = cover(bg, focus=(0.52, 0.40))
    bg = bg.filter(ImageFilter.GaussianBlur(1.2))
    bg = ImageEnhance.Contrast(bg).enhance(1.18)
    base = add_gradient_dark(bg, left_strength=230, right_strength=130)
    draw = ImageDraw.Draw(base)

    gameplay = Image.open(ROOT / "data" / "promo_itch" / "cover_v1_source.png")
    gameplay = gameplay.resize((470, 470), Image.Resampling.LANCZOS)
    paste_with_shadow(base, gameplay, (760, 180), scale=1.0, shadow=14)

    rounded_panel(draw, (42, 34, 555, 144), (255, 210, 57, 255), (0, 0, 0, 255), 8, 18)
    draw_text(draw, (68, 42), "WINNER", font(FONT_HEAVY, 88), (0, 0, 0), sw=0)

    draw_text(draw, (42, 158), "$1000", font(FONT_HEAVY, 168), (60, 255, 115), sw=11)
    draw_text(draw, (50, 325), "ВСЁ ИИ", font(FONT_HEAVY, 126), (255, 255, 255), sw=10)
    draw_text(draw, (52, 462), "30 000", font(FONT_HEAVY, 108), (255, 223, 80), sw=8)
    draw_text(draw, (58, 570), "СТРОК КОДА", font(FONT_BLACK, 58), (255, 255, 255), sw=5)
    return base


def save(img, name):
    path = OUT / name
    img.convert("RGB").save(path, quality=95)
    return path


if __name__ == "__main__":
    recommended = make_recommended()
    paths = [
        save(recommended, "youtube_thumbnail_final.png"),
        save(recommended, "youtube_thumbnail_v4_recommended_1000_30k_ai.png"),
        save(make_money_first(), "youtube_thumbnail_v1_money_ai_30k.png"),
        save(make_ai_confession(), "youtube_thumbnail_v2_no_code_30k_1000.png"),
        save(make_winner_proof(), "youtube_thumbnail_v3_winner_proof.png"),
    ]
    jpg_path = OUT / "youtube_thumbnail_final.jpg"
    recommended.convert("RGB").save(jpg_path, quality=95, optimize=True)
    paths.append(jpg_path)
    for p in paths:
        print(p)
