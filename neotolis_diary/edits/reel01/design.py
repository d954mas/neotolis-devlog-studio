"""Vertical design for reel01."""
from devlog.types import Design
from neotolis_diary.shared.palette import NEOTOLIS_DIARY_FONTS, NEOTOLIS_DIARY_PALETTE


DESIGN = Design(
    resolution=(1080, 1920),
    fps=30,
    palette=NEOTOLIS_DIARY_PALETTE,
    fonts=NEOTOLIS_DIARY_FONTS,
    underline_width=280,
    overlay_band_pad_v=92,
)
