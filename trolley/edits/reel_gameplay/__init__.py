"""Vertical reel — gameplay/features showcase."""
from devlog.types import Edit
from .design import DESIGN
from .beats import BEATS, CONCAT_ORDER, OUTPUT


EDIT = Edit(
    name="reel_gameplay",
    design=DESIGN,
    beats=BEATS,
    order=CONCAT_ORDER,
    output=OUTPUT,
)
