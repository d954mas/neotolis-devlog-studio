from pathlib import Path
import subprocess

from devlog.check import check_edit
from devlog.types import Beat, Chunk, Design, Edit, Fonts, Palette, Scene


def _design(tmp_path: Path):
    (tmp_path / "display.ttf").write_bytes(b"font")
    (tmp_path / "text.ttf").write_bytes(b"font")
    pal = Palette(bg=(0, 0, 0), gold=(1, 1, 1), gold_dim=(2, 2, 2), red=(3, 3, 3))
    fonts = Fonts(display=str(tmp_path / "display.ttf"), text=str(tmp_path / "text.ttf"))
    return Design(resolution=(1920, 1080), fps=30, palette=pal, fonts=fonts)


def test_check_passes_minimal_valid_edit(tmp_path: Path):
    (tmp_path / "data/finalize").mkdir(parents=True)
    (tmp_path / "data/finalize/intro_audio_final.wav").write_bytes(b"fake")
    (tmp_path / "data/finalize/intro_words.json").write_text(
        '{"words":[{"word":"one","start":0,"end":0.5},{"word":"two","start":0.5,"end":1.0}]}',
        encoding="utf-8",
    )
    edit = Edit(
        name="youtube",
        design=_design(tmp_path),
        output="data/finalize/out.mp4",
        order=["intro"],
        beats={
            "intro": Beat(
                audio="data/finalize/intro_audio_final.wav",
                words="data/finalize/intro_words.json",
                chunks=[Chunk(words=(0, 1), kind="plate", text="INTRO")],
            )
        },
    )
    assert check_edit(edit, tmp_path) == []


def test_check_reports_missing_assets_and_bad_word_ranges(tmp_path: Path):
    (tmp_path / "data/finalize").mkdir(parents=True)
    (tmp_path / "data/finalize/intro_words.json").write_text(
        '{"words":[{"word":"one","start":0,"end":0.5}]}',
        encoding="utf-8",
    )
    edit = Edit(
        name="youtube",
        design=_design(tmp_path),
        output="data/finalize/out.mp4",
        order=["intro"],
        beats={
            "intro": Beat(
                audio="data/finalize/missing.wav",
                words="data/finalize/intro_words.json",
                scene=Scene(kind="image", src="data/missing_bg.png"),
                chunks=[Chunk(words=(0, 2), kind="image", src="data/missing.png")],
            )
        },
    )
    issues = check_edit(edit, tmp_path)
    codes = {i.code for i in issues}
    assert "missing-asset" in codes
    assert "word-range-out-of-bounds" in codes


def test_deep_check_reports_video_offset_past_eof(tmp_path: Path, monkeypatch):
    (tmp_path / "data/finalize").mkdir(parents=True)
    (tmp_path / "data/finalize/intro_audio_final.wav").write_bytes(b"fake")
    (tmp_path / "data/finalize/intro_words.json").write_text(
        '{"words":[{"word":"one","start":0,"end":0.5}]}',
        encoding="utf-8",
    )
    (tmp_path / "data/bg.mp4").parent.mkdir(parents=True, exist_ok=True)
    (tmp_path / "data/bg.mp4").write_bytes(b"fake")

    def fake_run(*args, **kwargs):
        return subprocess.CompletedProcess(args[0], 0, stdout="2.000\n", stderr="")

    monkeypatch.setattr("devlog.check.subprocess.run", fake_run)
    edit = Edit(
        name="youtube",
        design=_design(tmp_path),
        output="data/finalize/out.mp4",
        order=["intro"],
        beats={
            "intro": Beat(
                audio="data/finalize/intro_audio_final.wav",
                words="data/finalize/intro_words.json",
                scene=Scene(kind="video", src="data/bg.mp4", offset=3.0),
                chunks=[Chunk(words=(0, 0), kind="overlay", text="INTRO")],
            )
        },
    )
    issues = check_edit(edit, tmp_path, deep=True)
    assert "video-offset-past-eof" in {i.code for i in issues}
