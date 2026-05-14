"""Trolley devlog brand palette and font set.

Both YouTube edit and vertical reels import from here, so the visual language
stays consistent across formats. Override individual values in a specific edit's
design.py if you need to deviate (e.g. brighter accent for reels).
"""
from devlog.types import Palette, Fonts

# ─── Colors (locked since iter_40) ────────────────────────────────
TROLLEY_PALETTE = Palette(
    bg=(26, 22, 18),           # #1a1612 — warm dark
    gold=(232, 182, 71),       # #e8b647 — primary accent
    gold_dim=(224, 174, 69),   # 96% gold — subtitles, notes (readable on phone)
    red=(192, 57, 43),         # #c0392b — punchline accent, underlines
    fg_dim=(180, 170, 150),    # secondary text
)

# ─── Fonts (Windows paths) ─────────────────────────────────────────
# bahnschrift: geometric display, clean numbers
# tahomabd:    bold Cyrillic with tight Й breve (better than arialbd)
# consolab:    monospace for code snippets
# seguiemj:    emoji color font (🏆 🥈) — optional
TROLLEY_FONTS = Fonts(
    display="C:/Windows/Fonts/bahnschrift.ttf",
    text="C:/Windows/Fonts/tahomabd.ttf",
    mono="C:/Windows/Fonts/consolab.ttf",
    emoji="C:/Windows/Fonts/seguiemj.ttf",
)
