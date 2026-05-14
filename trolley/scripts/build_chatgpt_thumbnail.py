from pathlib import Path
from PIL import Image, ImageDraw, ImageFont, ImageFilter


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data" / "thumbnails"
SRC = OUT / "chatgpt_image_background.png"
W, H = 1280, 720

FONT_BLACK = Path("C:/Windows/Fonts/ariblk.ttf")
FONT_BOLD = Path("C:/Windows/Fonts/arialbd.ttf")


def f(path: Path, size: int) -> ImageFont.FreeTypeFont:
    if not path.exists():
        path = FONT_BOLD
    return ImageFont.truetype(str(path), size=size)


def cover(img: Image.Image) -> Image.Image:
    sw, sh = img.size
    scale = max(W / sw, H / sh)
    nw, nh = int(sw * scale), int(sh * scale)
    img = img.resize((nw, nh), Image.Resampling.LANCZOS)
    left = (nw - W) // 2
    top = (nh - H) // 2
    return img.crop((left, top, left + W, top + H))


def text(draw, xy, value, font, fill, stroke=8, stroke_fill=(0, 0, 0), anchor=None):
    draw.text(
        xy,
        value,
        font=font,
        fill=fill,
        stroke_width=stroke,
        stroke_fill=stroke_fill,
        anchor=anchor,
    )


def fit_font(value: str, max_width: int, size: int) -> ImageFont.FreeTypeFont:
    probe = ImageDraw.Draw(Image.new("RGB", (10, 10)))
    while size > 20:
        font = f(FONT_BLACK, size)
        box = probe.textbbox((0, 0), value, font=font, stroke_width=8)
        if box[2] - box[0] <= max_width:
            return font
        size -= 2
    return f(FONT_BLACK, size)


def add_left_readability(base: Image.Image) -> Image.Image:
    overlay = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    px = overlay.load()
    for x in range(W):
        t = min(1, x / 650)
        alpha = int(245 * (1 - t) ** 1.45)
        for y in range(H):
            px[x, y] = (0, 0, 0, alpha)
    return Image.alpha_composite(base.convert("RGBA"), overlay)


def rounded_box(layer, box, fill, outline=None, width=6, radius=22):
    d = ImageDraw.Draw(layer)
    d.rounded_rectangle(box, radius=radius, fill=fill, outline=outline, width=width)


def build_final() -> Image.Image:
    base = cover(Image.open(SRC).convert("RGB"))
    base = add_left_readability(base)
    draw = ImageDraw.Draw(base)

    # MrBeast-style: one primary number, one scale number, one conflict tag.
    text(draw, (44, 32), "$1000", f(FONT_BLACK, 155), (43, 255, 99), stroke=12)

    text(draw, (48, 230), "30 000", f(FONT_BLACK, 118), (255, 255, 255), stroke=10)
    text(draw, (54, 348), "СТРОК КОДА", fit_font("СТРОК КОДА", 520, 62), (255, 255, 255), stroke=7)

    tag = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    rounded_box(tag, (44, 468, 398, 580), (255, 220, 42, 255), (0, 0, 0, 255), 7, 18)
    base = Image.alpha_composite(base, tag)
    draw = ImageDraw.Draw(base)
    draw.text((70, 486), "ВСЁ ИИ", font=f(FONT_BLACK, 68), fill=(0, 0, 0))

    # Small proof line, intentionally secondary.
    text(draw, (54, 610), "ЗА 13 ДНЕЙ", f(FONT_BLACK, 46), (255, 255, 255), stroke=6)
    return base


def build_thumb_preview(img: Image.Image) -> Image.Image:
    small = img.resize((320, 180), Image.Resampling.LANCZOS)
    canvas = Image.new("RGB", (360, 220), (22, 22, 22))
    canvas.paste(small.convert("RGB"), (20, 20))
    return canvas


if __name__ == "__main__":
    final = build_final()
    final_rgb = final.convert("RGB")
    final_rgb.save(OUT / "youtube_thumbnail_chatgpt_final.png", quality=95)
    final_rgb.save(OUT / "youtube_thumbnail_chatgpt_final.jpg", quality=95, optimize=True)
    build_thumb_preview(final).save(OUT / "youtube_thumbnail_chatgpt_mobile_preview.png")
    print(OUT / "youtube_thumbnail_chatgpt_final.png")
    print(OUT / "youtube_thumbnail_chatgpt_final.jpg")
    print(OUT / "youtube_thumbnail_chatgpt_mobile_preview.png")
