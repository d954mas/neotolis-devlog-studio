"""Subtitle primitive (`beat.subtitles`, PLAN_STUDIO_V2 1.6): compile-level
phrase grouping, the caption rasterizer, and a real-ffmpeg render proving the
caption actually appears in the bottom of the frame during its window.
"""
from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from dlstudio.compile import _build_captions, build_timeline
from dlstudio.ir import AssetProbe, WordSpan
from dlstudio.model import Beat, Chunk, Design, Edit, Fonts, Palette, Plate
from dlstudio.render.raster import render_caption_image

from _builders import words


def _design(resolution=(1080, 1920)) -> Design:
    return Design(
        resolution=resolution,
        fps=24,
        palette=Palette(tokens={"bg": "#101418", "text": "#ffffff", "accent": "#ff3355"}),
        fonts=Fonts(main="missing.ttf"),   # PIL default fallback keeps tests hermetic
    )


# ─── compile: phrase grouping ───────────────────────────────────────────────

def test_build_captions_splits_on_pause():
    ws = words((0.0, 0.4, "раз"), (0.5, 0.9, "два"),
               (1.8, 2.2, "три"), (2.3, 2.7, "четыре"))   # 0.9 -> 1.8 = 0.9s gap
    caps = _build_captions(ws, 3.0)
    assert [c.text for c in caps] == ["раз два", "три четыре"]
    # first caption holds until the next phrase starts (no flicker)
    assert caps[0].t0 == 0.0 and caps[0].t1 == 1.8
    assert caps[1].t0 == 1.8


def test_build_captions_splits_on_max_chars():
    ws = words(*[(i * 0.3, i * 0.3 + 0.25, "слово") for i in range(12)])
    caps = _build_captions(ws, 5.0)
    assert len(caps) > 1
    for c in caps:
        assert len(c.text) <= 34


def test_build_captions_last_tail_clamped_to_duration():
    ws = words((0.0, 0.4, "конец"))
    caps = _build_captions(ws, 0.5)
    assert caps[-1].t1 == 0.5          # 0.4 + 0.3 tail clamped to duration


def test_build_captions_empty_words():
    assert _build_captions([], 3.0) == []


def test_compile_beat_flag_gates_captions(tmp_path):
    wp = tmp_path / "w.json"
    wp.write_text(json.dumps({"words": [
        {"word": "привет", "start": 0.0, "end": 0.4},
        {"word": "мир", "start": 0.5, "end": 0.9},
    ]}), encoding="utf-8")
    probes = {
        "vo.wav": AssetProbe(path="vo.wav", kind="audio", exists=True, duration=2.0),
        "missing.ttf": AssetProbe(path="missing.ttf", kind="font", exists=True),
    }

    def compile_with(subtitles: bool):
        beat = Beat(audio="vo.wav", words=str(wp), subtitles=subtitles,
                    chunks=[Chunk(words=(0, 1), content=Plate(text="X"))])
        edit = Edit(name="e", design=_design(), beats={"b1": beat},
                    order=["b1"], output="o.mp4")
        return build_timeline(edit, probe=False, probes=probes).beats[0]

    assert compile_with(False).captions == []
    caps = compile_with(True).captions
    assert caps and caps[0].text == "привет мир"


def test_captions_change_beat_cache_key(tmp_path):
    """Captions ride inside the IRBeat, so toggling subtitles must change the
    beat cache key (a cached no-subtitles render is not a subtitled one)."""
    from dlstudio import cache as dl_cache

    wp = tmp_path / "w.json"
    wp.write_text(json.dumps({"words": [
        {"word": "a", "start": 0.0, "end": 0.4},
    ]}), encoding="utf-8")
    probes = {
        "vo.wav": AssetProbe(path="vo.wav", kind="audio", exists=True, duration=2.0),
        "missing.ttf": AssetProbe(path="missing.ttf", kind="font", exists=True),
    }

    def key(subtitles: bool) -> str:
        beat = Beat(audio="vo.wav", words=str(wp), subtitles=subtitles,
                    chunks=[Chunk(words=(0, 0), content=Plate(text="X"))])
        edit = Edit(name="e", design=_design(), beats={"b1": beat},
                    order=["b1"], output="o.mp4")
        tl = build_timeline(edit, probe=False, probes=probes)
        return dl_cache.beat_key(tl.beats[0], tl.design, quality="draft",
                                 width=None, gpu=False)

    assert key(False) != key(True)


