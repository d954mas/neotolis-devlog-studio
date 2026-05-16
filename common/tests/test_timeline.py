import subprocess
from pathlib import Path

from devlog.timeline import format_summaries, summarize_edit
from devlog.types import Beat, Chunk, Design, Edit, Fonts, Palette


def _design(tmp_path: Path):
    pal = Palette(bg=(0, 0, 0), gold=(1, 1, 1), gold_dim=(2, 2, 2), red=(3, 3, 3))
    fonts = Fonts(display=str(tmp_path / "display.ttf"), text=str(tmp_path / "text.ttf"))
    return Design(resolution=(1920, 1080), fps=30, palette=pal, fonts=fonts)


def test_summarize_edit_uses_words_duration_and_render_status(tmp_path: Path, monkeypatch):
    (tmp_path / "data/finalize").mkdir(parents=True)
    (tmp_path / "data/finalize/a_words.json").write_text(
        '{"words":[{"word":"one","start":0,"end":0.5},{"word":"two","start":0.5,"end":2.0}]}',
        encoding="utf-8",
    )
    (tmp_path / "data/finalize/a_video_1080p.mp4").write_bytes(b"fake")

    def fake_run(cmd, capture_output, text):
        return subprocess.CompletedProcess(cmd, 1, stdout="", stderr="missing audio")

    monkeypatch.setattr("devlog.timeline.subprocess.run", fake_run)
    edit = Edit(
        name="youtube",
        design=_design(tmp_path),
        output="data/finalize/out.mp4",
        order=["a"],
        beats={
            "a": Beat(
                title="A beat",
                audio="data/finalize/a_audio_final.wav",
                words="data/finalize/a_words.json",
                chunks=[Chunk(words=(0, 1), kind="plate", text="A")],
            )
        },
    )
    summaries = summarize_edit(edit, tmp_path)
    assert summaries[0].duration == 2.0
    assert summaries[0].words == 2
    assert summaries[0].rendered is True
    rendered = format_summaries(summaries)
    assert "a" in rendered
    assert "0:02" in rendered
    assert "yes" in rendered
