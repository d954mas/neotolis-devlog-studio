"""Tests for dlstudio.cache -- content-addressable, atomic render cache.

All inputs are built directly (IRBeat/Design via conftest builders); this
suite never depends on dlstudio.compile / dlstudio.render being
implemented.
"""
from __future__ import annotations

import itertools
import json
import os
import threading
import time
from pathlib import Path

import pytest

from dlstudio import cache
from dlstudio.ir import IROverlayItem, IRSegment, IRSfx

from conftest import make_design, make_ir_beat


@pytest.fixture(autouse=True)
def _isolated_cache_dir(tmp_path, monkeypatch):
    """Every test gets its own cache dir so tests never touch the real
    workspace data/finalize/.cache2, and never see each other's entries."""
    monkeypatch.setattr(cache, "CACHE_DIR", tmp_path / "cache2")
    yield


def _write(path: Path, content: bytes = b"hello") -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(content)


# ─── beat_key: stability & sensitivity to each input dimension ─────────

def test_beat_key_stable_across_calls():
    beat = make_ir_beat()
    design = make_design()
    k1 = cache.beat_key(beat, design, quality="draft", width=None, gpu=False)
    k2 = cache.beat_key(beat, design, quality="draft", width=None, gpu=False)
    assert k1 == k2
    assert len(k1) == 40  # sha1 hexdigest


def test_beat_key_changes_with_beat_content():
    design = make_design()
    k1 = cache.beat_key(make_ir_beat(duration=5.0), design, quality="draft", width=None, gpu=False)
    k2 = cache.beat_key(make_ir_beat(duration=6.0), design, quality="draft", width=None, gpu=False)
    assert k1 != k2


def test_beat_key_changes_with_design():
    beat = make_ir_beat()
    k1 = cache.beat_key(beat, make_design(1920, 1080), quality="draft", width=None, gpu=False)
    k2 = cache.beat_key(beat, make_design(1280, 720), quality="draft", width=None, gpu=False)
    assert k1 != k2


def test_beat_key_changes_with_quality():
    beat, design = make_ir_beat(), make_design()
    k1 = cache.beat_key(beat, design, quality="draft", width=None, gpu=False)
    k2 = cache.beat_key(beat, design, quality="upload", width=None, gpu=False)
    assert k1 != k2


def test_beat_key_changes_with_width():
    beat, design = make_ir_beat(), make_design()
    k1 = cache.beat_key(beat, design, quality="draft", width=None, gpu=False)
    k2 = cache.beat_key(beat, design, quality="draft", width=960, gpu=False)
    assert k1 != k2


def test_beat_key_changes_with_gpu():
    beat, design = make_ir_beat(), make_design()
    k1 = cache.beat_key(beat, design, quality="draft", width=None, gpu=False)
    k2 = cache.beat_key(beat, design, quality="draft", width=None, gpu=True)
    assert k1 != k2


def test_beat_key_changes_with_asset_mtime(tmp_path):
    audio = tmp_path / "b01.wav"
    _write(audio, b"v1")
    beat = make_ir_beat(audio=str(audio))
    design = make_design()
    k1 = cache.beat_key(beat, design, quality="draft", width=None, gpu=False)

    time.sleep(0.01)
    audio.write_bytes(b"v2-longer-content")
    k2 = cache.beat_key(beat, design, quality="draft", width=None, gpu=False)
    assert k1 != k2


def test_beat_key_missing_asset_differs_from_present(tmp_path):
    missing_path = str(tmp_path / "does_not_exist.wav")
    beat_missing = make_ir_beat(audio=missing_path)
    present_path = tmp_path / "present.wav"
    _write(present_path)
    beat_present = make_ir_beat(audio=str(present_path))
    design = make_design()
    k_missing = cache.beat_key(beat_missing, design, quality="draft", width=None, gpu=False)
    k_present = cache.beat_key(beat_present, design, quality="draft", width=None, gpu=False)
    assert k_missing != k_present


