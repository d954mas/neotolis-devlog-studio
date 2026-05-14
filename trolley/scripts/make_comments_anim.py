"""Creates itch_comments_anim.mp4 — 6 real comment screenshots appear over game bg."""
import numpy as np
from PIL import Image, ImageFilter
from moviepy.video.VideoClip import VideoClip

SHOTS = [
    r"C:\Users\ROG\YandexDisk\Скриншоты\2026-05-14_13-29-58.png",
    r"C:\Users\ROG\YandexDisk\Скриншоты\2026-05-14_13-30-10.png",
    r"C:\Users\ROG\YandexDisk\Скриншоты\2026-05-14_13-30-25.png",
    r"C:\Users\ROG\YandexDisk\Скриншоты\2026-05-14_13-30-35.png",
    r"C:\Users\ROG\YandexDisk\Скриншоты\2026-05-14_13-30-49.png",
    r"C:\Users\ROG\YandexDisk\Скриншоты\2026-05-14_13-30-57.png",
]

BG_PATH = r"C:\projects\devlogs\trolley\data\itch\snap_village_artshot.png"
OUT     = r"C:\projects\devlogs\trolley\data\itch\itch_comments_anim.mp4"

W, H   = 1920, 1080
FPS    = 30
DUR    = 5.5   # seconds — matches ~words 0-10 of a2-5

MAX_CARD_W   = 560     # scale wide cards down; keep narrow ones native
APPEAR_INT   = 0.65    # seconds between each comment appearing
FADE_DUR     = 0.18    # fade-in duration per card

# Fixed 3-column x anchors; rows at y=40 and y=360
COL_X = [55, 700, 1350]
ROW_Y = [40, 360]

POSITIONS = [
    (COL_X[0], ROW_Y[0]),
    (COL_X[1], ROW_Y[0]),
    (COL_X[2], ROW_Y[0]),
    (COL_X[0], ROW_Y[1]),
    (COL_X[1], ROW_Y[1]),
    (COL_X[2], ROW_Y[1]),
]

# ---------- prep background ----------
bg = Image.open(BG_PATH).convert("RGB").resize((W, H), Image.LANCZOS)
bg_arr = np.array(bg, dtype=np.float32)
dark   = np.array([26, 22, 18], dtype=np.float32)   # COL_BG
# darken game to 55% so cards read clearly
bg_dark = np.clip(bg_arr * 0.55 + dark * 0.45, 0, 255).astype(np.uint8)

# ---------- prep cards ----------
cards = []
for path in SHOTS:
    img = Image.open(path).convert("RGBA")
    w = min(img.width, MAX_CARD_W)
    ratio = w / img.width
    h = int(img.height * ratio)
    img = img.resize((w, h), Image.LANCZOS)
    cards.append(img)

# ---------- frame renderer ----------
def make_frame(t):
    frame = Image.fromarray(bg_dark).convert("RGBA")

    for i, (card, (cx, cy)) in enumerate(zip(cards, POSITIONS)):
        appear_t = i * APPEAR_INT
        if t < appear_t:
            continue

        alpha = min(1.0, (t - appear_t) / FADE_DUR)

        # shadow
        sh = 8
        shadow = Image.new("RGBA", (card.width + sh*2, card.height + sh*2), (0,0,0,0))
        shadow.paste(Image.new("RGBA", card.size, (0, 0, 0, int(200 * alpha))), (sh, sh))
        shadow = shadow.filter(ImageFilter.GaussianBlur(12))
        frame.alpha_composite(shadow, (cx - sh, cy - sh))

        # card with faded alpha
        r, g, b, a = card.split()
        a2 = a.point(lambda v: int(v * alpha))
        frame.alpha_composite(Image.merge("RGBA", (r, g, b, a2)), (cx, cy))

    return np.array(frame.convert("RGB"))

clip = VideoClip(make_frame, duration=DUR)
clip.write_videofile(OUT, fps=FPS, codec="libx264", audio=False, logger=None)
print(f"wrote {OUT}")
