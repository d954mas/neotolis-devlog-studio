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

from dlstudio.compile import probe as probe_mod
from dlstudio.compile.probe import build_registry, classify, probe_asset


@pytest.fixture(autouse=True)
def _isolated_probe_memo(tmp_path, monkeypatch):
    """Every test gets its own probe memo location so tests never touch the
    real workspace data/finalize/.cache2/probe_memo.json, and never see each
    other's memoized entries (mirrors test_cache.py's _isolated_cache_dir)."""
    monkeypatch.setattr(probe_mod, "MEMO_PATH", tmp_path / "cache2" / "probe_memo.json")
    yield


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


# ─── M3: cross-invocation ffprobe memo ─────────────────────────────────────
#
# probe_asset() consults an on-disk memo keyed by absolute path -> {size,
# mtime_ns, probe fields} before shelling out to ffprobe. A 30-beat edit
# probes ~60 assets per CLI invocation even on a full render-cache hit; the
# memo lets repeat invocations skip the subprocess entirely when a referenced
# file hasn't changed. `_isolated_probe_memo` (autouse, above) gives every
# test in this module its own memo file.

def _fake_ffprobe_video(duration="2.0", width=100, height=200):
    payload = json.dumps({
        "format": {"duration": duration},
        "streams": [{"codec_type": "video", "width": width, "height": height}],
    })

    def fake_run(*a, **k):
        return subprocess.CompletedProcess(a[0], 0, stdout=payload, stderr="")
    return fake_run


