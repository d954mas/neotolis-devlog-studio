"""Check gates: VQ-ASSET, VQ-WORDS, VQ-RES, VQ-OFFSET, and the VQ-SYNC
postcondition verify_output()."""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from _builders import mk_design, plate_chunk, probe
from dlstudio.check import run_checks, verify_output
from dlstudio.compile import build_timeline
from dlstudio.ir import (
    AssetProbe,
    BeatPlacement,
    IRBeat,
    IRMix,
    IROverlayItem,
    IRSegment,
    Timeline,
    WordSpan,
)
from dlstudio.model import Beat, Edit


# ── helpers to construct IR directly (isolate individual gates) ──────────────

def mk_beat(*, beat_id="b1", duration=4.0, segments=None, overlays=None):
    return IRBeat(
        id=beat_id, duration=duration, audio="vo.wav", words_path="w.json",
        words=[WordSpan(t0=0.0, t1=0.4, text="a")],
        segments=segments or [], overlays=overlays or [],
    )


def mk_timeline(*, beats=None, assets=None, warnings=None, resolution=(1080, 1920)):
    beats = beats or [mk_beat()]
    return Timeline(
        edit_name="e", design=mk_design(resolution=resolution), beats=beats,
        placements=[BeatPlacement(beat_id=b.id, t0=0.0) for b in beats],
        mix=IRMix(), assets=assets or {}, output="out.mp4",
        warnings=warnings or [],
    )


def seg(src, kind="image", t0=0.0, t1=4.0):
    return IRSegment(kind=kind, src=src, offset=0.0, t0=t0, t1=t1)


def ov(chunk_index, z, t0, t1):
    return IROverlayItem(chunk_index=chunk_index, z=z, t0=t0, t1=t1)


# ── VQ-ASSET ─────────────────────────────────────────────────────────────────

def test_vq_asset_missing_file_errors():
    assets = {"gone.png": probe("gone.png", "image", exists=False)}
    rep = run_checks(mk_timeline(assets=assets))
    assert not rep.ok
    codes = {i.code for i in rep.errors}
    assert "VQ-ASSET" in codes
    assert any(i.where == "gone.png" for i in rep.errors)


def test_vq_asset_all_present_passes():
    assets = {"there.png": probe("there.png", "image", width=1080, height=1920)}
    rep = run_checks(mk_timeline(assets=assets))
    assert not any(i.code == "VQ-ASSET" for i in rep.issues)


# ── VQ-WORDS ─────────────────────────────────────────────────────────────────

def test_vq_words_overlapping_overlays_errors():
    beat = mk_beat(overlays=[ov(0, 0, 0.0, 2.5), ov(1, 1, 2.0, 4.0)])  # 2.5 > 2.0
    rep = run_checks(mk_timeline(beats=[beat]))
    assert not rep.ok
    assert any(i.code == "VQ-WORDS" and "overlapping" in i.message for i in rep.errors)


def test_vq_words_unordered_overlays_errors():
    beat = mk_beat(overlays=[ov(0, 0, 3.0, 4.0), ov(1, 1, 1.0, 2.0)])  # goes backwards
    rep = run_checks(mk_timeline(beats=[beat]))
    assert any(i.code == "VQ-WORDS" and "out of order" in i.message for i in rep.errors)


def test_vq_words_tiled_overlays_pass():
    beat = mk_beat(overlays=[ov(0, 0, 0.0, 2.0), ov(1, 1, 2.0, 4.0)])
    rep = run_checks(mk_timeline(beats=[beat]))
    assert not any(i.code == "VQ-WORDS" for i in rep.issues)


def test_vq_words_out_of_range_index_from_compile_warning(tmp_path):
    # end-to-end: compile clamps + tags a VQ-WORDS warning; run_checks promotes.
    wp = tmp_path / "w.json"
    wp.write_text(json.dumps({"words": [{"word": "a", "start": 0.0, "end": 0.4}]}),
                  encoding="utf-8")
    beat = Beat(audio="vo.wav", words=str(wp), chunks=[plate_chunk(0, 0), plate_chunk(5, 9)])
    edit = Edit(name="e", design=mk_design(), beats={"b1": beat}, order=["b1"], output="o.mp4")
    probes = {
        "vo.wav": probe("vo.wav", "audio", duration=4.0),
        "/fonts/main.ttf": probe("/fonts/main.ttf", "font"),
        "/fonts/bold.ttf": probe("/fonts/bold.ttf", "font"),
    }
    tl = build_timeline(edit, probe=False, probes=probes)
    rep = run_checks(tl)
    assert not rep.ok
    words_errs = [i for i in rep.errors if i.code == "VQ-WORDS"]
    # the out-of-range index (from the compile warning) is promoted, located to
    # the beat; other VQ-WORDS errors (e.g. overlap) may also be present.
    assert any("out of range" in i.message and i.where == "b1" for i in words_errs)