# ─── raster: the caption image ──────────────────────────────────────────────

def _ink_rows(img: Image.Image) -> np.ndarray:
    alpha = np.array(img)[:, :, 3]
    return np.where(alpha.sum(axis=1) > 0)[0]


def test_caption_image_is_full_frame_and_bottom_anchored():
    design = _design((1080, 1920))
    img = render_caption_image("привет мир", design)
    assert img.size == (1080, 1920)
    rows = _ink_rows(img)
    assert len(rows), "caption drew no ink"
    height = 1920
    assert rows.min() > height * 0.55, "caption ink leaked into the top half"
    assert rows.max() < height * 0.97, "caption ink violates the bottom safe margin"


def test_caption_image_wraps_long_text_within_width():
    design = _design((1080, 1920))
    long_text = "это очень длинная фраза которая обязана перенестись"
    img = render_caption_image(long_text, design)
    alpha = np.array(img)[:, :, 3]
    cols = np.where(alpha.sum(axis=0) > 0)[0]
    assert len(cols), "no ink"
    assert cols.min() >= 0 and cols.max() < 1080
    # wrapped block is taller than a single line of the same style
    single = render_caption_image("это", design)
    assert len(_ink_rows(img)) > len(_ink_rows(single))


def test_caption_bg_opacity_zero_disables_pill():
    design = _design((1080, 1920))
    design = design.model_copy(update={
        "captions": design.captions.model_copy(update={"bg_opacity": 0.0})})
    img = render_caption_image("тест", design)
    with_pill = render_caption_image("тест", _design((1080, 1920)))
    assert (np.array(with_pill)[:, :, 3] > 0).sum() > (np.array(img)[:, :, 3] > 0).sum()


# ─── render: the caption is really in the encoded frames ────────────────────

pytestmark_integration = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH")


def _frame_bottom_ink(path, ss) -> int:
    """Count of pixels in the bottom 30% of the frame that deviate strongly
    from the frame's background (median of the top half) at output time ss —
    bright caption text shows up as a large count, an empty bottom as ~0."""
    tmp = str(path) + f".{ss}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(ss), "-i", str(path), "-frames:v", "1",
         "-update", "1", tmp], check=True, capture_output=True)
    arr = np.asarray(Image.open(tmp).convert("L")).astype(float)
    h = arr.shape[0]
    bottom = arr[int(h * 0.70):, :]
    bg = np.median(arr[: int(h * 0.5)])
    return int((np.abs(bottom - bg) > 60).sum())


@pytestmark_integration
def test_rendered_beat_shows_caption_in_window(tmp_path):
    from dlstudio.ir import IRBeat, IRCaption
    from dlstudio.render import RenderOpts, render_beat

    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "sine=frequency=300:duration=2",
         "-ar", "48000", "-ac", "1", str(tmp_path / "vo.wav")],
        check=True, capture_output=True)

    design = _design((320, 568))       # tiny 9:16 for speed
    beat = IRBeat(
        id="b01", duration=2.0, audio=str(tmp_path / "vo.wav"),
        words_path="w.json", words=[WordSpan(t0=0.0, t1=1.0, text="x")],
        segments=[], overlays=[],
        captions=[IRCaption(text="привет мир", t0=0.4, t1=1.4)],
    )
    out = render_beat(beat, design, None,
                      RenderOpts(quality="draft", workdir=tmp_path / "fin"))

    during = _frame_bottom_ink(out, 0.9)    # mid-window
    outside = _frame_bottom_ink(out, 1.8)   # after t1
    assert during > outside + 50, (
        f"caption not visible: during={during} outside={outside}")