def test_asset_identity_missing_vs_present(tmp_path):
    missing = str(tmp_path / "nope.bin")
    assert cache._asset_identity(missing) == "missing"
    present = tmp_path / "here.bin"
    _write(present, b"data")
    ident = cache._asset_identity(str(present))
    assert ident != "missing"
    assert ":" in ident


def test_walk_asset_paths_covers_audio_words_segments_sfx():
    beat = make_ir_beat(
        audio="a.wav",
        words_path="w.json",
        segments=[
            IRSegment(kind="image", src="seg1.png", offset=0.0, t0=0.0, t1=1.0),
            IRSegment(kind="video", src="seg2.mp4", offset=0.0, t0=1.0, t1=2.0),
        ],
        sfx=[IRSfx(src="sfx1.wav", t=0.5)],
    )
    assert cache._walk_asset_paths(beat) == ["a.wav", "w.json", "seg1.png", "seg2.mp4", "sfx1.wav"]


def test_walk_asset_paths_includes_overlay_asset_paths():
    # C1: raster-input files an overlay reads (e.g. a Plate's bg_image) must be
    # walked so an on-disk edit of that file changes the beat key.
    beat = make_ir_beat(
        audio="a.wav", words_path="w.json", segments=[],
        overlays=[
            IROverlayItem(chunk_index=0, z=0, t0=0.0, t1=1.0,
                          asset_paths=["plate_bg1.png"]),
            IROverlayItem(chunk_index=1, z=1, t0=1.0, t1=2.0,
                          asset_paths=["plate_bg2.png"]),
        ],
    )
    walked = cache._walk_asset_paths(beat)
    assert "plate_bg1.png" in walked and "plate_bg2.png" in walked


# ─── C1: overlay content_hash + overlay asset identity feed the key ────────

def test_beat_key_changes_with_overlay_content_hash():
    """C1 pin: two beats identical except an overlay's content_hash yield
    different keys — content_hash rides inside beat.model_dump_json(), so
    editing rasterized content (text/style/decorations) invalidates the key
    even though timing is unchanged."""
    design = make_design()
    beat_a = make_ir_beat(overlays=[
        IROverlayItem(chunk_index=0, z=0, t0=0.0, t1=5.0, content_hash="1111aaaa2222bbbb")])
    beat_b = make_ir_beat(overlays=[
        IROverlayItem(chunk_index=0, z=0, t0=0.0, t1=5.0, content_hash="9999cccc8888dddd")])
    k1 = cache.beat_key(beat_a, design, quality="draft", width=None, gpu=False)
    k2 = cache.beat_key(beat_b, design, quality="draft", width=None, gpu=False)
    assert k1 != k2


def test_beat_key_changes_with_overlay_asset_mtime(tmp_path):
    """C1 pin: bumping an overlay's raster-input file (bg_image) mtime — same
    IR, same content_hash — changes the key via _walk_asset_paths(ov.asset_paths)."""
    bg = tmp_path / "plate_bg.png"
    _write(bg, b"v1")
    beat = make_ir_beat(overlays=[
        IROverlayItem(chunk_index=0, z=0, t0=0.0, t1=5.0,
                      content_hash="deadbeefdeadbeef", asset_paths=[str(bg)])])
    design = make_design()
    k1 = cache.beat_key(beat, design, quality="draft", width=None, gpu=False)

    time.sleep(0.01)
    bg.write_bytes(b"v2-longer-content")
    k2 = cache.beat_key(beat, design, quality="draft", width=None, gpu=False)
    assert k1 != k2


