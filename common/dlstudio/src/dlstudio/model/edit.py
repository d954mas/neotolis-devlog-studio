"""Edit-level DSL: beats, audio mix graph, the Edit root.

Audio is first-class in v2: beats render as video + VO stem; `assemble`
lays MusicRegions ACROSS beat boundaries, applies sidechain ducking keyed
by the VO stems, places SFX at word anchors, and normalizes the final mix.
"""
from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from .content import Chunk, Scene, Transition
from .design import Design


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class SfxEvent(_Model):
    """One-shot sound effect anchored to a word index of the beat's VO."""

    src: str
    word: int
    gain_db: float = 0.0


class Beat(_Model):
    audio: str                       # processed VO wav
    words: str                       # Whisper words JSON (v1 schema)
    chunks: list[Chunk]
    scene: Scene | None = None       # beat-wide background (chunk scene overrides)
    face: Literal["full", "pip", "none"] = "none"
    vo: str | None = None            # script text (teleprompter/review)
    title: str | None = None
    stage: str | None = None         # stage direction for the voice actor
    sfx: list[SfxEvent] = Field(default_factory=list)
    transition_out: Transition | None = None   # into the NEXT beat (assemble)
    # Phrase-level subtitles auto-generated from the beat's words (reels):
    # compile groups words into phrases at pauses/length and render draws
    # them in the bottom safe zone, styled by Design.captions.
    subtitles: bool = False


class Duck(_Model):
    """Sidechain ducking of music under VO (ffmpeg sidechaincompress)."""

    amount_db: float = -12.0
    threshold_db: float = -30.0
    attack_ms: int = 120
    release_ms: int = 400


class MusicRegion(_Model):
    """Music bed spanning a contiguous run of beats. from_beat/to_beat are
    beat ids (inclusive); both None = the whole edit."""

    src: str
    from_beat: str | None = None
    to_beat: str | None = None
    gain_db: float = -18.0
    fade_in: float = 1.0
    fade_out: float = 1.5
    offset: float = 0.0              # seek into the music file
    duck: bool = True


class Mix(_Model):
    music: list[MusicRegion] = Field(default_factory=list)
    duck: Duck = Field(default_factory=Duck)
    target_lufs: float = -14.0       # YouTube spoken-word target (v1 parity)
    true_peak_db: float = -1.0


class Edit(_Model):
    name: str
    design: Design
    beats: dict[str, Beat]
    order: list[str]
    output: str
    mix: Mix = Field(default_factory=Mix)
