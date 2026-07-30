from __future__ import annotations

import hashlib
import json
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from threading import Barrier, Lock
from time import sleep

import pytest

from dlstudio.foundation.api import BlobRef
from dlstudio.rendering.api import (
    ExecutionFingerprint,
    PresentationCacheLimits,
    extract_presentation_frame,
    extract_presentation_waveform,
)


class _Resolver:
    def __init__(self, source: Path, artifact: BlobRef) -> None:
        self.source = source
        self.artifact = artifact
        self.verifications = 0

    def path_for(self, ref: BlobRef) -> Path:
        assert ref == self.artifact
        return self.source

    def verify(self, ref: BlobRef) -> None:
        assert ref == self.artifact
        self.verifications += 1
        assert self.source.read_bytes() == b"exact artifact bytes"


def _fixture(tmp_path: Path) -> tuple[BlobRef, _Resolver]:
    source = tmp_path / "artifact.mp4"
    raw = b"exact artifact bytes"
    source.write_bytes(raw)
    artifact = BlobRef(hashlib.sha256(raw).hexdigest(), len(raw))
    return artifact, _Resolver(source, artifact)


def _fingerprint(source_hash: str = "1" * 64) -> ExecutionFingerprint:
    return ExecutionFingerprint(
        ffmpeg="ffmpeg-test",
        ffmpeg_version="ffmpeg test",
        renderer_source_sha256=source_hash,
        ffmpeg_build_sha256="2" * 64,
        ffmpeg_binary_sha256="3" * 64,
        runtime="test-runtime",
    )


def _jpeg(frame: int) -> bytes:
    return b"\xff\xd8" + frame.to_bytes(4, "big") + b"\xff\xd9"


