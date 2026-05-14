"""YouTube edit: full 1920x1080 devlog video (4-minute Russian VO)."""
from devlog.types import Edit
from .design import DESIGN
from .beats import BEATS, CONCAT_ORDER, OUTPUT

EDIT = Edit(
    name="youtube",
    design=DESIGN,
    beats=BEATS,
    order=CONCAT_ORDER,
    output=OUTPUT,
)