def test_memo_hit_avoids_subprocess(tmp_path, monkeypatch):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"v1")

    calls = {"n": 0}

    def fake_run(*a, **k):
        calls["n"] += 1
        return subprocess.CompletedProcess(a[0], 0, stdout=json.dumps({
            "format": {"duration": "2.0"},
            "streams": [{"codec_type": "video", "width": 100, "height": 200}],
        }), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    p1 = probe_asset(str(f), "video")
    assert p1.readable is True
    assert calls["n"] == 1

    # Second call, same file untouched -> memo hit, no new subprocess call.
    p2 = probe_asset(str(f), "video")
    assert p2.readable is True
    assert p2.duration == 2.0
    assert p2.width == 100 and p2.height == 200
    assert p2.path == str(f)          # caller's path string, not the memo key
    assert calls["n"] == 1


def test_memo_size_or_mtime_change_forces_reprobe(tmp_path, monkeypatch):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"v1")

    calls = {"n": 0}

    def fake_run(*a, **k):
        calls["n"] += 1
        dur = "2.0" if calls["n"] == 1 else "9.0"
        return subprocess.CompletedProcess(a[0], 0, stdout=json.dumps({
            "format": {"duration": dur},
            "streams": [{"codec_type": "video", "width": 100, "height": 200}],
        }), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    p1 = probe_asset(str(f), "video")
    assert p1.duration == 2.0
    assert calls["n"] == 1

    f.write_bytes(b"v2-longer-content")   # changes size (and mtime_ns)
    p2 = probe_asset(str(f), "video")
    assert p2.duration == 9.0
    assert calls["n"] == 2


def test_memo_readable_false_result_is_memoized(tmp_path, monkeypatch):
    f = tmp_path / "clip.mp4"
    f.write_bytes(b"not a real video")

    calls = {"n": 0}

    def fake_run(*a, **k):
        calls["n"] += 1
        return subprocess.CompletedProcess(a[0], 1, stdout="", stderr="bad")

    monkeypatch.setattr(subprocess, "run", fake_run)

    p1 = probe_asset(str(f), "video")
    assert p1.readable is False
    assert calls["n"] == 1

    p2 = probe_asset(str(f), "video")   # readable=False is memoized too
    assert p2.readable is False
    assert calls["n"] == 1


def test_memo_missing_file_never_memoized(tmp_path):
    p = probe_asset(str(tmp_path / "nope.mp4"), "video")
    assert p.exists is False
    assert probe_mod._load_memo() == {}


def test_memo_corrupt_file_tolerated(tmp_path, monkeypatch):
    memo_path = probe_mod.MEMO_PATH
    memo_path.parent.mkdir(parents=True, exist_ok=True)
    memo_path.write_text("{not valid json", encoding="utf-8")

    f = tmp_path / "clip.mp4"
    f.write_bytes(b"whatever")
    monkeypatch.setattr(subprocess, "run", _fake_ffprobe_video(duration="1.0"))

    p = probe_asset(str(f), "video")     # must not raise despite corrupt memo
    assert p.readable is True
    assert p.duration == 1.0

    reloaded = json.loads(memo_path.read_text(encoding="utf-8"))
    assert str(f.resolve()) in reloaded


def test_memo_env_var_override(tmp_path, monkeypatch):
    # MEMO_PATH (module default) is monkeypatched by the autouse fixture to a
    # tmp_path location; the env var must take precedence over it.
    override_path = tmp_path / "override" / "probe_memo.json"
    monkeypatch.setenv(probe_mod.MEMO_PATH_ENV_VAR, str(override_path))

    f = tmp_path / "clip.mp4"
    f.write_bytes(b"whatever")
    monkeypatch.setattr(subprocess, "run", _fake_ffprobe_video(duration="3.0"))

    probe_asset(str(f), "video")

    assert override_path.exists()
    assert not probe_mod.MEMO_PATH.exists()   # the (unused) default must stay untouched


# ─── batched memo writes: N misses through build_registry -> 1 file write ──
#
# build_registry shares one _MemoSession across the whole pass, so the memo is
# read once and written once instead of read-prune-rewritten per miss.

def test_build_registry_batches_memo_to_one_write(tmp_path, monkeypatch):
    files = {}
    for i in range(5):
        f = tmp_path / f"clip{i}.mp4"
        f.write_bytes(f"v{i}".encode())
        files[str(f)] = "video"

    monkeypatch.setattr(subprocess, "run", _fake_ffprobe_video(duration="2.0"))

    writes = {"n": 0}
    real_write = probe_mod._atomic_write_memo

    def counting_write(path, memo, **kw):
        writes["n"] += 1
        return real_write(path, memo, **kw)

    monkeypatch.setattr(probe_mod, "_atomic_write_memo", counting_write)

    reg = build_registry(files, probe=True, injected=None)
    assert len(reg) == 5
    assert all(reg[p].readable for p in files)
    # 5 misses, but the whole registry flushes exactly once.
    assert writes["n"] == 1


def test_build_registry_second_pass_is_all_memo_hits(tmp_path, monkeypatch):
    files = {}
    for i in range(3):
        f = tmp_path / f"c{i}.mp4"
        f.write_bytes(f"data{i}".encode())
        files[str(f)] = "video"

    calls = {"n": 0}

    def fake_run(*a, **k):
        calls["n"] += 1
        return subprocess.CompletedProcess(a[0], 0, stdout=json.dumps({
            "format": {"duration": "2.0"},
            "streams": [{"codec_type": "video", "width": 10, "height": 20}],
        }), stderr="")

    monkeypatch.setattr(subprocess, "run", fake_run)

    build_registry(files, probe=True, injected=None)
    assert calls["n"] == 3                     # first pass: 3 misses

    # Second pass: the memo persisted at the first flush -> all hits, no probes.
    reg2 = build_registry(files, probe=True, injected=None)
    assert calls["n"] == 3
    assert all(reg2[p].duration == 2.0 for p in files)


def test_build_registry_no_probes_needed_never_writes(tmp_path, monkeypatch):
    # Only font/other kinds (never ffprobed) -> the session stays clean and
    # must not write the memo at all.
    font = tmp_path / "f.ttf"
    font.write_bytes(b"x")
    other = tmp_path / "n.txt"
    other.write_text("hi", encoding="utf-8")

    writes = {"n": 0}
    monkeypatch.setattr(probe_mod, "_atomic_write_memo",
                        lambda *a, **k: writes.__setitem__("n", writes["n"] + 1))

    build_registry({str(font): "font", str(other): "other"},
                   probe=True, injected=None)
    assert writes["n"] == 0


def test_memo_atomic_write_leaves_no_temp_on_failure(tmp_path, monkeypatch):
    memo_path = tmp_path / "cache2" / "probe_memo.json"

    def boom_replace(src, dst):
        raise OSError("disk full (simulated)")

    monkeypatch.setattr(probe_mod.os, "replace", boom_replace)
    monkeypatch.setattr(probe_mod.time, "sleep", lambda *_a, **_k: None)

    with pytest.raises(OSError):
        probe_mod._atomic_write_memo(memo_path, {"some": "data"})

    assert not memo_path.exists()
    assert list(memo_path.parent.glob("*.tmp-*")) == []
