"""Vertical reel design: 1080x1920 @ 30fps.

Same palette and fonts as YouTube edit — they share trolley/shared/palette.
Token overrides reduce scale-dependent sizes for the narrower aspect.
"""
from devlog.types import Design
from trolley.shared.palette import TROLLEY_PALETTE, TROLLEY_FONTS

DESIGN = Design(
    resolution=(1080, 1920),
    fps=30,
    palette=TROLLEY_PALETTE,
    fonts=TROLLEY_FONTS,

    # Vertical-specific tokens (1080 wide → scale = 0.5625 of 1920 baseline,
    # so engine auto-shrinks these; values below are explicit overrides
    # where the auto-scale doesn't feel right for tall format).
    underline_width=270,             # 56% of 480 baseline — proportional to width
    overlay_band_pad_v=64,           # tighter band in vertical
    plate_margin=120,                # less side margin in vertical
)
