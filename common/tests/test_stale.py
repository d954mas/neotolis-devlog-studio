import os
import time
from pathlib import Path

from devlog.cache import beat_hash, cache_path
from devlog.stale import format_stale, stale_beats
from devlog.types import Beat, Chunk, Design, Edit, Fonts, Palette


def _edit() -> Edit:
    pal = Palette(bg=(0, 0, 0), gold=(1, 1, 1), gold_dim=(2, 2, 2), red=(3, 3, 3))
    fonts = Fonts(display="display.ttf", text="text.ttf")
    design = Design(resolution=(1920, 1080), fps=30, palette=pal, fonts=fonts)
    return Edit(
        name="youtube",
        design=design,
        output="data/finalize/out.mp4",
        order=["a"],
        beats={
            "a": Beat(
                audio="data/finalize/a.wav",
                words="data/finalize/a.json",
                chunks=[Chunk(words=(0, 1), kind="plate", text="A")],
            )
        },
    )


def test_stale_beats_reports_missing_render(tmp_path: Path):
    stale = stale_beats(_edit(), tmp_path)

    assert stale[0].beat_id == "a"
    assert stale[0].reason == "missing render"


def test_stale_beats_reports_newer_source(tmp_path: Path):
    (tmp_path / "data/finalize").mkdir(parents=True)
    audio = tmp_path / "data/finalize/a.wav"
    words = tmp_path / "data/finalize/a.json"
    output = tmp_path / "data/finalize/a_video_1080p.mp4"
    source = tmp_path / "beats.py"
    audio.write_bytes(b"audio")
    words.write_text("{}", encoding="utf-8")
    output.write_bytes(b"video")
    source.write_text("newer", encoding="utf-8")
    old = time.time() - 10
    os.utime(output, (old, old))

    stale = stale_beats(_edit(), tmp_path, source_paths=[source])

    assert stale[0].reason == "source newer: beats.py"
    assert "source newer" in format_stale(stale)


def test_stale_beats_trusts_current_content_cache(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    edit = _edit()
    (tmp_path / "data/finalize").mkdir(parents=True)
    (tmp_path / "data/finalize/a.wav").write_bytes(b"audio")
    (tmp_path / "data/finalize/a.json").write_text("{}", encoding="utf-8")
    output = tmp_path / "data/finalize/a_video_1080p.mp4"
    source = tmp_path / "beats.py"
    output.write_bytes(b"video")
    source.write_text("newer", encoding="utf-8")
    old = time.time() - 10
    os.utime(output, (old, old))
    key = beat_hash(edit.beats["a"], edit.design)
    current_cache = tmp_path / cache_path(key)
    current_cache.parent.mkdir(parents=True)
    current_cache.write_bytes(b"cached")

    stale = stale_beats(edit, tmp_path, source_paths=[source])

    assert stale == []
