"""Phase-1 acceptance: the full pipeline end-to-end with real ffmpeg.

Edit (DSL) -> build_timeline (real ffprobe) -> run_checks -> raster ->
render_beat (real ffmpeg) -> verify_output postcondition -> assemble.

This is the integration seam test: every module below was implemented by a
different agent; this file proves they compose.
"""
from __future__ import annotations

import json
import shutil
import subprocess
from pathlib import Path

import pytest
from PIL import Image

from dlstudio.check import run_checks, verify_output
from dlstudio.compile import build_timeline
from dlstudio.model import (
    Beat,
    Chunk,
    Design,
    Edit,
    Fonts,
    Overlay,
    Palette,
    Plate,
    Scene,
    TextStyle,
    Underline,
)
from dlstudio.render import RenderOpts, assemble, render_beat
from dlstudio.render import beat as render_beat_mod

pytestmark = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


def _font_path() -> str:
    """A real font when available (Windows arial), else a placeholder file —
    raster falls back to PIL's default font on load failure, but VQ-ASSET
    requires the referenced path to exist."""
    arial = Path("C:/Windows/Fonts/arial.ttf")
    if arial.exists():
        return str(arial)
    Path("data/font.ttf").write_bytes(b"placeholder")
    return "data/font.ttf"


@pytest.fixture()
def project(tmp_path, monkeypatch):
    """A minimal real project: 3.4s sine VO, words JSON, gradient scene."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "data").mkdir()

    subprocess.run(
        ["ffmpeg", "-v", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3.4",
         "-ar", "48000", "-ac", "1", "data/vo.wav"],
        check=True, capture_output=True,
    )

    words = {
        "text": "hello brave new world again now",
        "words": [
            {"word": "hello", "start": 0.0, "end": 0.4},
            {"word": "brave", "start": 0.5, "end": 0.9},
            {"word": "new", "start": 1.0, "end": 1.3},
            {"word": "world", "start": 2.0, "end": 2.4},
            {"word": "again", "start": 2.5, "end": 2.9},
            {"word": "now", "start": 3.0, "end": 3.4},
        ],
    }
    Path("data/words.json").write_text(json.dumps(words), encoding="utf-8")

    img = Image.new("RGB", (640, 360))
    for x in range(640):
        for band in range(0, 360, 8):
            img.paste((x * 255 // 640, 80, 160), (x, band, x + 1, band + 8))
    img.save("data/scene.png")

    design = Design(
        resolution=(320, 180),
        fps=30,
        palette=Palette(tokens={"bg": "#101018", "text": "#ffffff", "accent": "#ff2b4e"}),
        fonts=Fonts(main=_font_path()),
        styles={"plate.default": TextStyle(size=220), "overlay.default": TextStyle(size=120)},
    )
    edit = Edit(
        name="e2e",
        design=design,
        beats={
            "b01": Beat(
                audio="data/vo.wav",
                words="data/words.json",
                scene=Scene(kind="image", src="data/scene.png", ken_burns=False),
                chunks=[
                    Chunk(words=(0, 2), content=Plate(text="HELLO"),
                          decorations=[Underline()]),
                    Chunk(words=(3, 5), content=Overlay(text="WORLD", subtitle="again now")),
                ],
            ),
        },
        order=["b01"],
        output="data/e2e_final.mp4",
    )
    return edit


def test_full_pipeline(project):
    edit = project

    timeline = build_timeline(edit)
    assert timeline.beats[0].duration == pytest.approx(3.4, abs=0.1)
    assert len(timeline.beats[0].overlays) == 2

    report = run_checks(timeline)
    assert report.ok, [i.model_dump() for i in report.errors]

    render_beat_mod.set_chunk_resolver(lambda bid, ci: edit.beats[bid].chunks[ci])
    try:
        opts = RenderOpts(quality="draft", workdir=Path("data"))
        beat_mp4 = render_beat(timeline.beats[0], timeline.design, timeline, opts)
        assert beat_mp4.exists()
        verify_output(str(beat_mp4), timeline.beats[0].duration, tolerance=0.5)

        vo_stem = beat_mp4.with_name(f"{timeline.beats[0].id}_vo_stem.wav")
        assert vo_stem.exists(), "render_beat must write the VO stem for Phase-2 mix"

        final = assemble(timeline, {"b01": beat_mp4}, opts)
        assert final.exists()
        verify_output(str(final), timeline.duration, tolerance=0.5)
    finally:
        render_beat_mod.set_chunk_resolver(None)


def test_check_catches_missing_asset(project):
    edit = project
    edit.beats["b01"].chunks[0].content.bg_image = "data/nope.png"
    timeline = build_timeline(edit)
    report = run_checks(timeline)
    assert not report.ok
    assert any(i.code == "VQ-ASSET" for i in report.errors)
