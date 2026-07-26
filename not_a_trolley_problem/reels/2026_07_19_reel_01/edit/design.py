"""Visual tokens for the vertical silent-first temporal demo."""
from __future__ import annotations

from dlstudio.model import Design, Fonts, Palette, TextStyle


RESOLUTION = (1080, 1920)
DESIGN = Design(
    resolution=RESOLUTION,
    fps=30,
    palette=Palette(tokens={
        "bg": "#0d0e0e",
        "paper": "#f0ece2",
        "text": "#f0ece2",
        "ink": "#17191a",
        "accent": "#e23e34",
        "muted": "#aaa49a",
    }),
    fonts=Fonts(main="data/fonts/main.ttf", bold="data/fonts/main.ttf"),
    styles={
        "plate.default": TextStyle(size=190, color="text", font="bold"),
        "overlay.default": TextStyle(size=112, color="text", font="bold"),
    },
)
