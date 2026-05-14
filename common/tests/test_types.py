"""Smoke tests for the dataclass surface.

Run from C:\\projects\\devlogs\\ with:
    PYTHONPATH=common pytest common/tests/
"""
from devlog.types import Palette, Fonts, Design, Scene, Chunk, Beat, Edit


def test_palette_immutable():
    p = Palette(bg=(0,0,0), gold=(1,1,1), gold_dim=(2,2,2), red=(3,3,3))
    try:
        p.bg = (9, 9, 9)
        assert False, "Palette should be frozen"
    except Exception:
        pass


def test_design_scaling():
    pal = Palette(bg=(0,0,0), gold=(1,1,1), gold_dim=(2,2,2), red=(3,3,3))
    fonts = Fonts(display="a.ttf", text="b.ttf")

    d1080 = Design(resolution=(1920, 1080), fps=30, palette=pal, fonts=fonts)
    assert d1080.scale == 1.0
    assert d1080.px(280) == 280
    assert d1080.aspect > 1.7

    d540 = Design(resolution=(960, 540), fps=30, palette=pal, fonts=fonts)
    assert abs(d540.scale - 0.5) < 1e-6
    assert d540.px(280) == 140

    d4k = Design(resolution=(3840, 2160), fps=30, palette=pal, fonts=fonts)
    assert d4k.scale == 2.0
    assert d4k.px(280) == 560

    d_reel = Design(resolution=(1080, 1920), fps=30, palette=pal, fonts=fonts)
    assert d_reel.aspect < 1.0


def test_chunk_defaults():
    c = Chunk(words=(0, 5), kind="overlay", text="hello")
    assert c.position == "bottom"
    assert c.style == "band"
    assert c.color is None
    assert c.red_underline is False
    assert c.scene is None


def test_beat_with_chunks():
    b = Beat(
        audio="a.wav",
        words="a.json",
        chunks=[
            Chunk(words=(0, 5), kind="overlay", text="hi"),
            Chunk(words=(6, 10), kind="plate", text="bye", size=200, red_underline=True),
        ],
        title="t",
        vo="vo text",
        face="full",
    )
    assert len(b.chunks) == 2
    assert b.chunks[1].red_underline is True
    assert b.face == "full"


def test_edit_assembly():
    pal = Palette(bg=(0,0,0), gold=(1,1,1), gold_dim=(2,2,2), red=(3,3,3))
    fonts = Fonts(display="a.ttf", text="b.ttf")
    design = Design(resolution=(1920, 1080), fps=30, palette=pal, fonts=fonts)
    beats = {
        "x": Beat(audio="x.wav", words="x.json",
                  chunks=[Chunk(words=(0,1), kind="overlay", text="x")]),
    }
    e = Edit(name="test", design=design, beats=beats, order=["x"], output="out.mp4")
    assert e.name == "test"
    assert "x" in e.beats
