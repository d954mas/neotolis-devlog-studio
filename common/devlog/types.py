"""Core dataclasses shared between engine and project edits.

Design philosophy:
- Engine functions accept (spec, design). No module-level color/font constants.
- Chunks are one big dataclass with a `kind` discriminator. Unused fields stay None.
- A project defines: Palette + Fonts + Design + Beat dict + Edit list.
- An Edit is a single output (YT video, reel) — its own Design, its own beats list.
"""
from __future__ import annotations
from dataclasses import dataclass, field
from typing import Literal, Optional, Tuple


# ─── Brand tokens ─────────────────────────────────────────────────

@dataclass(frozen=True)
class Palette:
    """RGB triples for the brand. Used by all render functions via design.palette."""
    bg: Tuple[int, int, int]
    gold: Tuple[int, int, int]
    gold_dim: Tuple[int, int, int]
    red: Tuple[int, int, int]
    white: Tuple[int, int, int] = (255, 255, 255)
    fg_dim: Tuple[int, int, int] = (180, 170, 150)


@dataclass(frozen=True)
class Fonts:
    """Filesystem paths to TTF/OTF files. Engine selects per-language."""
    display: str           # Latin/numbers/display (e.g. bahnschrift)
    text: str              # Cyrillic-safe body (e.g. tahomabd — tight Й breve)
    mono: Optional[str] = None
    emoji: Optional[str] = None


@dataclass(frozen=True)
class Design:
    """Render target: resolution, fps, palette, font set, design tokens.

    Tokens are absolute pixel sizes for the 1920px-wide baseline.
    Engine scales them via `design.scale` when resolution differs.
    """
    resolution: Tuple[int, int]                  # (1920, 1080) | (1080, 1920) | (1080, 1080)
    fps: int
    palette: Palette
    fonts: Fonts

    # Design tokens — pixel values at 1920px-wide baseline
    underline_width: int = 480                   # red underline below plate headlines
    underline_thickness: int = 11
    crossfade_dur: float = 0.6                   # between scene segments
    plate_margin: int = 240                      # safe area for plate text
    overlay_band_pad_v: int = 80
    overlay_card_pad_x: int = 120
    label_pad_x: int = 30
    label_pad_y: int = 18

    @property
    def W(self) -> int:
        return self.resolution[0]

    @property
    def H(self) -> int:
        return self.resolution[1]

    @property
    def scale(self) -> float:
        """Scale relative to 1920px baseline. Use for any pixel-size design token."""
        return self.resolution[0] / 1920.0

    @property
    def aspect(self) -> float:
        return self.resolution[0] / self.resolution[1]

    def px(self, baseline_px: int) -> int:
        """Scale a baseline-px value to current resolution."""
        return int(round(baseline_px * self.scale))


# ─── Beat structure ───────────────────────────────────────────────

@dataclass
class Scene:
    """Background visual for a chunk or whole beat. Either video or image.

    For video: offset = seek position; loop = repeat if shorter than duration;
               otherwise the last frame freezes for the remainder.
    For image: fit = cover (fill+crop) | contain (letterbox); ken_burns = slow zoom.
    """
    kind: Literal["video", "image"]
    src: str
    offset: float = 0.0
    fit: Literal["cover", "contain"] = "cover"
    loop: bool = False
    ken_burns: bool = False
    kb_zoom: float = 0.10                        # Ken Burns end-scale delta (1.0 → 1.0+kb_zoom)


@dataclass
class Chunk:
    """One timed visual segment of a beat, bounded by Whisper word indices.

    `kind` dispatches the renderer. Most fields are kind-specific and default to None.
    """
    words: Tuple[int, int]                       # inclusive word indices into beat's words.json
    kind: Literal["plate", "overlay", "image", "video"]

    # ── Text content (plate, overlay) ──
    text: str = ""
    subtitle: Optional[str] = None

    # ── Plate styling ──
    color: Optional[Tuple[int, int, int]] = None       # None → design.palette.gold
    bg: Optional[Tuple[int, int, int]] = None          # None → design.palette.bg
    size: int = 120                                    # px at 1920-baseline; engine scales
    subtitle_color: Optional[Tuple[int, int, int]] = None
    sub_ratio: float = 0.25                            # subtitle size as fraction of main size
    line_gap_ratio: float = 0.18                       # multiline gap as fraction of size
    red_underline: bool = False
    red_accent: bool = False                           # accent bar under last text line
    accent_card: bool = False                          # render text on rounded card
    silver_badge: bool = False                         # decorative #2 badge above text
    trophy: bool = False                               # 🏆 emoji above text
    medal: bool = False                                # 🥈 emoji above text (deprecated — clashes with palette)
    bg_image: Optional[str] = None                     # blurred game screenshot behind plate
    bg_opacity: float = 0.28                           # blend strength for bg_image
    subtitle_spaced: bool = False                      # add spaces between subtitle chars

    # ── Overlay styling ──
    position: Literal["bottom", "top", "middle"] = "bottom"
    style: Literal["band", "card", "hero"] = "band"

    # ── Image / Video source ──
    src: Optional[str] = None
    fit: Literal["cover", "contain"] = "cover"
    framed_card: bool = False                          # inset card on brand bg
    label: Optional[str] = None                        # caption pill on B-roll image
    label_style: Literal["default", "branded"] = "default"
    ken_burns: bool = False                            # slow zoom for static image
    vignette_overlay: bool = False                     # add radial dark vignette
    offset: float = 0.0                                # video seek position for kind=video

    # ── Scene override (for kind=overlay backed by its own scene) ──
    scene: Optional[Scene] = None


@dataclass
class Beat:
    """One beat: audio + words.json + ordered chunks. Optional default scene
    used by chunks that don't carry their own.

    Production metadata (title, vo, stage, face) is consumed by recorder.html
    and preview.html — keep here so beats.py is single source of truth.
    """
    audio: str                                   # path to *_audio_final.wav
    words: str                                   # path to *_words.json
    chunks: list[Chunk]
    scene: Optional[Scene] = None                # default beat-wide background

    # ── Recorder / preview metadata ──
    title: str = ""
    vo: str = ""                                 # spoken text for teleprompter
    stage: str = ""                              # delivery notes for reader
    face: Literal["full", "pip", "none"] = "none"


@dataclass
class Edit:
    """A single video output: which beats, in what order, at what design.

    Each edit lives in its own folder: edits/<name>/{beats.py, design.py}.
    YT video, vertical reel, compilation — all are Edits with their own
    design + beats. They may share assets via paths into project's data/.
    """
    name: str
    design: Design
    beats: dict[str, Beat]                       # beat_id → Beat
    order: list[str]                             # beat_ids in concat order
    output: str                                  # output filename (e.g. "iter86.mp4")
