"""Design: resolution, palette, fonts, and the project style registry.

The engine knows primitives; the PROJECT names looks. "plate.climax" maps to
a TextStyle the project defines once (sizes per HIT_VIDEO_PRACTICES visual
hierarchy). Engine/raster code resolves style names through Design.styles
and must not contain brand constants.
"""
from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Palette(_Model):
    """Named color tokens ("bg", "text", "accent", ...) -> #rrggbb."""

    tokens: dict[str, str]

    def color(self, ref: str) -> str:
        """Resolve a token name; passes through literal #rrggbb values."""
        if ref.startswith("#"):
            return ref
        try:
            return self.tokens[ref]
        except KeyError:
            raise KeyError(f"palette token {ref!r} not defined; tokens: {sorted(self.tokens)}")


class Fonts(_Model):
    """Paths to TTF/OTF files. `main` is required; others fall back to it."""

    main: str
    bold: str | None = None
    accent: str | None = None


class TextStyle(_Model):
    """A named typographic look, referenced from content via style name."""

    size: int
    color: str = "text"                      # palette token
    font: str = "bold"                       # "main" | "bold" | "accent"
    line_gap_ratio: float = 0.02
    caps: bool = False


class CaptionStyle(_Model):
    """The ONE subtitle look (`beat.subtitles=True`, PLAN_STUDIO_V2 1.6):
    a centered, wrapped text line over a soft backdrop pill in the bottom
    safe zone. One primitive, one position, one style — projects tune the
    knobs, they don't get a general titling system."""

    size: int = 96                  # authored for 1920-wide; scaled via Design.px
    color: str = "text"             # palette token (or literal #rrggbb)
    font: str = "main"              # "main" | "bold" | "accent"
    y_ratio: float = 0.78           # text-block center as a fraction of height
    max_width_ratio: float = 0.86   # wrap width as a fraction of frame width
    bg_opacity: float = 0.55        # backdrop pill opacity; 0 disables the pill


class Design(_Model):
    resolution: tuple[int, int]
    fps: int = 30
    palette: Palette
    fonts: Fonts
    styles: dict[str, TextStyle] = Field(default_factory=dict)
    captions: CaptionStyle = Field(default_factory=CaptionStyle)
    crossfade_dur: float = 0.3
    safe_margin_ratio: float = 0.05

    # Baseline for resolution-independent sizing: style sizes are authored
    # for a 1920-WIDE frame; px() scales by WIDTH, matching legacy
    # devlog.types.Design.px. Width-based scaling is the production-proven
    # behavior for vertical reels: at 1080x1920 px(480) == 270 (the value
    # v1 designs were tuned around), where height-based scaling would give
    # a 3.2x larger 853.
    def px(self, v: float, base: float = 1920.0) -> int:
        return round(v * self.resolution[0] / base)

    @property
    def scale(self) -> float:
        return self.resolution[0] / 1920.0

    def style(self, name: str) -> TextStyle:
        """Resolve a style name with sensible fallback chain:
        exact -> "<kind>.default" -> hard default."""
        if name in self.styles:
            return self.styles[name]
        kind = name.split(".", 1)[0]
        fallback = f"{kind}.default"
        if fallback in self.styles:
            return self.styles[fallback]
        return TextStyle(size=220)
