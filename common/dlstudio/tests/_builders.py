"""Shared test builders. Imported by test_compile*/test_check* modules.

pytest inserts the tests dir onto sys.path (no __init__.py here), so
`from _builders import ...` resolves.
"""
from __future__ import annotations

from pathlib import Path

from dlstudio.ir import AssetProbe, WordSpan
from dlstudio.model import (
    Beat,
    Chunk,
    Design,
    Edit,
    Fonts,
    Mix,
    MusicRegion,
    Palette,
    Scene,
    SfxEvent,
)
from dlstudio.model.content import (
    Anim,
    ImageShot,
    Overlay,
    Plate,
    Transition,
    VideoShot,
)

FIXTURES = Path(__file__).parent / "fixtures"
WORDS_BASIC = FIXTURES / "words_basic.json"


def mk_design(resolution=(1080, 1920), *, crossfade=0.3, fps=30) -> Design:
    return Design(
        resolution=resolution,
        fps=fps,
        palette=Palette(tokens={"bg": "#101010", "text": "#ffffff", "accent": "#ff3355"}),
        fonts=Fonts(main="/fonts/main.ttf", bold="/fonts/bold.ttf"),
        crossfade_dur=crossfade,
    )


def probe(
    path: str,
    kind: str = "audio",
    *,
    exists: bool = True,
    duration=None,
    width=None,
    height=None,
    has_audio=None,
) -> AssetProbe:
    return AssetProbe(
        path=path, kind=kind, exists=exists, duration=duration,
        width=width, height=height, has_audio=has_audio,
    )


def words(*triples) -> list[WordSpan]:
    """words((0.0, 0.4, "hi"), (0.5, 0.9, "there"), ...) -> [WordSpan]."""
    return [WordSpan(t0=a, t1=b, text=t) for (a, b, t) in triples]


def plate_chunk(wi, wj, *, scene=None, anims=None, transition=None,
                pad_before=0.0, pad_after=0.0, text="X") -> Chunk:
    return Chunk(
        words=(wi, wj), content=Plate(text=text), scene=scene,
        anims=anims or [], transition=transition,
        pad_before=pad_before, pad_after=pad_after,
    )


def default_probes(**overrides) -> dict[str, AssetProbe]:
    """A permissive registry: everything exists, sane media facts. Override or
    extend per test."""
    base = {
        "/fonts/main.ttf": probe("/fonts/main.ttf", "font"),
        "/fonts/bold.ttf": probe("/fonts/bold.ttf", "font"),
    }
    base.update(overrides)
    return base