def test_frame_evidence_cache_hit_does_not_launch_ffmpeg_and_key_is_exact(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, resolver = _fixture(tmp_path)
    launches: list[tuple[str, ...]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        assert check
        assert not capture_output
        launches.append(tuple(command))
        Path(command[-1]).write_bytes(_jpeg(12))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    cache_root = tmp_path / "presentation"
    request = {
        "frame": 12,
        "fps_num": 30,
        "fps_den": 1,
        "source_width": 1920,
        "source_height": 1080,
        "width": 320,
        "crop_milli": None,
        "cache_root": cache_root,
    }

    first = extract_presentation_frame(
        artifact,
        resolver,
        fingerprint=_fingerprint(),
        **request,
    )
    second = extract_presentation_frame(
        artifact,
        resolver,
        fingerprint=_fingerprint(),
        **request,
    )
    changed_tool = extract_presentation_frame(
        artifact,
        resolver,
        fingerprint=_fingerprint("4" * 64),
        **request,
    )

    assert not first.cache_hit
    assert second.cache_hit
    assert not changed_tool.cache_hit
    assert first.cache_key == second.cache_key
    assert changed_tool.cache_key != first.cache_key
    assert first.blob == second.blob
    assert first.path.read_bytes() == _jpeg(12)
    assert first.media_type == "image/jpeg"
    assert len(launches) == 2
    assert resolver.verifications == 3


def test_frame_evidence_uses_exact_normalized_crop_pixels(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, resolver = _fixture(tmp_path)
    commands: list[tuple[str, ...]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        assert check
        commands.append(tuple(command))
        Path(command[-1]).write_bytes(_jpeg(3))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = extract_presentation_frame(
        artifact,
        resolver,
        frame=3,
        fps_num=24,
        fps_den=1,
        source_width=101,
        source_height=203,
        width=128,
        crop_milli=(100, 200, 300, 150),
        cache_root=tmp_path / "presentation",
        fingerprint=_fingerprint(),
    )

    assert not result.cache_hit
    filter_graph = commands[0][commands[0].index("-vf") + 1]
    assert filter_graph.startswith("crop=31:32:10:40,")
    assert "scale=128:-2" in filter_graph


def test_waveform_is_bounded_cached_and_recovers_corrupt_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, resolver = _fixture(tmp_path)
    launches = 0

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal launches
        assert check
        assert not capture_output
        launches += 1
        values = tuple(
            24_000 if index % 7 == 0 else -8_000
            for index in range(4096)
        )
        Path(command[-1]).write_bytes(
            struct.pack(f"<{len(values)}h", *values)
        )
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    cache_root = tmp_path / "presentation"

    first = extract_presentation_waveform(
        artifact,
        resolver,
        duration_ns=2_000_000_000,
        sample_count=256,
        cache_root=cache_root,
        fingerprint=_fingerprint(),
    )
    second = extract_presentation_waveform(
        artifact,
        resolver,
        duration_ns=2_000_000_000,
        sample_count=256,
        cache_root=cache_root,
        fingerprint=_fingerprint(),
    )
    first.path.write_bytes(b"{not valid json")
    rebuilt = extract_presentation_waveform(
        artifact,
        resolver,
        duration_ns=2_000_000_000,
        sample_count=256,
        cache_root=cache_root,
        fingerprint=_fingerprint(),
    )

    assert len(first.samples) == 256
    assert all(0 <= sample <= 1000 for sample in first.samples)
    assert max(first.samples) > 700
    assert second.cache_hit
    assert not rebuilt.cache_hit
    assert rebuilt.samples == first.samples
    assert launches == 2


def test_presentation_cache_coalesces_same_key_and_limits_ffmpeg_concurrency(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, resolver = _fixture(tmp_path)
    active = 0
    peak = 0
    launches = 0
    counter_lock = Lock()

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal active, peak, launches
        with counter_lock:
            launches += 1
            active += 1
            peak = max(peak, active)
        try:
            sleep(0.04)
            frame = int(Path(command[-1]).stem.split(".")[-2], 16) % 1000
            Path(command[-1]).write_bytes(_jpeg(frame))
            return subprocess.CompletedProcess(command, 0)
        finally:
            with counter_lock:
                active -= 1

    monkeypatch.setattr(subprocess, "run", fake_run)
    cache_root = tmp_path / "presentation"
    limits = PresentationCacheLimits(
        max_entries=16,
        max_bytes=1024 * 1024,
        max_concurrency=2,
    )
    start = Barrier(4)

    def same_request(_index: int):
        start.wait()
        return extract_presentation_frame(
            artifact,
            resolver,
            frame=7,
            fps_num=30,
            fps_den=1,
            source_width=1920,
            source_height=1080,
            width=160,
            crop_milli=None,
            cache_root=cache_root,
            fingerprint=_fingerprint(),
            limits=limits,
        )

    with ThreadPoolExecutor(max_workers=4) as pool:
        same_results = tuple(pool.map(same_request, range(4)))

    assert launches == 1
    assert sum(result.cache_hit for result in same_results) == 3

    with ThreadPoolExecutor(max_workers=5) as pool:
        different_results = tuple(
            pool.map(
                lambda frame: extract_presentation_frame(
                    artifact,
                    resolver,
                    frame=frame,
                    fps_num=30,
                    fps_den=1,
                    source_width=1920,
                    source_height=1080,
                    width=160,
                    crop_milli=None,
                    cache_root=cache_root,
                    fingerprint=_fingerprint(),
                    limits=limits,
                ),
                range(8, 13),
            )
        )

    assert all(not result.cache_hit for result in different_results)
    assert peak <= 2


def test_presentation_cache_evicts_deterministic_least_recent_entry(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, resolver = _fixture(tmp_path)
    launches: list[int] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        capture_output: bool = False,
    ) -> subprocess.CompletedProcess[bytes]:
        frame = len(launches)
        launches.append(frame)
        Path(command[-1]).write_bytes(_jpeg(frame))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    cache_root = tmp_path / "presentation"
    limits = PresentationCacheLimits(
        max_entries=2,
        max_bytes=1024,
        max_concurrency=1,
    )

    def extract(frame: int):
        return extract_presentation_frame(
            artifact,
            resolver,
            frame=frame,
            fps_num=30,
            fps_den=1,
            source_width=1920,
            source_height=1080,
            width=160,
            crop_milli=None,
            cache_root=cache_root,
            fingerprint=_fingerprint(),
            limits=limits,
        )

    first = extract(1)
    second = extract(2)
    assert extract(1).cache_hit
    third = extract(3)

    lru = json.loads((cache_root / "lru.json").read_text(encoding="utf-8"))
    assert len(lru["entries"]) == 2
    assert first.cache_key in lru["entries"]
    assert third.cache_key in lru["entries"]
    assert second.cache_key not in lru["entries"]
    assert not extract(2).cache_hit
