"""Rebuildable frame and audio evidence derived from exact render artifacts."""

from __future__ import annotations

import hashlib
import json
import math
import os
import struct
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Mapping, Protocol

from dlstudio.foundation.api import BlobRef, canonical_hash


class PresentationResolver(Protocol):
    def path_for(self, ref: BlobRef) -> Path: ...

    def verify(self, ref: BlobRef) -> None: ...


class PresentationToolFingerprint(Protocol):
    ffmpeg: str

    def as_payload(self) -> Mapping[str, object]: ...


@dataclass(frozen=True, slots=True)
class PresentationCacheLimits:
    max_entries: int = 4096
    max_bytes: int = 512 * 1024 * 1024
    max_concurrency: int = 2

    def __post_init__(self) -> None:
        if self.max_entries <= 0:
            raise ValueError("presentation cache entry limit must be positive")
        if self.max_bytes <= 0:
            raise ValueError("presentation cache byte limit must be positive")
        if not 1 <= self.max_concurrency <= 16:
            raise ValueError("presentation extraction concurrency must be 1..16")


@dataclass(frozen=True, slots=True)
class PresentationFileResult:
    blob: BlobRef
    path: Path
    cache_key: str
    cache_hit: bool
    media_type: str


@dataclass(frozen=True, slots=True)
class PresentationWaveformResult:
    blob: BlobRef
    path: Path
    cache_key: str
    cache_hit: bool
    samples: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    cache_key: str
    kind: str
    blob: BlobRef
    suffix: str
    media_type: str
    path: Path


