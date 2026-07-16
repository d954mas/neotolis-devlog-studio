"""Asset probing: ffprobe facts, `AssetProbe.readable` tri-state, and the
build_registry(probe=True) path.

`readable` distinguishes present-but-broken files from healthy ones:
None = not determined (missing file, or a font/other kind never ffprobed),
True = ffprobe succeeded, False = the file exists but ffprobe failed on it
(nonzero exit or unparseable output).
"""
from __future__ import annotations

import json
import shutil
import subprocess

import pytest

from dlstudio.compile.probe import build_registry, classify, probe_asset


# ─── classify ────────────────────────────────────────────────────────────────

def test_classify_by_extension():
    assert classify("a.mp4") == "video"
    assert classify("a.wav") == "audio"
    assert classify("a.png") == "image"
    assert classify("a.ttf") == "font"
    assert classify("a.unknownext") == "other"


# ─── missing files / unprobed kinds -> readable stays None ─────────────────

def test_missing_file_readable_undetermined():
    p = probe_asset("/no/such/file.mp4", "video")
    assert p.exists is False
    assert p.readable is None


def test_font_kind_not_probed_readable_undetermined(tmp_path):
    f = tmp_path / "font.ttf"
    f.write_bytes(b"not a real font, but it exists")
    p = probe_asset(str(f), "font")
    assert p.exists is True
    assert p.readable is None


def test_other_kind_not_probed_readable_undetermined(tmp_path):
    f = tmp_path / "notes.txt"
    f.write_text("hi", encoding="utf-8")
    p = probe_asset(str(f), "other")
    assert p.exists is True
    assert p.readable is None


# ─── ffprobe failure -> readable=False (monkeypatched subprocess) ──────────

def test_ffprobe_nonzero_rc_marks_unreadable(tmp_path, monkeypatch):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"this is not actually a video file")

    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a[0], 1, stdout="", stderr="invalid data found")

    monkeypatch.setattr(subprocess, "run", fake_run)
    p = probe_asset(str(f), "video")
    assert p.exists is True
    assert p.readable is False
    assert p.duration is None and p.width is None and p.height is None


def test_ffprobe_unparseable_json_marks_unreadable(tmp_path, monkeypatch):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"whatever bytes")

    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a[0], 0, stdout="not json at all", stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    p = probe_asset(str(f), "video")
    assert p.exists is True
    assert p.readable is False


# ─── ffprobe success -> readable=True ──────────────────────────────────────

def test_ffprobe_success_marks_readable(tmp_path, monkeypatch):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"whatever bytes")

    payload = json.dumps({
        "format": {"duration": "2.5"},
        "streams": [{"codec_type": "video", "width": 1080, "height": 1920}],
    })

    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a[0], 0, stdout=payload, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    p = probe_asset(str(f), "video")
    assert p.readable is True
    assert p.duration == 2.5
    assert p.width == 1080 and p.height == 1920


def test_ffprobe_success_image_readable_true_no_duration(tmp_path, monkeypatch):
    f = tmp_path / "pic.png"
    f.write_bytes(b"whatever bytes")

    payload = json.dumps({
        "format": {"duration": "0.04"},   # images sometimes report a bogus duration
        "streams": [{"codec_type": "video", "width": 1080, "height": 1920}],
    })

    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a[0], 0, stdout=payload, stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)
    p = probe_asset(str(f), "image")
    assert p.readable is True
    assert p.duration is None          # images never report a meaningful duration


# ─── build_registry(probe=True) end-to-end ─────────────────────────────────

def test_build_registry_probe_true_marks_unreadable_for_corrupt_file(tmp_path, monkeypatch):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"not a real video")

    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a[0], 1, stdout="", stderr="bad")

    monkeypatch.setattr(subprocess, "run", fake_run)
    reg = build_registry({str(f): "video"}, probe=True, injected=None)
    assert reg[str(f)].exists is True
    assert reg[str(f)].readable is False


def test_build_registry_probe_false_leaves_readable_none_when_uninjected(tmp_path):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"anything")
    reg = build_registry({str(f): "video"}, probe=False, injected=None)
    assert reg[str(f)].exists is True
    assert reg[str(f)].readable is None    # cheap Path.exists() fallback, no ffprobe


# ─── real ffprobe on a genuinely corrupt file ──────────────────────────────

@pytest.mark.slow
def test_real_corrupt_mp4_marks_unreadable(tmp_path):
    if shutil.which("ffprobe") is None:      # pragma: no cover
        pytest.skip("ffprobe not on PATH")
    corrupt = tmp_path / "corrupt.mp4"
    corrupt.write_text("this is definitely not a video file", encoding="utf-8")
    p = probe_asset(str(corrupt), "video")
    assert p.exists is True
    assert p.readable is False


@pytest.mark.slow
def test_real_ffprobe_on_real_video_marks_readable(tmp_path):
    if shutil.which("ffmpeg") is None:       # pragma: no cover
        pytest.skip("ffmpeg not on PATH")
    mp4 = tmp_path / "clip.mp4"
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i", "testsrc=d=1:s=64x64:r=10",
         "-pix_fmt", "yuv420p", str(mp4)],
        check=True, capture_output=True)
    p = probe_asset(str(mp4), "video")
    assert p.exists is True
    assert p.readable is True
    assert p.duration is not None and p.duration > 0
