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
    (tmp_path / "data/finalize/old_render.mp4").write_bytes(b"generated")
    Image.new("RGB", (800, 400)).save(tmp_path / "data/bg.png")
    Image.new("RGB", (2000, 1000)).save(tmp_path / "data/unused.png")

    report = asset_report(_edit(), tmp_path, target_width=1920)
    assert "data/card.png" in report.missing
    assert "data/unused.png" in report.unused
    assert "data/finalize/old_render.mp4" not in report.unused
    assert any(item.startswith("high: data/bg.png") for item in report.low_res)
    text = format_asset_report(report, show_unused=True)
    assert "missing:" in text
    assert "unused:" in text
    assert "2.70x upscale" in text


def test_asset_report_does_not_warn_for_contained_vertical_image(tmp_path: Path):
    (tmp_path / "data/finalize").mkdir(parents=True)
    (tmp_path / "data/finalize/a.wav").write_bytes(b"fake")
    (tmp_path / "data/finalize/a.json").write_text("{}", encoding="utf-8")
    Image.new("RGB", (1080, 1920)).save(tmp_path / "data/vertical.png")
    edit = Edit(
        name="youtube",
        design=_design(),
        output="data/finalize/out.mp4",
        order=["a"],
        beats={
            "a": Beat(
                audio="data/finalize/a.wav",
                words="data/finalize/a.json",
                scene=Scene(kind="image", src="data/vertical.png", fit="contain"),
                chunks=[],
            )
        },
    )

    report = asset_report(edit, tmp_path, target_width=1920)

    assert report.low_res == []


def test_asset_report_sorts_low_res_by_severity(tmp_path: Path):
    (tmp_path / "data/finalize").mkdir(parents=True)
    (tmp_path / "data/finalize/a.wav").write_bytes(b"fake")
    (tmp_path / "data/finalize/a.json").write_text("{}", encoding="utf-8")
    Image.new("RGB", (640, 360)).save(tmp_path / "data/tiny.png")
    Image.new("RGB", (1600, 900)).save(tmp_path / "data/okish.png")
    edit = Edit(
        name="youtube",
        design=_design(),
        output="data/finalize/out.mp4",
        order=["a"],
        beats={
            "a": Beat(
                audio="data/finalize/a.wav",
                words="data/finalize/a.json",
                chunks=[
                    Chunk(words=(0, 1), kind="image", src="data/okish.png"),
                    Chunk(words=(2, 3), kind="image", src="data/tiny.png"),
                ],
            )
        },
    )

    report = asset_report(edit, tmp_path, target_width=1920)

    assert report.low_res[0].startswith("high: data/tiny.png")
    assert report.low_res[1].startswith("low: data/okish.png")