def test_c1_editing_plate_text_changes_beat_key(tmp_path):
    """THE C1 regression pin (end-to-end): compile the same edit twice with
    ONLY Plate.text changed (timing identical) -> different beat_key. Before the
    fix the IRBeat carried no chunk content, so the key was identical and a
    stale render was served."""
    from dlstudio.compile import build_timeline
    from dlstudio.ir import AssetProbe
    from dlstudio.model import Beat, Chunk, Edit, Plate

    wp = tmp_path / "w.json"
    wp.write_text(json.dumps({"words": [{"word": "a", "start": 0.0, "end": 0.4}]}),
                  encoding="utf-8")
    design = make_design()
    probes = {
        "vo.wav": AssetProbe(path="vo.wav", kind="audio", exists=True, duration=4.0),
        "fonts/main.ttf": AssetProbe(path="fonts/main.ttf", kind="font", exists=True),
    }

    def _key(text: str) -> str:
        beat = Beat(audio="vo.wav", words=str(wp),
                    chunks=[Chunk(words=(0, 0), content=Plate(text=text))])
        edit = Edit(name="e", design=design, beats={"b1": beat},
                    order=["b1"], output="o.mp4")
        tl = build_timeline(edit, probe=False, probes=probes)
        return cache.beat_key(tl.beats[0], tl.design, quality="draft", width=None, gpu=False)

    assert _key("HELLO") != _key("GOODBYE")


# ─── get/put roundtrip ──────────────────────────────────────────────────

def test_put_get_roundtrip(tmp_path):
    rendered = tmp_path / "rendered.mp4"
    _write(rendered, b"fake-mp4-bytes")
    cache.put("somekey", rendered)

    out = tmp_path / "out" / "beat.mp4"
    assert cache.get("somekey", out) is True
    assert out.read_bytes() == b"fake-mp4-bytes"


def test_get_miss_returns_false(tmp_path):
    out = tmp_path / "out.mp4"
    assert cache.get("no-such-key", out) is False
    assert not out.exists()


def test_has_reflects_put(tmp_path):
    rendered = tmp_path / "rendered.mp4"
    _write(rendered)
    assert cache.has("k1") is False
    cache.put("k1", rendered)
    assert cache.has("k1") is True


# ─── atomicity ──────────────────────────────────────────────────────────

def test_put_leaves_no_tmp_file(tmp_path):
    rendered = tmp_path / "rendered.mp4"
    _write(rendered)
    cache.put("atomickey", rendered)
    assert list(cache.CACHE_DIR.glob("*.tmp-*")) == []
    assert (cache.CACHE_DIR / "atomickey.mp4").exists()


def test_put_cleans_up_tmp_on_copy_failure(tmp_path, monkeypatch):
    rendered = tmp_path / "rendered.mp4"
    _write(rendered)

    def boom(src, dst):
        Path(dst).write_bytes(b"partial")  # tmp file gets created...
        raise OSError("disk full (simulated)")  # ...then the copy fails

    monkeypatch.setattr(cache.shutil, "copyfile", boom)
    with pytest.raises(OSError):
        cache.put("failkey", rendered)

    assert not (cache.CACHE_DIR / "failkey.mp4").exists()
    assert list(cache.CACHE_DIR.glob("*.tmp-*")) == []


def test_put_atomic_visibility_during_slow_copy(tmp_path, monkeypatch):
    """The target <key>.mp4 must only ever be observed fully-formed or
    absent -- never a partially-written file mid-publish."""
    rendered = tmp_path / "rendered.mp4"
    payload = b"X" * 2_000_000
    _write(rendered, payload)
    real_copyfile = cache.shutil.copyfile

    def slow_copyfile(src, dst):
        real_copyfile(src, dst)
        time.sleep(0.15)  # hold the fully-written tmp file before os.replace

    monkeypatch.setattr(cache.shutil, "copyfile", slow_copyfile)

    observed_sizes = []
    stop = threading.Event()
    target = cache.CACHE_DIR / "slowkey.mp4"

    def poll_target():
        while not stop.is_set():
            if target.exists():
                try:
                    observed_sizes.append(target.stat().st_size)
                except OSError:
                    pass
            time.sleep(0.01)

    poller = threading.Thread(target=poll_target)
    poller.start()
    cache.put("slowkey", rendered)
    stop.set()
    poller.join()

    assert all(size == len(payload) for size in observed_sizes)


