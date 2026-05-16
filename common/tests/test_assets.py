from pathlib import Path

from PIL import Image

from devlog.assets import asset_report, collect_used_assets, format_asset_report
from devlog.types import Beat, Chunk, Design, Edit, Fonts, Palette, Scene


def _design():
    pal = Palette(bg=(0, 0, 0), gold=(1, 1, 1), gold_dim=(2, 2, 2), red=(3, 3, 3))
    fonts = Fonts(display="display.ttf", text="text.ttf")
    return Design(resolution=(1920, 1080), fps=30, palette=pal, fonts=fonts)


def _edit():
    return Edit(
        name="youtube",
        design=_design(),
        output="data/finalize/out.mp4",
        order=["a"],
        beats={
            "a": Beat(
                audio="data/finalize/a.wav",
                words="data/finalize/a.json",
                scene=Scene(kind="image", src="data/bg.png"),
                chunks=[Chunk(words=(0, 1), kind="image", src="data/card.png")],
            )
        },
    )


def test_collect_used_assets_includes_audio_words_and_images():
    used = collect_used_assets(_edit())
    assert "data/finalize/a.wav" in used
    assert "data/finalize/a.json" in used
    assert "data/bg.png" in used
    assert "data/card.png" in used


def test_asset_report_finds_missing_unused_and_low_res(tmp_path: Path):
    (tmp_path / "data/finalize").mkdir(parents=True)
    (tmp_path / "data/finalize/a.wav").write_bytes(b"fake")
    (tmp_path / "data/finalize/a.json").write_text("{}", encoding="utf-8")
    Image.new("RGB", (800, 400)).save(tmp_path / "data/bg.png")
    Image.new("RGB", (2000, 1000)).save(tmp_path / "data/unused.png")

    report = asset_report(_edit(), tmp_path, target_width=1920)
    assert "data/card.png" in report.missing
    assert "data/unused.png" in report.unused
    assert any("data/bg.png" in item for item in report.low_res)
    text = format_asset_report(report, show_unused=True)
    assert "missing:" in text
    assert "unused:" in text
