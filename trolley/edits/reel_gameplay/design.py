"""Vertical reel design for gameplay/features."""
from devlog.types import Design
from trolley.shared.palette import TROLLEY_PALETTE, TROLLEY_FONTS


DESIGN = Design(
    resolution=(1080, 1920),
    fps=30,
    palette=TROLLEY_PALETTE,
    fonts=TROLLEY_FONTS,
    underline_width=280,
    overlay_band_pad_v=92,
    plate_margin=120,
)
