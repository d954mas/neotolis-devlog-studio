from pathlib import Path

from devlog.types import Beat, Chunk, Design, Edit, Fonts, Palette
from devlog.web.serve import _status_to_dict


def test_status_to_dict_reports_errors_and_beats(tmp_path: Path):
    pal = Palette(bg=(0, 0, 0), gold=(1, 1, 1), gold_dim=(2, 2, 2), red=(3, 3, 3))
    fonts = Fonts(display=str(tmp_path / "display.ttf"), text=str(tmp_path / "text.ttf"))
    (tmp_path / "display.ttf").write_bytes(b"font")
    (tmp_path / "text.ttf").write_bytes(b"font")
    design = Design(resolution=(1920, 1080), fps=30, palette=pal, fonts=fonts)
    edit = Edit(
        name="youtube",
        design=design,
        output="data/finalize/out.mp4",
        order=["a"],
        beats={
            "a": Beat(
                title="A",
                audio="data/finalize/missing.wav",
                words="data/finalize/missing.json",
                chunks=[Chunk(words=(0, 1), kind="plate", text="A")],
            )
        },
    )
    status = _status_to_dict(edit, tmp_path)
    assert status["errors"] >= 1
    assert status["beats"][0]["beat_id"] == "a"
