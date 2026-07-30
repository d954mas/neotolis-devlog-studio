from __future__ import annotations

import hashlib
import json
import struct
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from pathlib import Path
from threading import Barrier, Lock
from time import sleep

import pytest

from dlstudio.foundation.api import BlobRef
from dlstudio.rendering.api import (
    ExecutionFingerprint,
    PresentationCacheLimits,
    PresentationFingerprint,
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
        raw = self.source.read_bytes()
        assert BlobRef(hashlib.sha256(raw).hexdigest(), len(raw)) == ref


def _fixture(tmp_path: Path) -> tuple[BlobRef, _Resolver]:
    source = tmp_path / "artifact.mp4"
    raw = b"exact artifact bytes"
    source.write_bytes(raw)
    artifact = BlobRef(hashlib.sha256(raw).hexdigest(), len(raw))
    return artifact, _Resolver(source, artifact)


def _execution_fingerprint() -> ExecutionFingerprint:
    return ExecutionFingerprint(
        ffmpeg="ffmpeg-test",
        ffmpeg_version="ffmpeg test",
        renderer_source_sha256="1" * 64,
        ffmpeg_build_sha256="2" * 64,
        ffmpeg_binary_sha256="3" * 64,
        runtime="test-runtime",
    )


def _fingerprint(source_hash: str = "4" * 64) -> PresentationFingerprint:
    return PresentationFingerprint.from_execution(
        _execution_fingerprint(),
        presentation_source_sha256=source_hash,
    )


def _jpeg(frame: int) -> bytes:
    app_payload = frame.to_bytes(4, "big") + b"\0\0"
    app = b"\xff\xe1" + (len(app_payload) + 2).to_bytes(2, "big") + app_payload
    sof = (
        b"\xff\xc0\x00\x0b\x08"
        b"\x00\x01\x00\x01"
        b"\x01\x01\x11\x00"
    )
    scan = b"\xff\xda\x00\x08\x01\x01\x00\x00\x3f\x00\x00"
    return b"\xff\xd8" + app + sof + scan + b"\xff\xd9"


def _cached_path(cache_root: Path, cache_key: str) -> Path:
    manifest = json.loads(
        (cache_root / "manifests" / f"{cache_key}.json").read_text(
            encoding="utf-8"
        )
    )
    blob = manifest["blob"]
    return (
        cache_root
        / "objects"
        / f"{blob['sha256']}.{manifest['suffix']}"
    )


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
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        assert check
        assert not capture_output
        assert timeout == 30
        launches.append(tuple(command))
        Path(command[-1]).write_bytes(_jpeg(12))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    cache_root = tmp_path / "presentation"
    request = {
        "frame": 12,
        "duration_ns": 2_000_000_000,
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
        fingerprint=_fingerprint("5" * 64),
        **request,
    )

    assert not first.cache_hit
    assert second.cache_hit
    assert not changed_tool.cache_hit
    assert first.cache_key == second.cache_key
    assert changed_tool.cache_key != first.cache_key
    assert first.blob == second.blob
    assert first.content == _jpeg(12)
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
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        assert check
        assert timeout == 30
        commands.append(tuple(command))
        Path(command[-1]).write_bytes(_jpeg(3))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    result = extract_presentation_frame(
        artifact,
        resolver,
        frame=3,
        duration_ns=2_000_000_000,
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
    assert filter_graph.startswith("crop=31:32:10:40:exact=1,")
    assert "scale=128:-2" in filter_graph


def test_frame_evidence_uses_integer_ceil_for_large_exact_clock(
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
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal launches
        assert check
        assert not capture_output
        assert timeout == 30
        launches += 1
        Path(command[-1]).write_bytes(_jpeg(134_217_728))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    request = {
        "duration_ns": 4_473_924_266_666_667,
        "fps_num": 30,
        "fps_den": 1,
        "source_width": 1920,
        "source_height": 1080,
        "width": 160,
        "crop_milli": None,
        "cache_root": tmp_path / "presentation",
        "fingerprint": _fingerprint(),
    }

    result = extract_presentation_frame(
        artifact,
        resolver,
        frame=134_217_728,
        **request,
    )

    assert result.content == _jpeg(134_217_728)
    assert launches == 1
    with pytest.raises(ValueError, match="outside the artifact"):
        extract_presentation_frame(
            artifact,
            resolver,
            frame=134_217_729,
            **request,
        )


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
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal launches
        assert check
        assert not capture_output
        assert timeout == 30
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
    _cached_path(cache_root, first.cache_key).write_bytes(b"{not valid json")
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
    assert first.has_audio
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
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal active, peak, launches
        assert timeout == 30
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
            duration_ns=2_000_000_000,
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
                    duration_ns=2_000_000_000,
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
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        assert timeout == 30
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
            duration_ns=2_000_000_000,
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


def test_frame_seek_is_fast_input_seek_with_floor_rational_timestamp(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, resolver = _fixture(tmp_path)
    commands: list[tuple[str, ...]] = []

    def fake_run(
        command: list[str],
        *,
        check: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        commands.append(tuple(command))
        Path(command[-1]).write_bytes(_jpeg(1001))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    extract_presentation_frame(
        artifact,
        resolver,
        frame=1001,
        duration_ns=40_000_000_000,
        fps_num=30_000,
        fps_den=1001,
        source_width=1920,
        source_height=1080,
        width=320,
        crop_milli=None,
        cache_root=tmp_path / "presentation",
        fingerprint=_fingerprint(),
    )

    command = commands[0]
    assert command.index("-ss") < command.index("-i")
    assert command[command.index("-ss") + 1] == "33.400033333"
    assert command[command.index("-map") + 1] == "0:v:0"


def test_presentation_rejects_unbounded_crop_output_before_ffmpeg(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, resolver = _fixture(tmp_path)

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("FFmpeg must not run for an unbounded crop")

    monkeypatch.setattr(subprocess, "run", forbidden)

    with pytest.raises(ValueError, match="output dimensions"):
        extract_presentation_frame(
            artifact,
            resolver,
            frame=0,
            duration_ns=2_000_000_000,
            fps_num=30,
            fps_den=1,
            source_width=1080,
            source_height=1920,
            width=640,
            crop_milli=(0, 0, 1, 1000),
            cache_root=tmp_path / "presentation",
            fingerprint=_fingerprint(),
        )


def test_corrupt_lru_cannot_delete_outside_presentation_cache(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, resolver = _fixture(tmp_path)
    cache_root = tmp_path / "presentation"
    cache_root.mkdir()
    sentinel = tmp_path / "sentinel.jpg"
    sentinel.write_bytes(b"keep me")
    (cache_root / "lru.json").write_text(
        json.dumps(
            {
                "schema": "dlstudio.presentation_lru",
                "version": 1,
                "counter": 1,
                "entries": {
                    "corrupt": {
                        "access": 0,
                        "sha256": "../../sentinel",
                        "size": 7,
                        "suffix": "jpg",
                    }
                },
            }
        ),
        encoding="utf-8",
    )

    def fake_run(
        command: list[str],
        *,
        check: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        Path(command[-1]).write_bytes(_jpeg(0))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    extract_presentation_frame(
        artifact,
        resolver,
        frame=0,
        duration_ns=2_000_000_000,
        fps_num=30,
        fps_den=1,
        source_width=1920,
        source_height=1080,
        width=160,
        crop_milli=None,
        cache_root=cache_root,
        fingerprint=_fingerprint(),
        limits=PresentationCacheLimits(
            max_entries=1,
            max_bytes=1024,
            max_concurrency=1,
        ),
    )

    assert sentinel.read_bytes() == b"keep me"


def test_silent_final_mix_is_distinct_from_missing_waveform(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, resolver = _fixture(tmp_path)

    def fake_run(
        command: list[str],
        *,
        check: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        assert command[command.index("-map") + 1] == "0:a:0"
        Path(command[-1]).write_bytes(b"\0" * 4096)
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    result = extract_presentation_waveform(
        artifact,
        resolver,
        duration_ns=2_000_000_000,
        sample_count=256,
        cache_root=tmp_path / "presentation",
        fingerprint=_fingerprint(),
    )

    assert result.samples == (0,) * 256
    assert not result.has_audio


def test_invalid_jpeg_is_rejected_even_with_soi_and_eoi(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, resolver = _fixture(tmp_path)

    def fake_run(
        command: list[str],
        *,
        check: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        Path(command[-1]).write_bytes(b"\xff\xd8not-an-image\xff\xd9")
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)

    with pytest.raises(RuntimeError, match="invalid JPEG"):
        extract_presentation_frame(
            artifact,
            resolver,
            frame=0,
            duration_ns=2_000_000_000,
            fps_num=30,
            fps_den=1,
            source_width=1920,
            source_height=1080,
            width=160,
            crop_milli=None,
            cache_root=tmp_path / "presentation",
            fingerprint=_fingerprint(),
        )


def test_ffmpeg_timeout_releases_key_and_extraction_slot(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    artifact, resolver = _fixture(tmp_path)
    launches = 0

    def fake_run(
        command: list[str],
        *,
        check: bool,
        timeout: float,
    ) -> subprocess.CompletedProcess[bytes]:
        nonlocal launches
        launches += 1
        if launches == 1:
            raise subprocess.TimeoutExpired(command, timeout)
        Path(command[-1]).write_bytes(_jpeg(0))
        return subprocess.CompletedProcess(command, 0)

    monkeypatch.setattr(subprocess, "run", fake_run)
    request = {
        "frame": 0,
        "duration_ns": 2_000_000_000,
        "fps_num": 30,
        "fps_den": 1,
        "source_width": 1920,
        "source_height": 1080,
        "width": 160,
        "crop_milli": None,
        "cache_root": tmp_path / "presentation",
        "fingerprint": _fingerprint(),
        "limits": PresentationCacheLimits(max_concurrency=1),
    }

    with pytest.raises(subprocess.TimeoutExpired):
        extract_presentation_frame(artifact, resolver, **request)
    recovered = extract_presentation_frame(artifact, resolver, **request)

    assert not recovered.cache_hit
    assert recovered.content == _jpeg(0)
    assert launches == 2


@pytest.mark.slow
def test_fast_seek_matches_slow_unique_frame_oracle(
    tmp_path: Path,
) -> None:
    source = tmp_path / "unique-frames.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=320x180:rate=30000/1001:duration=4",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-g",
            "60",
            "-keyint_min",
            "60",
            "-sc_threshold",
            "0",
            "-pix_fmt",
            "yuv420p",
            str(source),
        ],
        check=True,
        timeout=30,
    )
    raw = source.read_bytes()
    artifact = BlobRef(hashlib.sha256(raw).hexdigest(), len(raw))
    resolver = _Resolver(source, artifact)
    fingerprint = replace(_fingerprint(), ffmpeg="ffmpeg")

    for frame in (0, 1, 59, 60, 100):
        evidence = extract_presentation_frame(
            artifact,
            resolver,
            frame=frame,
            duration_ns=4_000_000_000,
            fps_num=30_000,
            fps_den=1001,
            source_width=320,
            source_height=180,
            width=160,
            crop_milli=None,
            cache_root=tmp_path / "presentation",
            fingerprint=fingerprint,
        )
        oracle = tmp_path / f"oracle-{frame}.jpg"
        subprocess.run(
            [
                "ffmpeg",
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:v:0",
                "-vf",
                f"select=eq(n\\,{frame}),scale=160:-2:flags=lanczos",
                "-frames:v",
                "1",
                "-fps_mode",
                "passthrough",
                "-q:v",
                "3",
                str(oracle),
            ],
            check=True,
            timeout=30,
        )

        assert evidence.content == oracle.read_bytes()
