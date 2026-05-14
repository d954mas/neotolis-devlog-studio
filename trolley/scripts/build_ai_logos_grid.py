"""Build a 4x2 grid of AI tool logos for a2-2 hype section."""
import os
from PIL import Image, ImageDraw, ImageFilter, ImageFont

W, H = 1920, 1080
COL_BG = (26, 22, 18)
COL_GOLD = (232, 182, 71)

LOGOS = [
    ("data/ai_hype/logo_openai.png",    "ChatGPT"),
    ("data/ai_hype/logo_midjourney.png","Midjourney"),
    ("data/ai_hype/logo_gemini.png",    "Gemini"),
    ("data/ai_hype/logo_claude.png",    "Claude"),
    ("data/ai_hype/logo_copilot.png",   "Copilot"),
    ("data/ai_hype/logo_grok.png",      "Grok"),
    ("data/ai_hype/logo_perplexity.png","Perplexity"),
    ("data/ai_hype/logo_stability.png", "Stable Diff"),
]

def build():
    canvas = Image.new("RGB", (W, H), COL_BG)

    # subtle city bg
    city = Image.open("data/itch/snap_city.png").convert("RGB").resize((W, H), Image.LANCZOS)
    city = city.filter(ImageFilter.GaussianBlur(18))
    canvas = Image.blend(canvas, city, 0.15)

    cols, rows = 4, 2
    cell_w = W // cols
    cell_h = H // rows
    logo_size = 200  # icon square
    font_size = 38

    try:
        font = ImageFont.truetype("C:/Windows/Fonts/bahnschrift.ttf", font_size)
    except:
        font = ImageFont.load_default()

    draw = ImageDraw.Draw(canvas)

    for i, (path, label) in enumerate(LOGOS):
        col = i % cols
        row = i // cols
        cx = col * cell_w + cell_w // 2
        cy = row * cell_h + cell_h // 2 - 20  # shift up slightly for label

        # Load and resize logo
        try:
            logo = Image.open(path).convert("RGBA")
            logo = logo.resize((logo_size, logo_size), Image.LANCZOS)

            # Paste with alpha
            paste_x = cx - logo_size // 2
            paste_y = cy - logo_size // 2
            canvas.paste(logo, (paste_x, paste_y), logo)
        except Exception as e:
            print(f"  skip {path}: {e}")

        # Label below
        label_y = cy + logo_size // 2 + 12
        bbox = draw.textbbox((0, 0), label, font=font)
        lw = bbox[2] - bbox[0]
        draw.text((cx - lw // 2, label_y), label, fill=COL_GOLD, font=font)

    out = "data/ai_hype/ai_logos_grid.png"
    canvas.save(out)
    print(f"Saved {out}")

if __name__ == "__main__":
    build()