# ── VQ-RES ───────────────────────────────────────────────────────────────────

def test_vq_res_dimension_over_4096_errors():
    # the 3840x6826 x264 OOM class
    rep = run_checks(mk_timeline(resolution=(3840, 6826)))
    assert not rep.ok
    assert any(i.code == "VQ-RES" and "exceeds encoder-safe" in i.message
               for i in rep.errors)


def test_vq_res_excessive_upscale_errors():
    assets = {"tiny.png": probe("tiny.png", "image", width=320, height=240)}
    beat = mk_beat(segments=[seg("tiny.png")])
    rep = run_checks(mk_timeline(beats=[beat], assets=assets, resolution=(1080, 1920)))
    assert not rep.ok
    res = [i for i in rep.errors if i.code == "VQ-RES"]
    assert res and "upscales" in res[0].message


def test_vq_res_source_at_target_passes():
    assets = {"full.png": probe("full.png", "image", width=1080, height=1920)}
    beat = mk_beat(segments=[seg("full.png")])
    rep = run_checks(mk_timeline(beats=[beat], assets=assets, resolution=(1080, 1920)))
    assert not any(i.code == "VQ-RES" for i in rep.issues)


def test_vq_res_within_2_2x_passes():
    # 540x960 -> 1080x1920 is exactly 2.0x, under the 2.2 cap
    assets = {"half.png": probe("half.png", "image", width=540, height=960)}
    beat = mk_beat(segments=[seg("half.png")])
    rep = run_checks(mk_timeline(beats=[beat], assets=assets, resolution=(1080, 1920)))
    assert not any(i.code == "VQ-RES" for i in rep.issues)


def test_vq_res_unprobed_segment_skipped():
    beat = mk_beat(segments=[seg("unknown.png")])   # no probe in assets
    rep = run_checks(mk_timeline(beats=[beat], assets={}))
    assert not any(i.code == "VQ-RES" for i in rep.issues)


# ── VQ-OFFSET (warn, not error) ──────────────────────────────────────────────

def test_vq_offset_warning_promoted_but_not_error():
    tl = mk_timeline(warnings=[
        "[b1] VQ-OFFSET: scene offset 99.00s is at/past source duration 10.00s "
        "for bg.mp4; clamped to 9.00s"])
    rep = run_checks(tl)
    assert rep.ok                                    # warn does not fail the gate
    offs = [i for i in rep.issues if i.code == "VQ-OFFSET"]
    assert offs and offs[0].severity == "warn"
    assert offs[0].where == "b1"


def test_clean_timeline_passes_all_gates():
    assets = {"bg.png": probe("bg.png", "image", width=1080, height=1920),
              "vo.wav": probe("vo.wav", "audio", duration=4.0)}
    beat = mk_beat(segments=[seg("bg.png")],
                   overlays=[ov(0, 0, 0.0, 2.0), ov(1, 1, 2.0, 4.0)])
    rep = run_checks(mk_timeline(beats=[beat], assets=assets))
    assert rep.ok and rep.issues == []


# ── VQ-SYNC / verify_output ──────────────────────────────────────────────────

@pytest.fixture(scope="module")
def media(tmp_path_factory):
    if shutil.which("ffmpeg") is None:      # pragma: no cover
        pytest.skip("ffmpeg not on PATH")
    d = tmp_path_factory.mktemp("media")
    mp4 = d / "clip.mp4"
    wav = d / "silent.wav"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=d=2:s=320x240:r=30",
         "-pix_fmt", "yuv420p", str(mp4)],
        check=True, capture_output=True)
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "anullsrc=r=48000:cl=mono",
         "-t", "2", str(wav)],
        check=True, capture_output=True)
    return {"mp4": str(mp4), "wav": str(wav), "dir": str(d)}


def test_verify_output_passes_within_tolerance(media):
    verify_output(media["mp4"], 2.0, tolerance=0.25)     # ~2.0s, no raise


def test_verify_output_duration_mismatch_raises(media):
    with pytest.raises(RuntimeError, match="duration mismatch") as e:
        verify_output(media["mp4"], 10.0)
    # both durations reported (the fact the v1 bug hid)
    assert "2.0" in str(e.value) and "10.0" in str(e.value)


def test_verify_output_missing_file_raises():
    with pytest.raises(RuntimeError, match="does not exist"):
        verify_output("/no/such/file.mp4", 2.0)


def test_verify_output_no_video_stream_raises(media):
    with pytest.raises(RuntimeError, match="no video stream"):
        verify_output(media["wav"], 2.0)