class _FileLease:
    def __init__(self, path: Path, timeout: float = 30.0) -> None:
        self.path = path
        self.timeout = timeout
        self._handle: BinaryIO | None = None

    @staticmethod
    def try_lock(handle: BinaryIO) -> bool:
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            return True
        except (BlockingIOError, OSError):
            return False

    @staticmethod
    def unlock(handle: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    @staticmethod
    def open_lock(path: Path) -> BinaryIO:
        path.parent.mkdir(parents=True, exist_ok=True)
        handle = path.open("a+b")
        if path.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        return handle

    def __enter__(self) -> "_FileLease":
        handle = self.open_lock(self.path)
        deadline = time.monotonic() + self.timeout
        while not self.try_lock(handle):
            if time.monotonic() >= deadline:
                handle.close()
                raise TimeoutError(
                    f"presentation cache lease timeout: {self.path.name}"
                )
            time.sleep(0.01)
            handle.seek(0)
        self._handle = handle
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._handle is not None:
            self._handle.seek(0)
            self.unlock(self._handle)
            self._handle.close()
            self._handle = None


class _ExtractionSlot:
    """Cross-process pool that bounds all distinct-key FFmpeg work."""

    def __init__(
        self,
        cache_root: Path,
        slots: int,
        timeout: float = 30.0,
    ) -> None:
        self.cache_root = cache_root
        self.slots = slots
        self.timeout = timeout
        self._handle: BinaryIO | None = None

    def __enter__(self) -> "_ExtractionSlot":
        deadline = time.monotonic() + self.timeout
        while True:
            for index in range(self.slots):
                handle = _FileLease.open_lock(
                    self.cache_root
                    / "locks"
                    / "extraction"
                    / f"slot-{index}.lock"
                )
                if _FileLease.try_lock(handle):
                    self._handle = handle
                    return self
                handle.close()
            if time.monotonic() >= deadline:
                raise TimeoutError("presentation extraction slot timeout")
            time.sleep(0.01)

    def __exit__(self, *_exc: object) -> None:
        if self._handle is not None:
            self._handle.seek(0)
            _FileLease.unlock(self._handle)
            self._handle.close()
            self._handle = None


def _hash_file(path: Path) -> BlobRef:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return BlobRef(digest.hexdigest(), size)


def _atomic_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    stage = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with stage.open("x", encoding="utf-8", newline="\n") as handle:
            json.dump(
                payload,
                handle,
                sort_keys=True,
                separators=(",", ":"),
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(stage, path)
    finally:
        stage.unlink(missing_ok=True)


def _manifest_path(cache_root: Path, cache_key: str) -> Path:
    return cache_root / "manifests" / f"{cache_key}.json"


def _read_manifest(
    cache_root: Path,
    cache_key: str,
    kind: str,
) -> _CacheEntry | None:
    manifest_path = _manifest_path(cache_root, cache_key)
    if not manifest_path.is_file():
        return None
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
        if (
            payload.get("schema") != "dlstudio.presentation_cache"
            or payload.get("version") != 1
            or payload.get("cache_key") != cache_key
            or payload.get("kind") != kind
        ):
            return None
        blob = BlobRef.from_payload(payload["blob"])
        suffix = str(payload["suffix"])
        if suffix not in {"jpg", "json"}:
            return None
        path = cache_root / "objects" / f"{blob.sha256}.{suffix}"
        if not path.is_file() or _hash_file(path) != blob:
            return None
        return _CacheEntry(
            cache_key=cache_key,
            kind=kind,
            blob=blob,
            suffix=suffix,
            media_type=str(payload["media_type"]),
            path=path,
        )
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None


def _read_lru(cache_root: Path) -> dict[str, object]:
    path = cache_root / "lru.json"
    if path.is_file():
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
            entries = payload["entries"]
            if (
                payload.get("schema") == "dlstudio.presentation_lru"
                and payload.get("version") == 1
                and type(payload.get("counter")) is int
                and isinstance(entries, dict)
            ):
                for key, value in entries.items():
                    if (
                        not isinstance(key, str)
                        or not isinstance(value, dict)
                        or type(value.get("access")) is not int
                        or type(value.get("size")) is not int
                        or not isinstance(value.get("sha256"), str)
                        or value.get("suffix") not in {"jpg", "json"}
                    ):
                        raise ValueError("invalid presentation LRU entry")
                return payload
        except (
            KeyError,
            OSError,
            TypeError,
            ValueError,
            json.JSONDecodeError,
        ):
            pass

    entries: dict[str, dict[str, object]] = {}
    counter = 0
    manifests = cache_root / "manifests"
    if manifests.is_dir():
        for manifest_path in sorted(manifests.glob("*.json")):
            cache_key = manifest_path.stem
            entry = _read_manifest(cache_root, cache_key, "frame")
            if entry is None:
                entry = _read_manifest(cache_root, cache_key, "waveform")
            if entry is None:
                continue
            counter += 1
            entries[cache_key] = {
                "access": counter,
                "sha256": entry.blob.sha256,
                "size": entry.blob.size,
                "suffix": entry.suffix,
            }
    return {
        "schema": "dlstudio.presentation_lru",
        "version": 1,
        "counter": counter,
        "entries": entries,
    }


def _delete_unreferenced_object(
    cache_root: Path,
    sha256: str,
    suffix: str,
    entries: Mapping[str, object],
) -> None:
    referenced = any(
        isinstance(value, dict)
        and value.get("sha256") == sha256
        and value.get("suffix") == suffix
        for value in entries.values()
    )
    if not referenced:
        (cache_root / "objects" / f"{sha256}.{suffix}").unlink(
            missing_ok=True
        )


def _record_access(
    cache_root: Path,
    entry: _CacheEntry,
    limits: PresentationCacheLimits,
) -> None:
    if entry.blob.size > limits.max_bytes:
        raise ValueError("presentation cache entry exceeds its byte limit")
    with _FileLease(cache_root / "locks" / "lru.lock"):
        payload = _read_lru(cache_root)
        entries = payload["entries"]
        assert isinstance(entries, dict)
        counter = int(payload["counter"]) + 1
        entries[entry.cache_key] = {
            "access": counter,
            "sha256": entry.blob.sha256,
            "size": entry.blob.size,
            "suffix": entry.suffix,
        }
        payload["counter"] = counter

        def total_bytes() -> int:
            return sum(
                int(value["size"])
                for value in entries.values()
                if isinstance(value, dict)
            )

        while (
            len(entries) > limits.max_entries
            or total_bytes() > limits.max_bytes
        ):
            evicted_key, evicted = min(
                entries.items(),
                key=lambda item: (int(item[1]["access"]), item[0]),
            )
            del entries[evicted_key]
            _manifest_path(cache_root, evicted_key).unlink(missing_ok=True)
            _delete_unreferenced_object(
                cache_root,
                str(evicted["sha256"]),
                str(evicted["suffix"]),
                entries,
            )
        _atomic_json(cache_root / "lru.json", payload)


def _discard_entry(cache_root: Path, cache_key: str) -> None:
    with _FileLease(cache_root / "locks" / "lru.lock"):
        payload = _read_lru(cache_root)
        entries = payload["entries"]
        assert isinstance(entries, dict)
        removed = entries.pop(cache_key, None)
        _manifest_path(cache_root, cache_key).unlink(missing_ok=True)
        if isinstance(removed, dict):
            _delete_unreferenced_object(
                cache_root,
                str(removed["sha256"]),
                str(removed["suffix"]),
                entries,
            )
        _atomic_json(cache_root / "lru.json", payload)


def _load_entry(
    cache_root: Path,
    cache_key: str,
    kind: str,
    limits: PresentationCacheLimits,
) -> _CacheEntry | None:
    manifest_exists = _manifest_path(cache_root, cache_key).exists()
    entry = _read_manifest(cache_root, cache_key, kind)
    if entry is None:
        if manifest_exists:
            _discard_entry(cache_root, cache_key)
        return None
    _record_access(cache_root, entry, limits)
    return entry


def _publish_entry(
    cache_root: Path,
    cache_key: str,
    kind: str,
    media_type: str,
    suffix: str,
    stage: Path,
    limits: PresentationCacheLimits,
) -> _CacheEntry:
    blob = _hash_file(stage)
    if blob.size == 0:
        raise RuntimeError("presentation extraction produced an empty result")
    objects = cache_root / "objects"
    objects.mkdir(parents=True, exist_ok=True)
    target = objects / f"{blob.sha256}.{suffix}"
    if target.is_file():
        if _hash_file(target) != blob:
            target.unlink()
            os.replace(stage, target)
        else:
            stage.unlink()
    else:
        os.replace(stage, target)
    entry = _CacheEntry(
        cache_key=cache_key,
        kind=kind,
        blob=blob,
        suffix=suffix,
        media_type=media_type,
        path=target,
    )
    _atomic_json(
        _manifest_path(cache_root, cache_key),
        {
            "schema": "dlstudio.presentation_cache",
            "version": 1,
            "cache_key": cache_key,
            "kind": kind,
            "blob": blob.as_payload(),
            "suffix": suffix,
            "media_type": media_type,
        },
    )
    _record_access(cache_root, entry, limits)
    return entry


def _verify_source(
    resolver: PresentationResolver,
    artifact: BlobRef,
) -> Path:
    resolver.verify(artifact)
    source = resolver.path_for(artifact)
    if not source.is_file() or source.stat().st_size != artifact.size:
        raise ValueError("presentation source is missing or changed")
    return source


def _frame_count(duration_ns: int, fps_num: int, fps_den: int) -> int:
    if duration_ns <= 0 or fps_num <= 0 or fps_den <= 0:
        raise ValueError("presentation frame clock is invalid")
    return max(
        1,
        math.ceil(duration_ns * fps_num / (1_000_000_000 * fps_den)),
    )


def _validate_crop(
    crop_milli: tuple[int, int, int, int] | None,
    source_width: int,
    source_height: int,
) -> tuple[int, int, int, int] | None:
    if source_width <= 0 or source_height <= 0:
        raise ValueError("presentation source dimensions must be positive")
    if crop_milli is None:
        return None
    if len(crop_milli) != 4:
        raise ValueError("presentation crop must have four coordinates")
    x, y, width, height = crop_milli
    if (
        min(x, y) < 0
        or width <= 0
        or height <= 0
        or x + width > 1000
        or y + height > 1000
    ):
        raise ValueError("presentation crop exceeds the normalized frame")
    left = source_width * x // 1000
    top = source_height * y // 1000
    right = math.ceil(source_width * (x + width) / 1000)
    bottom = math.ceil(source_height * (y + height) / 1000)
    return left, top, max(1, right - left), max(1, bottom - top)


def _frame_cache_key(
    artifact: BlobRef,
    *,
    frame: int,
    fps_num: int,
    fps_den: int,
    source_width: int,
    source_height: int,
    width: int,
    crop_milli: tuple[int, int, int, int] | None,
    fingerprint: PresentationToolFingerprint,
) -> str:
    return canonical_hash(
        {
            "kind": "frame",
            "artifact": artifact.as_payload(),
            "frame": frame,
            "fps_num": fps_num,
            "fps_den": fps_den,
            "source_width": source_width,
            "source_height": source_height,
            "width": width,
            "crop_milli": crop_milli,
            "tool": dict(fingerprint.as_payload()),
            "contract": "ffmpeg-frame-jpeg-v1",
        },
        domain="dlstudio.presentation_cache",
        version=1,
    )


def extract_presentation_frame(
    artifact: BlobRef,
    resolver: PresentationResolver,
    *,
    frame: int,
    fps_num: int,
    fps_den: int,
    source_width: int,
    source_height: int,
    width: int,
    crop_milli: tuple[int, int, int, int] | None,
    cache_root: Path,
    fingerprint: PresentationToolFingerprint,
    limits: PresentationCacheLimits = PresentationCacheLimits(),
) -> PresentationFileResult:
    if not 64 <= width <= 640:
        raise ValueError("presentation frame width must be 64..640")
    if frame < 0 or fps_num <= 0 or fps_den <= 0:
        raise ValueError("presentation frame is invalid")
    crop_pixels = _validate_crop(crop_milli, source_width, source_height)
    source = _verify_source(resolver, artifact)
    cache_root = cache_root.resolve()
    cache_key = _frame_cache_key(
        artifact,
        frame=frame,
        fps_num=fps_num,
        fps_den=fps_den,
        source_width=source_width,
        source_height=source_height,
        width=width,
        crop_milli=crop_milli,
        fingerprint=fingerprint,
    )
    with _FileLease(cache_root / "locks" / "keys" / f"{cache_key}.lock"):
        cached = _load_entry(cache_root, cache_key, "frame", limits)
        if cached is not None:
            return PresentationFileResult(
                cached.blob,
                cached.path,
                cache_key,
                True,
                cached.media_type,
            )
        staging = cache_root / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        fd, raw_stage = tempfile.mkstemp(
            prefix=f".{cache_key}.",
            suffix=".jpg",
            dir=staging,
        )
        os.close(fd)
        stage = Path(raw_stage)
        try:
            filters: list[str] = []
            if crop_pixels is not None:
                left, top, crop_width, crop_height = crop_pixels
                filters.append(
                    f"crop={crop_width}:{crop_height}:{left}:{top}"
                )
            filters.append(f"scale={width}:-2:flags=lanczos")
            seconds = frame * fps_den / fps_num
            command = [
                fingerprint.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-ss",
                f"{seconds:.9f}",
                "-frames:v",
                "1",
                "-vf",
                ",".join(filters),
                "-q:v",
                "3",
                str(stage),
            ]
            with _ExtractionSlot(
                cache_root,
                limits.max_concurrency,
            ):
                subprocess.run(command, check=True)
            raw = stage.read_bytes()
            if (
                len(raw) < 4
                or not raw.startswith(b"\xff\xd8")
                or not raw.endswith(b"\xff\xd9")
            ):
                raise RuntimeError("FFmpeg produced invalid JPEG evidence")
            entry = _publish_entry(
                cache_root,
                cache_key,
                "frame",
                "image/jpeg",
                "jpg",
                stage,
                limits,
            )
            return PresentationFileResult(
                entry.blob,
                entry.path,
                cache_key,
                False,
                entry.media_type,
            )
        finally:
            stage.unlink(missing_ok=True)


def _waveform_cache_key(
    artifact: BlobRef,
    *,
    duration_ns: int,
    sample_count: int,
    fingerprint: PresentationToolFingerprint,
) -> str:
    return canonical_hash(
        {
            "kind": "waveform",
            "artifact": artifact.as_payload(),
            "duration_ns": duration_ns,
            "sample_count": sample_count,
            "tool": dict(fingerprint.as_payload()),
            "contract": "ffmpeg-final-mix-peak-v1",
        },
        domain="dlstudio.presentation_cache",
        version=1,
    )


def _waveform_payload(samples: tuple[int, ...]) -> bytes:
    return json.dumps(
        {
            "schema": "dlstudio.presentation_waveform",
            "version": 1,
            "samples": list(samples),
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _read_waveform(
    entry: _CacheEntry,
    sample_count: int,
) -> tuple[int, ...] | None:
    try:
        payload = json.loads(entry.path.read_text(encoding="utf-8"))
        values = payload["samples"]
        if (
            payload.get("schema") != "dlstudio.presentation_waveform"
            or payload.get("version") != 1
            or not isinstance(values, list)
            or len(values) != sample_count
            or any(
                type(value) is not int or not 0 <= value <= 1000
                for value in values
            )
        ):
            return None
        return tuple(values)
    except (
        KeyError,
        OSError,
        TypeError,
        ValueError,
        json.JSONDecodeError,
    ):
        return None


def _envelope(raw: bytes, sample_count: int) -> tuple[int, ...]:
    usable = len(raw) - (len(raw) % 2)
    values = tuple(
        value[0]
        for value in struct.iter_unpack("<h", raw[:usable])
    )
    if not values:
        return (0,) * sample_count
    peaks = [0] * sample_count
    total = len(values)
    for index, value in enumerate(values):
        bucket = min(sample_count - 1, index * sample_count // total)
        amplitude = min(1000, round(abs(value) * 1000 / 32767))
        if amplitude > peaks[bucket]:
            peaks[bucket] = amplitude
    return tuple(peaks)


def extract_presentation_waveform(
    artifact: BlobRef,
    resolver: PresentationResolver,
    *,
    duration_ns: int,
    sample_count: int,
    cache_root: Path,
    fingerprint: PresentationToolFingerprint,
    limits: PresentationCacheLimits = PresentationCacheLimits(),
) -> PresentationWaveformResult:
    if duration_ns <= 0:
        raise ValueError("presentation waveform duration must be positive")
    if not 256 <= sample_count <= 8192:
        raise ValueError("presentation waveform samples must be 256..8192")
    source = _verify_source(resolver, artifact)
    cache_root = cache_root.resolve()
    cache_key = _waveform_cache_key(
        artifact,
        duration_ns=duration_ns,
        sample_count=sample_count,
        fingerprint=fingerprint,
    )
    with _FileLease(cache_root / "locks" / "keys" / f"{cache_key}.lock"):
        cached = _load_entry(cache_root, cache_key, "waveform", limits)
        if cached is not None:
            samples = _read_waveform(cached, sample_count)
            if samples is not None:
                return PresentationWaveformResult(
                    cached.blob,
                    cached.path,
                    cache_key,
                    True,
                    samples,
                )
            _discard_entry(cache_root, cache_key)

        staging = cache_root / "staging"
        staging.mkdir(parents=True, exist_ok=True)
        fd, raw_pcm = tempfile.mkstemp(
            prefix=f".{cache_key}.",
            suffix=".pcm",
            dir=staging,
        )
        os.close(fd)
        pcm = Path(raw_pcm)
        json_stage = staging / f".{cache_key}.{uuid.uuid4().hex}.json"
        try:
            duration_seconds = duration_ns / 1_000_000_000
            sample_rate = max(
                256,
                min(
                    8000,
                    math.ceil(sample_count * 16 / duration_seconds),
                ),
            )
            command = [
                fingerprint.ffmpeg,
                "-hide_banner",
                "-loglevel",
                "error",
                "-y",
                "-i",
                str(source),
                "-map",
                "0:a:0?",
                "-vn",
                "-ac",
                "1",
                "-ar",
                str(sample_rate),
                "-t",
                f"{duration_seconds:.9f}",
                "-f",
                "s16le",
                str(pcm),
            ]
            with _ExtractionSlot(
                cache_root,
                limits.max_concurrency,
            ):
                subprocess.run(command, check=True)
            samples = _envelope(pcm.read_bytes(), sample_count)
            json_stage.write_bytes(_waveform_payload(samples))
            entry = _publish_entry(
                cache_root,
                cache_key,
                "waveform",
                "application/json",
                "json",
                json_stage,
                limits,
            )
            return PresentationWaveformResult(
                entry.blob,
                entry.path,
                cache_key,
                False,
                samples,
            )
        finally:
            pcm.unlink(missing_ok=True)
            json_stage.unlink(missing_ok=True)