def test_concurrent_put_same_key_different_workers(tmp_path, monkeypatch):
    """Simulates two concurrent `-j N` workers (distinct pids) racing
    os.replace() onto the same cache key: the result must be one of the
    two complete payloads, never a torn mixture, and no tmp files left."""
    content_a = b"A" * 300_000
    content_b = b"B" * 300_000
    src_a, src_b = tmp_path / "a.mp4", tmp_path / "b.mp4"
    src_a.write_bytes(content_a)
    src_b.write_bytes(content_b)

    pid_counter = itertools.count(10_000)
    pid_lock = threading.Lock()

    def fake_getpid():
        with pid_lock:
            return next(pid_counter)

    monkeypatch.setattr(cache.os, "getpid", fake_getpid)

    barrier = threading.Barrier(2)

    def worker(src):
        barrier.wait()
        cache.put("racekey", src)

    threads = [threading.Thread(target=worker, args=(s,)) for s in (src_a, src_b)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()

    final = (cache.CACHE_DIR / "racekey.mp4").read_bytes()
    assert final in (content_a, content_b)
    assert list(cache.CACHE_DIR.glob("*.tmp-*")) == []


# ─── CACHE_DIR override (env var + direct monkeypatch) ─────────────────

def test_cache_dir_env_var_override(tmp_path, monkeypatch):
    override_dir = tmp_path / "env-cache"
    monkeypatch.setenv(cache.CACHE_DIR_ENV_VAR, str(override_dir))
    rendered = tmp_path / "rendered.mp4"
    _write(rendered)
    cache.put("envkey", rendered)
    assert (override_dir / "envkey.mp4").exists()
    # CACHE_DIR itself (monkeypatched to a *different* tmp dir by the
    # autouse fixture) must not have received the file.
    assert not (cache.CACHE_DIR / "envkey.mp4").exists()


# ─── info() / prune() ──────────────────────────────────────────────────

def test_info_empty():
    i = cache.info()
    assert i.entries == 0
    assert i.total_bytes == 0
    assert i.oldest_mtime is None
    assert i.newest_mtime is None


def test_info_counts_entries_and_bytes(tmp_path):
    for i in range(3):
        rendered = tmp_path / f"r{i}.mp4"
        _write(rendered, b"x" * (100 * (i + 1)))
        cache.put(f"key{i}", rendered)
    result = cache.info()
    assert result.entries == 3
    assert result.total_bytes == 100 + 200 + 300


def test_prune_removes_old_entries_only(tmp_path):
    old = tmp_path / "old.mp4"
    new = tmp_path / "new.mp4"
    _write(old)
    _write(new)
    cache.put("oldkey", old)
    cache.put("newkey", new)

    old_path = cache.CACHE_DIR / "oldkey.mp4"
    ancient = time.time() - 30 * 86400
    os.utime(old_path, (ancient, ancient))

    removed = cache.prune(older_than_days=10)
    assert removed == 1
    assert not old_path.exists()
    assert (cache.CACHE_DIR / "newkey.mp4").exists()


def test_prune_rejects_negative_days():
    with pytest.raises(ValueError):
        cache.prune(-1)


def test_prune_on_missing_cache_dir_is_noop(tmp_path):
    assert cache.prune(1) == 0


# ─── engine hash ────────────────────────────────────────────────────────

def test_engine_hash_deterministic_and_memoized():
    cache._reset_engine_hash_cache()
    h1 = cache._engine_hash()
    h2 = cache._engine_hash()
    assert h1 == h2
    assert len(h1) == 40


def test_engine_hash_reflects_package_files():
    """Sanity check that the hash is derived from real package files, not
    a hardcoded/empty value (guards against the v1 _ENGINE_FILES class of
    bug where a file is silently missing from the hash input)."""
    import dlstudio

    pkg_dir = Path(dlstudio.__file__).resolve().parent
    assert any(pkg_dir.rglob("*.py"))
    cache._reset_engine_hash_cache()
    assert cache._engine_hash() != ""
