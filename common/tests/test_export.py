from devlog.export import script_markdown, shotlist_markdown
from devlog.types import Beat, Chunk, Design, Edit, Fonts, Palette, Scene


def _edit():
    pal = Palette(bg=(0, 0, 0), gold=(1, 1, 1), gold_dim=(2, 2, 2), red=(3, 3, 3))
    fonts = Fonts(display="display.ttf", text="text.ttf")
    design = Design(resolution=(1920, 1080), fps=30, palette=pal, fonts=fonts)
    return Edit(
        name="youtube",
        design=design,
        output="out.mp4",
        order=["a"],
        beats={
            "a": Beat(
                title="Intro",
                vo="Hello world.",
                stage="Read clearly.",
                audio="a.wav",
                words="a.json",
                scene=Scene(kind="image", src="bg.png"),
                chunks=[Chunk(words=(0, 1), kind="overlay", text="HELLO")],
            )
        },
    )


def test_script_markdown_exports_vo_and_stage():
    text = script_markdown(_edit())
    assert "# Script: youtube" in text
    assert "Hello world." in text
    assert "> Read clearly." in text


def test_shotlist_markdown_exports_chunks_and_scene():
    text = shotlist_markdown(_edit())
    assert "# Shotlist: youtube" in text
    assert "c0 words 0-1" in text
    assert "image:bg.png" in text
