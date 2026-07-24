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
    IRSegmentGeometry,
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


def test_normalize_segment_uses_explicit_ir_crop_coordinates():
    design = Design(
        resolution=(100, 100), fps=24,
        palette=Palette(tokens={"bg": "#000000", "text": "#ffffff"}),
        fonts=Fonts(main="none.ttf"),
    )
    segment = IRSegment(
        kind="video",
        src="wide.mp4",
        offset=0.0,
        t0=0.0,
        t1=2.0,
        fit="cover",
        geometry=IRSegmentGeometry(
            fit="cover",
            anchor_x=0.5,
            anchor_y=0.5,
            source_width=200,
            source_height=100,
            scaled_width=200,
            scaled_height=100,
            output_width=100,
            output_height=100,
            crop_x=50,
            crop_y=0,
            crop_width=100,
            crop_height=100,
        ),
    )

    chain = beat_mod._normalize_segment(
        0, segment, 2.0, 0.0, design, "0x000000", "explicit",
    ).render()

    assert "scale=200:100" in chain
    assert "crop=100:100:50:0" in chain


def test_normalize_segment_retargets_ir_geometry_for_draft_profile():
    design = Design(
        resolution=(100, 100), fps=24,
        palette=Palette(tokens={"bg": "#000000", "text": "#ffffff"}),
        fonts=Fonts(main="none.ttf"),
    )
    delivery_geometry = IRSegmentGeometry.resolve(
        fit="cover",
        anchor_x=0.5,
        anchor_y=0.5,
        source_width=200,
        source_height=100,
        output_width=200,
        output_height=200,
    )
    segment = IRSegment(
        kind="video",
        src="wide.mp4",
        offset=0.0,
        t0=0.0,
        t1=2.0,
        fit="cover",
        geometry=delivery_geometry,
    )

    chain = beat_mod._normalize_segment(
        0, segment, 2.0, 0.0, design, "0x000000", "draft",
    ).render()

    assert "scale=200:100" in chain
    assert "crop=100:100:50:0" in chain


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


def test_ken_burns_changes_every_draft_frame(tmp_path):
    """A slow Ken Burns zoom must not hold an integer scale for many frames.

    This exercises the exact normalize chain before lossy encoding, where the
    old ``scale=iw*(1+...)`` implementation repeated raw frames at 304x540.
    """
    design = Design(
        resolution=(304, 540), fps=24,
        palette=Palette(tokens={"bg": "#000000", "text": "#ffffff"}),
        fonts=Fonts(main="none.ttf"),
    )
    source = tmp_path / "portrait-grid.png"
    image = Image.new("RGB", (608, 1080), (12, 18, 28))
    draw = ImageDraw.Draw(image)
    for x in range(0, image.width, 12):
        draw.line((x, 0, x, image.height), fill=(220, 80, 40), width=3)
    for y in range(0, image.height, 12):
        draw.line((0, y, image.width, y), fill=(40, 160, 230), width=3)
    image.save(source)

    duration = 3.0
    segment = IRSegment(
        kind="image", src=str(source), offset=0.0,
        t0=0.0, t1=duration, ken_burns=True,
    )
    chain = beat_mod._normalize_segment(
        0, segment, duration, 0.0, design, "0x000000", "smooth",
    ).render()
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-loop", "1", "-i", str(source),
            "-filter_complex", chain, "-map", "[smooth]",
            "-frames:v", str(round(duration * design.fps)),
            "-f", "framemd5", "-",
        ],
        check=True, capture_output=True, text=True,
    )
    hashes = [
        line.rsplit(",", 1)[-1].strip()
        for line in result.stdout.splitlines()
        if line.startswith("0,")
    ]

    assert len(hashes) == round(duration * design.fps)
    assert all(left != right for left, right in zip(hashes, hashes[1:]))


def test_render_beat_hard_cuts_preserve_all_segment_video(tmp_path):
    """A zero-duration scene transition is a concat cut, not xfade=dur=0.

    FFmpeg's xfade filter treats ``duration=0`` as a degenerate transition
    and emits roughly only its second input.  The MP4 container can still
    have the expected duration because the VO stream is intact, hiding the
    truncated video track unless VQ-SYNC checks streams separately.
    """
    design = _design()
    dur = 3.0
    audio = tmp_path / "vo.wav"
    _make_wav(audio, dur)

    images = []
    for i, color in enumerate(((120, 10, 10), (10, 120, 10), (10, 10, 120))):
        image = tmp_path / f"seg{i}.png"
        _solid_png(image, color)
        images.append(image)

    beat = IRBeat(
        id="b_cuts",
        duration=dur,
        audio=str(audio),
        words_path=str(tmp_path / "words.json"),
        words=[WordSpan(t0=0.0, t1=dur, text="hi")],
        segments=[
            IRSegment(kind="image", src=str(images[0]), offset=0.0,
                      t0=0.0, t1=1.0,
                      xfade=Transition(kind="cut", dur=0.0)),
            IRSegment(kind="image", src=str(images[1]), offset=0.0,
                      t0=1.0, t1=1.75,
                      xfade=Transition(kind="cut", dur=0.0)),
            IRSegment(kind="image", src=str(images[2]), offset=0.0,
                      t0=1.75, t1=dur),
        ],
        overlays=[],
    )
    opts = RenderOpts(quality="draft", workdir=tmp_path / "finalize")

    out = render_beat(beat, design, None, opts)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration", "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True,
    )
    assert float(probe.stdout.strip()) == pytest.approx(dur, abs=0.10)


