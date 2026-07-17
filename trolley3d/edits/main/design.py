"""design.py — vertical reel для Not a Trolley Problem (3D, свой движок).

Палитра — под «Playable Doodle» игры: бумажный фон, чернильный текст,
красный акцент трамвая.
"""
from __future__ import annotations

from dlstudio.model import CaptionStyle, Design, Fonts, Palette, TextStyle

RESOLUTION = (1080, 1920)
DESIGN = Design(
    resolution=RESOLUTION,
    fps=30,
    palette=Palette(tokens={
        "bg": "#efece3",        # бумага
        "text": "#1c1b18",      # чернила
        "accent": "#c0392b",    # красный трамвай
    }),
    fonts=Fonts(main="data/fonts/main.ttf"),
    styles={
        "plate.default": TextStyle(size=200),
        "plate.climax": TextStyle(size=230, color="accent", caps=True),
        "plate.title": TextStyle(size=180, color="text", caps=True),
        "overlay.default": TextStyle(size=110),
        "overlay.title": TextStyle(size=150),
    },
    captions=CaptionStyle(size=96, color="text", y_ratio=0.80, bg_opacity=0.6),
)
