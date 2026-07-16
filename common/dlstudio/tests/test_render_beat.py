"""Integration tests for render_beat against real ffmpeg.

Tiny/fast: 320x180, ~3s, draft (libx264 ultrafast). Segment backgrounds are
generated PNGs; overlay rasterisation is mocked (a PIL PNG) so this test does
not depend on the parallel raster-agent. Total runtime target < ~20s.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest
from PIL import Image, ImageDraw, ImageStat

from dlstudio.ir import (
    BeatPlacement,
    IRBeat,
    IRMix,
    IROverlayItem,
    IRSegment,
    Timeline,
    WordSpan,
)
from dlstudio.model import Chunk, Design, Fonts, Palette, Plate, Transition
from dlstudio.render import RenderOpts, render_beat
from dlstudio.render import beat as beat_mod

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None,
                                reason="ffmpeg not on PATH")


def _design():
    return Design(
        resolution=(320, 180),
        fps=24,
        palette=Palette(tokens={"bg": "#0a0e14", "text": "#ffffff",
                                "accent": "#ffcc00"}),
        fonts=Fonts(main="none.ttf"),
    )


def _make_wav(path, dur):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"sine=frequency=220:duration={dur}", "-ac", "1", str(path)],
        check=True, capture_output=True,
    )


def _solid_png(path, color, size=(640, 360)):
    Image.new("RGB", size, color).save(path)


def _grab(mp4, t, out):
    # accurate seek (after -i) so we hit the exact overlay window
    subprocess.run(
        ["ffmpeg", "-y", "-i", str(mp4), "-ss", f"{t:.3f}",
         "-frames:v", "1", str(out)],
        check=True, capture_output=True,
    )
    return Image.open(out).convert("RGB")


def _box_mean(img, cx, cy, r=5):
    box = img.crop((cx - r, cy - r, cx + r, cy + r))
    return ImageStat.Stat(box).mean  # [R, G, B]


def _fake_raster(chunk, design, out_path):
    """Stand-in for render.raster.render_chunk_png: white centre block for
    overlay 0, green top-left block for overlay 1."""
    w, h = design.resolution
    img = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    if out_path.name == "ov_0.png":
        d.rectangle([120, 60, 200, 120], fill=(255, 255, 255, 255))
    else:
        d.rectangle([10, 10, 70, 50], fill=(0, 255, 0, 255))
    img.save(out_path)
    return out_path


def test_render_beat_two_segments_with_overlays(tmp_path, monkeypatch):
    design = _design()
    dur = 3.0

    audio = tmp_path / "vo.wav"
    _make_wav(audio, dur)
    seg0 = tmp_path / "seg0.png"
    seg1 = tmp_path / "seg1.png"
    _solid_png(seg0, (12, 16, 28))      # dark blue
    _solid_png(seg1, (28, 12, 16))      # dark red

    beat = IRBeat(
        id="b01",
        duration=dur,
        audio=str(audio),
        words_path=str(tmp_path / "words.json"),
        words=[WordSpan(t0=0.0, t1=dur, text="hi")],
        segments=[
            IRSegment(kind="image", src=str(seg0), offset=0.0, t0=0.0, t1=1.5,
                      xfade=Transition(kind="fade", dur=0.3)),
            IRSegment(kind="image", src=str(seg1), offset=0.0, t0=1.5, t1=3.0),
        ],
        overlays=[
            # A: whole beat, white centre block
            IROverlayItem(chunk_index=0, z=0, t0=0.0, t1=3.0,
                          transition_in=Transition(kind="fade", dur=0.2)),
            # B: starts at 1.6 -> exercises the setpts PTS-shift invariant
            IROverlayItem(chunk_index=1, z=1, t0=1.6, t1=3.0),
        ],
    )
    timeline = Timeline(
        edit_name="t", design=design, beats=[beat],
        placements=[BeatPlacement(beat_id="b01", t0=0.0)],
        mix=IRMix(), assets={}, output=str(tmp_path / "out.mp4"),
    )

    monkeypatch.setattr(beat_mod, "render_chunk_png", _fake_raster)
    monkeypatch.setattr(beat_mod, "_chunk_resolver",
                        lambda bid, idx: Chunk(words=(0, 1),
                                               content=Plate(text="x")))

    opts = RenderOpts(quality="draft", workdir=tmp_path / "finalize")
    out = render_beat(beat, design, timeline, opts)

    # exists + duration postcondition (render_beat would have raised otherwise)
    assert out.exists()
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    assert abs(float(r.stdout.strip()) - dur) < 0.35

    # VO stem copied next to the MP4 for Phase-2 ducking
    assert (out.parent / "b01_vo_stem.wav").exists()

    # frame @0.75s: seg0, overlay A visible, overlay B NOT yet
    f1 = _grab(out, 0.75, tmp_path / "f1.png")
    assert sum(_box_mean(f1, 160, 90)) / 3 > 150            # white centre (A)
    assert sum(_box_mean(f1, 40, 30)) / 3 < 90              # corner still bg (no B)

    # frame @2.30s: seg1, overlays A + B both visible (B proves PTS-shift)
    f2 = _grab(out, 2.30, tmp_path / "f2.png")
    assert sum(_box_mean(f2, 160, 90)) / 3 > 140            # white centre (A)
    g = _box_mean(f2, 40, 30)                               # top-left corner
    assert g[1] > 110 and g[1] > g[0] and g[1] > g[2]       # green block (B)


def test_render_beat_no_segments_solid_bg(tmp_path, monkeypatch):
    """Fallback path: no scenes, no overlays -> solid color bg + audio."""
    design = _design()
    dur = 1.5
    audio = tmp_path / "vo.wav"
    _make_wav(audio, dur)

    beat = IRBeat(
        id="b_solid",
        duration=dur,
        audio=str(audio),
        words_path=str(tmp_path / "w.json"),
        words=[WordSpan(t0=0.0, t1=dur, text="x")],
        segments=[],
        overlays=[],
    )
    timeline = Timeline(
        edit_name="t", design=design, beats=[beat],
        placements=[BeatPlacement(beat_id="b_solid", t0=0.0)],
        mix=IRMix(), assets={}, output=str(tmp_path / "o.mp4"),
    )
    opts = RenderOpts(quality="draft", workdir=tmp_path / "fin")
    out = render_beat(beat, design, timeline, opts)
    assert out.exists()
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(out)],
        capture_output=True, text=True,
    )
    assert abs(float(r.stdout.strip()) - dur) < 0.35


def test_render_beat_missing_resolver_raises(tmp_path, monkeypatch):
    """A beat with overlays but no chunk resolver fails with a clear error."""
    design = _design()
    audio = tmp_path / "vo.wav"
    _make_wav(audio, 1.0)
    beat = IRBeat(
        id="b_no_res", duration=1.0, audio=str(audio),
        words_path=str(tmp_path / "w.json"),
        words=[WordSpan(t0=0.0, t1=1.0, text="x")],
        segments=[],
        overlays=[IROverlayItem(chunk_index=0, z=0, t0=0.0, t1=1.0)],
    )
    timeline = Timeline(
        edit_name="t", design=design, beats=[beat],
        placements=[BeatPlacement(beat_id="b_no_res", t0=0.0)],
        mix=IRMix(), assets={}, output=str(tmp_path / "o.mp4"),
    )
    monkeypatch.setattr(beat_mod, "_chunk_resolver", None)
    opts = RenderOpts(quality="draft", workdir=tmp_path / "fin")
    with pytest.raises(RuntimeError, match="chunk resolver"):
        render_beat(beat, design, timeline, opts)
