"""Design configuration for the YouTube edit of the trolley devlog.

1920x1080 @ 30fps. Uses the shared trolley palette and fonts.
All design tokens stay at the 1920-baseline default values.
"""
from devlog.types import Design
from trolley.shared.palette import TROLLEY_PALETTE, TROLLEY_FONTS

DESIGN = Design(
    resolution=(1920, 1080),
    fps=30,
    palette=TROLLEY_PALETTE,
    fonts=TROLLEY_FONTS,
    # Tokens use baseline defaults — see devlog.types.Design
)