def test_render_beat_hard_cut_then_fade_uses_one_timebase(tmp_path):
    """A concat cut followed by xfade must keep compatible input timebases."""
    design = _design()
    dur = 3.0
    audio = tmp_path / "vo.wav"
    _make_wav(audio, dur)

    images = []
    for i, color in enumerate(((120, 10, 10), (10, 120, 10), (10, 10, 120))):
        image = tmp_path / f"mixed{i}.png"
        _solid_png(image, color)
        images.append(image)

    beat = IRBeat(
        id="b_cut_fade",
        duration=dur,
        audio=str(audio),
        words_path=str(tmp_path / "words.json"),
        words=[WordSpan(t0=0.0, t1=dur, text="hi")],
        segments=[
            IRSegment(kind="image", src=str(images[0]), offset=0.0,
                      t0=0.0, t1=1.0,
                      xfade=Transition(kind="cut", dur=0.0)),
            IRSegment(kind="image", src=str(images[1]), offset=0.0,
                      t0=1.0, t1=1.75,
                      xfade=Transition(kind="fade", dur=0.2)),
            IRSegment(kind="image", src=str(images[2]), offset=0.0,
                      t0=1.75, t1=dur),
        ],
        overlays=[],
    )
    opts = RenderOpts(quality="draft", workdir=tmp_path / "finalize")

    out = render_beat(beat, design, None, opts)

    probe = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "v:0",
         "-show_entries", "stream=duration", "-of", "csv=p=0", str(out)],
        check=True, capture_output=True, text=True,
    )
    assert float(probe.stdout.strip()) == pytest.approx(dur, abs=0.10)


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


# ─── _bg_color: 3-digit hex shorthand ──────────────────────────────────────
#
# _bg_color used to only handle #rrggbb (6 hex digits); a 3-digit shorthand
# like "#abc" fell through to the "not exactly 6 digits" branch and silently
# rendered as black instead of the intended color. Fixed by expanding the
# shorthand inline (duplicated from render.raster._util.hex_to_rgb's 3->6
# expansion -- beat.py must not import from raster/, see layering note).

def _design_with_bg(hexv):
    return Design(
        resolution=(320, 180), fps=24,
        palette=Palette(tokens={"bg": hexv, "text": "#ffffff"}),
        fonts=Fonts(main="none.ttf"),
    )


def test_bg_color_expands_3_digit_hex_shorthand():
    design = _design_with_bg("#abc")
    assert beat_mod._bg_color(design) == "0xAABBCC"


def test_bg_color_6_digit_hex_still_works():
    design = _design_with_bg("#101418")
    assert beat_mod._bg_color(design) == "0x101418"


def test_bg_color_invalid_falls_back_to_black():
    design = _design_with_bg("not-a-color")
    assert beat_mod._bg_color(design) == "0x000000"


# ─── L5b: _duration_cache keyed by (path, size, mtime_ns), not path alone ──
#
# A path-only key goes stale within a long-lived process (e.g. a future
# watch mode): editing a source file on disk keeps the same path but the
# cache would keep serving the pre-edit duration forever. Keying on identity
# (size + mtime_ns) makes an edited file a cache miss, same as
# dlstudio.cache's asset-identity fingerprint.

def test_probe_duration_cache_reprobes_after_file_content_change(tmp_path, monkeypatch):
    beat_mod._duration_cache.clear()
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"v1")

    calls = {"n": 0}

    def fake_run_v1(cmd, **kwargs):
        calls["n"] += 1
        return subprocess.CompletedProcess(cmd, 0, stdout="5.0\n", stderr="")

    monkeypatch.setattr(beat_mod.subprocess, "run", fake_run_v1)

    d1 = beat_mod._probe_duration(str(src))
    assert d1 == 5.0
    assert calls["n"] == 1

    # Same path, unchanged file -> cache hit, no subprocess call.
    d2 = beat_mod._probe_duration(str(src))
    assert d2 == 5.0
    assert calls["n"] == 1

    # Change the file's content (and mtime) at the SAME path -> must re-probe,
    # not silently keep serving the stale 5.0 duration.
    src.write_bytes(b"v2-longer-content-forces-a-new-mtime-and-size")

    def fake_run_v2(cmd, **kwargs):
        calls["n"] += 1
        return subprocess.CompletedProcess(cmd, 0, stdout="9.0\n", stderr="")

    monkeypatch.setattr(beat_mod.subprocess, "run", fake_run_v2)

    d3 = beat_mod._probe_duration(str(src))
    assert d3 == 9.0
    assert calls["n"] == 2
    beat_mod._duration_cache.clear()
