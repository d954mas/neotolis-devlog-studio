"""Fresh-process-capable rendering from TimelineIR and immutable objects."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import re
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from fractions import Fraction
from pathlib import Path
from typing import Any, BinaryIO, Literal, Protocol

from dlstudio.foundation.api import BlobRef, canonical_bytes, canonical_hash
from dlstudio.rendering._filters import media_geometry_filter
from dlstudio.timeline.api import (
    AnimationInstruction,
    AssetSnapshot,
    AudioInstruction,
    TimelineIR,
    _base_transition_track,
    check_timeline,
)


class ObjectResolver(Protocol):
    def path_for(self, ref: BlobRef) -> Path: ...

    def verify(self, ref: BlobRef) -> None: ...


@dataclass(frozen=True, slots=True)
class ExecutionFingerprint:
    ffmpeg: str
    ffmpeg_version: str
    renderer_source_sha256: str
    ffmpeg_build_sha256: str
    ffmpeg_binary_sha256: str
    runtime: str
    raster_contract: str = "ffmpeg-filtergraph-v1"
    video_encoder: str = "libx264"
    audio_encoder: str = "aac"

    DOMAIN = "dlstudio.execution_fingerprint"
    VERSION = 1

    def as_payload(self) -> dict[str, str]:
        return {
            "ffmpeg_version": self.ffmpeg_version,
            "ffmpeg_build_sha256": self.ffmpeg_build_sha256,
            "ffmpeg_binary_sha256": self.ffmpeg_binary_sha256,
            "renderer_source_sha256": self.renderer_source_sha256,
            "runtime": self.runtime,
            "raster_contract": self.raster_contract,
            "video_encoder": self.video_encoder,
            "audio_encoder": self.audio_encoder,
        }

    @classmethod
    def detect(cls, ffmpeg: str = "ffmpeg") -> "ExecutionFingerprint":
        executable = shutil.which(ffmpeg)
        if executable is None:
            raise FileNotFoundError(f"FFmpeg executable not found: {ffmpeg}")
        completed = subprocess.run(
            [executable, "-version"],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        semantic_sources = (
            Path(__file__),
            Path(__file__).with_name("_filters.py"),
            Path(__file__).with_name("worker.py"),
            Path(__file__).parents[1] / "timeline" / "api.py",
        )
        source_digest = hashlib.sha256()
        for source_path in sorted(semantic_sources):
            raw = source_path.read_bytes()
            source_digest.update(source_path.name.encode("utf-8"))
            source_digest.update(len(raw).to_bytes(8, "big"))
            source_digest.update(raw)
        ffmpeg_build = completed.stdout.encode("utf-8")
        binary_digest = hashlib.sha256()
        with Path(executable).open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                binary_digest.update(chunk)
        return cls(
            ffmpeg=executable,
            ffmpeg_version=completed.stdout.splitlines()[0],
            renderer_source_sha256=source_digest.hexdigest(),
            ffmpeg_build_sha256=hashlib.sha256(ffmpeg_build).hexdigest(),
            ffmpeg_binary_sha256=binary_digest.hexdigest(),
            runtime=(
                f"{platform.python_implementation()}-{platform.python_version()}-"
                f"{platform.system()}-{platform.machine()}"
            ),
        )

    def validate_executor(self) -> "ExecutionFingerprint":
        current = self.detect(self.ffmpeg)
        if current.as_payload() != self.as_payload():
            raise RuntimeError("local renderer differs from its fingerprint")
        return current

    @property
    def ref(self) -> BlobRef:
        raw = self.canonical_bytes()
        return BlobRef(
            canonical_hash(
                self.as_payload(), domain=self.DOMAIN, version=self.VERSION
            ),
            len(raw),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @classmethod
    def from_canonical_bytes(
        cls, raw: bytes, *, ffmpeg: str = "ffmpeg"
    ) -> "ExecutionFingerprint":
        wrapped = json.loads(raw)
        if (
            wrapped.get("$domain") != cls.DOMAIN
            or wrapped.get("$version") != cls.VERSION
        ):
            raise ValueError("invalid execution fingerprint schema")
        value = wrapped["payload"]
        result = cls(
            ffmpeg=ffmpeg,
            ffmpeg_version=str(value["ffmpeg_version"]),
            renderer_source_sha256=str(value["renderer_source_sha256"]),
            ffmpeg_build_sha256=str(value["ffmpeg_build_sha256"]),
            ffmpeg_binary_sha256=str(value["ffmpeg_binary_sha256"]),
            runtime=str(value["runtime"]),
            raster_contract=str(value["raster_contract"]),
            video_encoder=str(value["video_encoder"]),
            audio_encoder=str(value["audio_encoder"]),
        )
        if result.canonical_bytes() != raw:
            raise ValueError("execution fingerprint is not canonical")
        return result


@dataclass(frozen=True, slots=True)
class RenderOptions:
    crf: int = 23
    preset: str = "veryfast"
    pixel_format: str = "yuv420p"
    audio_bitrate: str = "192k"

    DOMAIN = "dlstudio.render_options"
    VERSION = 1

    def __post_init__(self) -> None:
        if not 0 <= self.crf <= 51:
            raise ValueError("crf must be 0..51")

    def as_payload(self) -> dict[str, object]:
        return {
            "crf": self.crf,
            "preset": self.preset,
            "pixel_format": self.pixel_format,
            "audio_bitrate": self.audio_bitrate,
        }

    @property
    def ref(self) -> BlobRef:
        raw = self.canonical_bytes()
        return BlobRef(
            canonical_hash(
                self.as_payload(), domain=self.DOMAIN, version=self.VERSION
            ),
            len(raw),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "RenderOptions":
        wrapped = json.loads(raw)
        if (
            wrapped.get("$domain") != cls.DOMAIN
            or wrapped.get("$version") != cls.VERSION
        ):
            raise ValueError("invalid render options schema")
        value = wrapped["payload"]
        result = cls(
            crf=int(value["crf"]),
            preset=str(value["preset"]),
            pixel_format=str(value["pixel_format"]),
            audio_bitrate=str(value["audio_bitrate"]),
        )
        if result.canonical_bytes() != raw:
            raise ValueError("render options are not canonical")
        return result


@dataclass(frozen=True, slots=True)
class RenderResult:
    artifact: BlobRef
    path: Path
    cache_key: str
    cache_hit: bool
    command: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class ArtifactFinding:
    rule: str
    severity: Literal["warning", "error"]
    message: str

    def __post_init__(self) -> None:
        if not self.rule.strip():
            raise ValueError("artifact finding rule is required")
        if self.severity not in {"warning", "error"}:
            raise ValueError("unsupported artifact finding severity")
        if not self.message.strip():
            raise ValueError("artifact finding message is required")

    def as_payload(self) -> dict[str, str]:
        return {
            "rule": self.rule,
            "severity": self.severity,
            "message": self.message,
        }


@dataclass(frozen=True, slots=True)
class ArtifactReport:
    artifact: BlobRef
    width: int
    height: int
    fps_num: int
    fps_den: int
    duration_ns: int
    audio_codec: str | None
    audio_sample_rate: int | None
    audio_channels: int | None
    integrated_lufs_milli: int | None
    true_peak_db_milli: int | None
    active_audio_ratio_milli: int | None
    findings: tuple[ArtifactFinding, ...] = ()
    voice_true_peak_db_milli: int | None = None
    voice_active_audio_ratio_milli: int | None = None
    ffprobe_binary_sha256: str | None = None
    voice_correlation_db_milli: int | None = None

    DOMAIN = "dlstudio.artifact_report"
    VERSION = 2

    def __post_init__(self) -> None:
        if min(
            self.width,
            self.height,
            self.fps_num,
            self.fps_den,
            self.duration_ns,
        ) <= 0:
            raise ValueError("artifact video facts must be positive")
        audio_values = (
            self.audio_codec,
            self.audio_sample_rate,
            self.audio_channels,
        )
        if any(value is None for value in audio_values) and any(
            value is not None for value in audio_values
        ):
            raise ValueError("artifact audio stream facts must be complete")
        if self.audio_sample_rate is not None and self.audio_sample_rate <= 0:
            raise ValueError("artifact audio sample rate must be positive")
        if self.audio_channels is not None and self.audio_channels <= 0:
            raise ValueError("artifact audio channels must be positive")
        if (
            self.active_audio_ratio_milli is not None
            and not 0 <= self.active_audio_ratio_milli <= 1000
        ):
            raise ValueError("active audio ratio must be 0..1000")
        if (
            self.voice_active_audio_ratio_milli is not None
            and not 0 <= self.voice_active_audio_ratio_milli <= 1000
        ):
            raise ValueError("voice active audio ratio must be 0..1000")
        if (
            self.ffprobe_binary_sha256 is not None
            and re.fullmatch(r"[0-9a-f]{64}", self.ffprobe_binary_sha256) is None
        ):
            raise ValueError("ffprobe binary sha256 must be lowercase hexadecimal")
        object.__setattr__(self, "findings", tuple(self.findings))

    @property
    def blocking(self) -> bool:
        return any(item.severity == "error" for item in self.findings)

    def as_payload(self) -> dict[str, Any]:
        return {
            "artifact": self.artifact.as_payload(),
            "width": self.width,
            "height": self.height,
            "fps_num": self.fps_num,
            "fps_den": self.fps_den,
            "duration_ns": self.duration_ns,
            "audio_codec": self.audio_codec,
            "audio_sample_rate": self.audio_sample_rate,
            "audio_channels": self.audio_channels,
            "integrated_lufs_milli": self.integrated_lufs_milli,
            "true_peak_db_milli": self.true_peak_db_milli,
            "active_audio_ratio_milli": self.active_audio_ratio_milli,
            "voice_true_peak_db_milli": self.voice_true_peak_db_milli,
            "voice_active_audio_ratio_milli": (
                self.voice_active_audio_ratio_milli
            ),
            "ffprobe_binary_sha256": self.ffprobe_binary_sha256,
            "voice_correlation_db_milli": self.voice_correlation_db_milli,
            "findings": [item.as_payload() for item in self.findings],
        }

    @property
    def ref(self) -> BlobRef:
        raw = self.canonical_bytes()
        return BlobRef(
            canonical_hash(
                self.as_payload(), domain=self.DOMAIN, version=self.VERSION
            ),
            len(raw),
        )

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "ArtifactReport":
        wrapped = json.loads(raw)
        if (
            wrapped.get("$domain") != cls.DOMAIN
            or wrapped.get("$version") != cls.VERSION
        ):
            raise ValueError("invalid artifact report schema")
        value = wrapped["payload"]
        result = cls(
            artifact=BlobRef.from_payload(value["artifact"]),
            width=int(value["width"]),
            height=int(value["height"]),
            fps_num=int(value["fps_num"]),
            fps_den=int(value["fps_den"]),
            duration_ns=int(value["duration_ns"]),
            audio_codec=value["audio_codec"],
            audio_sample_rate=(
                None
                if value["audio_sample_rate"] is None
                else int(value["audio_sample_rate"])
            ),
            audio_channels=(
                None
                if value["audio_channels"] is None
                else int(value["audio_channels"])
            ),
            integrated_lufs_milli=(
                None
                if value["integrated_lufs_milli"] is None
                else int(value["integrated_lufs_milli"])
            ),
            true_peak_db_milli=(
                None
                if value["true_peak_db_milli"] is None
                else int(value["true_peak_db_milli"])
            ),
            active_audio_ratio_milli=(
                None
                if value["active_audio_ratio_milli"] is None
                else int(value["active_audio_ratio_milli"])
            ),
            voice_true_peak_db_milli=(
                None
                if value["voice_true_peak_db_milli"] is None
                else int(value["voice_true_peak_db_milli"])
            ),
            voice_active_audio_ratio_milli=(
                None
                if value["voice_active_audio_ratio_milli"] is None
                else int(value["voice_active_audio_ratio_milli"])
            ),
            ffprobe_binary_sha256=value["ffprobe_binary_sha256"],
            voice_correlation_db_milli=(
                None
                if value["voice_correlation_db_milli"] is None
                else int(value["voice_correlation_db_milli"])
            ),
            findings=tuple(
                ArtifactFinding(
                    rule=str(item["rule"]),
                    severity=item["severity"],
                    message=str(item["message"]),
                )
                for item in value["findings"]
            ),
        )
        if result.canonical_bytes() != raw:
            raise ValueError("artifact report is not canonical")
        return result


def _probe_fraction(value: str) -> Fraction:
    numerator, denominator = value.split("/", 1)
    result = Fraction(int(numerator), int(denominator))
    if result <= 0:
        raise ValueError("artifact fps must be positive")
    return result


def _probe_duration_ns(value: object) -> int:
    duration = Decimal(str(value))
    if duration <= 0:
        raise ValueError("artifact duration must be positive")
    return int(duration * Decimal(1_000_000_000))


def _audio_metric(output: str, pattern: str) -> int | None:
    matches = re.findall(pattern, output, flags=re.IGNORECASE)
    if not matches:
        return None
    value = matches[-1]
    if "inf" in value.lower():
        return None
    return int(Decimal(value) * Decimal(1000))


def _active_audio_ratio(output: str, duration_ns: int) -> int:
    silence = sum(
        (Decimal(value) for value in re.findall(
            r"silence_duration:\s*([0-9]+(?:[.][0-9]+)?)",
            output,
        )),
        Decimal(0),
    )
    duration = Decimal(duration_ns) / Decimal(1_000_000_000)
    active = max(Decimal(0), min(Decimal(1), Decimal(1) - silence / duration))
    return int(active * Decimal(1000))


def paired_ffprobe(ffmpeg: str) -> str:
    """Resolve ffprobe from the same installed toolchain as exact FFmpeg."""

    executable = Path(ffmpeg).resolve(strict=True)
    suffix = executable.suffix if os.name == "nt" else ""
    probe = executable.with_name(f"ffprobe{suffix}")
    if not probe.is_file():
        raise FileNotFoundError(
            f"paired FFprobe executable not found beside FFmpeg: {probe}"
        )
    return str(probe)


@dataclass(frozen=True, slots=True)
class VoiceSignalEvidence:
    artifact: BlobRef
    true_peak_db_milli: int | None
    active_audio_ratio_milli: int
    correlation_db_milli: int | None


def analyze_voice_signal(
    artifact: BlobRef,
    artifact_path: Path,
    timeline: TimelineIR,
    resolver: ObjectResolver,
    *,
    ffmpeg: str,
) -> VoiceSignalEvidence:
    """Prove expected voice is audible and correlated with the exact final."""

    voices = tuple(item for item in timeline.audio if item.role == "voice")
    if not voices:
        return VoiceSignalEvidence(artifact, None, 0, None)
    final_path = artifact_path.resolve(strict=True)
    if _hash_file(final_path) != artifact:
        raise ValueError("voice evidence path does not contain the exact artifact")
    snapshots = {snapshot.ref: snapshot for snapshot in timeline.assets}
    def voice_graph(input_offset: int) -> tuple[list[str], list[str], str]:
        arguments: list[str] = []
        filters: list[str] = []
        labels: list[str] = []
        for index, item in enumerate(voices):
            snapshot = snapshots.get(item.asset)
            if snapshot is None:
                raise ValueError("voice asset revision is absent from TimelineIR")
            resolver.verify(snapshot.blob)
            if item.loop:
                arguments.extend(["-stream_loop", "-1"])
            arguments.extend(["-i", str(resolver.path_for(snapshot.blob))])
            label = f"voice{index}"
            effects = (
                "aformat=sample_rates=48000:channel_layouts=stereo,"
                f"atrim=start={_seconds(item.source_start_ns)}:"
                f"duration={_seconds(item.duration_ns)},"
                "asetpts=N/SR/TB,"
                f"volume={item.gain_db_milli / 1000:.3f}dB"
            )
            if item.fade_in_ns:
                effects += f",afade=t=in:st=0:d={_seconds(item.fade_in_ns)}"
            if item.fade_out_ns:
                fade_start = item.duration_ns - item.fade_out_ns
                effects += (
                    f",afade=t=out:st={_seconds(fade_start)}:"
                    f"d={_seconds(item.fade_out_ns)}"
                )
            delay_ms = round(item.start_ns / 1_000_000)
            filters.append(
                f"[{index + input_offset}:a]{effects},"
                f"adelay=delays={delay_ms}:all=1[{label}]"
            )
            labels.append(label)
        inputs = "".join(f"[{label}]" for label in labels)
        mix = (
            f"{inputs}amix=inputs={len(labels)}:normalize=0:duration=longest,"
            f"apad,atrim=duration={_seconds(timeline.duration_ns)}"
        )
        return arguments, filters, mix

    voice_arguments, filters, mix = voice_graph(0)
    command = [ffmpeg, "-hide_banner", "-nostats", *voice_arguments]
    filters.append(
        f"{mix},silencedetect=noise=-50dB:d=0.05,"
        "ebur128=peak=true[voiceout]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            "[voiceout]",
            "-f",
            "null",
            os.devnull,
        ]
    )
    measured = subprocess.run(
        command,
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    voice_peak = _audio_metric(
            measured.stderr,
            r"\bPeak:\s*(-?inf|[+-]?[0-9]+(?:[.][0-9]+)?)\s+dBFS",
    )
    voice_active = _active_audio_ratio(measured.stderr, timeline.duration_ns)

    correlation_arguments, correlation_filters, correlation_mix = voice_graph(1)
    correlation_filters.extend(
        (
            f"{correlation_mix}[expectedvoice]",
            "[0:a]aformat=sample_rates=48000:channel_layouts=stereo,"
            f"apad,atrim=duration={_seconds(timeline.duration_ns)}[finalaudio]",
            "[finalaudio][expectedvoice]"
            "axcorrelate=size=8192:algo=fast,"
            "astats=metadata=1:reset=0[correlation]",
        )
    )
    correlation = subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-nostats",
            "-i",
            str(final_path),
            *correlation_arguments,
            "-filter_complex",
            ";".join(correlation_filters),
            "-map",
            "[correlation]",
            "-f",
            "null",
            os.devnull,
        ],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    correlation_db = None if correlation.returncode else _audio_metric(
        correlation.stderr,
        r"RMS level dB:\s*(-?inf|[+-]?[0-9]+(?:[.][0-9]+)?)",
    )
    return VoiceSignalEvidence(
        artifact,
        voice_peak,
        voice_active,
        correlation_db,
    )


def verify_rendered_artifact(
    artifact: BlobRef,
    path: Path,
    timeline: TimelineIR,
    *,
    require_voice: bool,
    voice_signal: VoiceSignalEvidence | None = None,
    ffmpeg: str = "ffmpeg",
    ffprobe: str = "ffprobe",
) -> ArtifactReport:
    """Probe the exact ingested final artifact and return canonical evidence."""

    source = path.resolve(strict=True)
    if _hash_file(source) != artifact:
        raise ValueError("artifact path does not contain the exact artifact")
    if require_voice and voice_signal is None:
        raise ValueError("voice-required verification needs isolated voice evidence")
    if voice_signal is not None and voice_signal.artifact != artifact:
        raise ValueError("voice evidence does not name the exact artifact")
    probe_executable = shutil.which(ffprobe)
    if probe_executable is None:
        raise FileNotFoundError(f"FFprobe executable not found: {ffprobe}")
    probe = subprocess.run(
        [
            probe_executable,
            "-v",
            "error",
            "-show_streams",
            "-show_format",
            "-of",
            "json",
            str(source),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    payload = json.loads(probe.stdout)
    streams = payload.get("streams", ())
    video = next(
        (item for item in streams if item.get("codec_type") == "video"),
        None,
    )
    if video is None:
        raise ValueError("artifact has no video stream")
    audio = next(
        (item for item in streams if item.get("codec_type") == "audio"),
        None,
    )
    fps = _probe_fraction(
        str(video.get("avg_frame_rate") or video.get("r_frame_rate"))
    )
    duration_value = video.get("duration") or payload.get("format", {}).get(
        "duration"
    )
    duration_ns = _probe_duration_ns(duration_value)
    findings: list[ArtifactFinding] = []
    width = int(video["width"])
    height = int(video["height"])
    if (width, height) != (timeline.width, timeline.height):
        findings.append(
            ArtifactFinding(
                "artifact.geometry.mismatch",
                "error",
                "final artifact geometry differs from TimelineIR",
            )
        )
    if fps != Fraction(timeline.fps_num, timeline.fps_den):
        findings.append(
            ArtifactFinding(
                "artifact.fps.mismatch",
                "error",
                "final artifact fps differs from TimelineIR",
            )
        )
    frame_ns = Fraction(
        1_000_000_000 * timeline.fps_den,
        timeline.fps_num,
    )
    if abs(duration_ns - timeline.duration_ns) > frame_ns:
        findings.append(
            ArtifactFinding(
                "artifact.duration.mismatch",
                "error",
                "final artifact duration differs by more than one frame",
            )
        )

    integrated_lufs_milli: int | None = None
    true_peak_db_milli: int | None = None
    active_audio_ratio_milli: int | None = None
    if audio is None:
        if require_voice:
            findings.append(
                ArtifactFinding(
                    "audio.voice.required",
                    "error",
                    "voice-required final artifact has no audio stream",
                )
            )
    else:
        loudness = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-af",
                "ebur128=peak=true",
                "-f",
                "null",
                os.devnull,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        integrated_lufs_milli = _audio_metric(
            loudness.stderr,
            r"\bI:\s*(-?inf|[+-]?[0-9]+(?:[.][0-9]+)?)\s+LUFS",
        )
        true_peak_db_milli = _audio_metric(
            loudness.stderr,
            r"\bPeak:\s*(-?inf|[+-]?[0-9]+(?:[.][0-9]+)?)\s+dBFS",
        )
        silence = subprocess.run(
            [
                ffmpeg,
                "-hide_banner",
                "-nostats",
                "-i",
                str(source),
                "-map",
                "0:a:0",
                "-af",
                "silencedetect=noise=-50dB:d=0.05",
                "-f",
                "null",
                os.devnull,
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        active_audio_ratio_milli = _active_audio_ratio(
            silence.stderr,
            duration_ns,
        )
        voice_peak = None if voice_signal is None else voice_signal.true_peak_db_milli
        voice_active = (
            0 if voice_signal is None else voice_signal.active_audio_ratio_milli
        )
        voice_correlation = (
            None if voice_signal is None else voice_signal.correlation_db_milli
        )
        if require_voice and (
            active_audio_ratio_milli <= 10
            or true_peak_db_milli is None
            or true_peak_db_milli <= -60_000
            or voice_active <= 10
            or voice_peak is None
            or voice_peak <= -60_000
            or voice_correlation is None
            or voice_correlation <= -30_000
        ):
            findings.append(
                ArtifactFinding(
                    "audio.voice.silent",
                    "error",
                    "voice-required final artifact contains no audible signal",
                )
            )

    return ArtifactReport(
        artifact=artifact,
        width=width,
        height=height,
        fps_num=fps.numerator,
        fps_den=fps.denominator,
        duration_ns=duration_ns,
        audio_codec=(None if audio is None else str(audio["codec_name"])),
        audio_sample_rate=(
            None if audio is None else int(audio["sample_rate"])
        ),
        audio_channels=None if audio is None else int(audio["channels"]),
        integrated_lufs_milli=integrated_lufs_milli,
        true_peak_db_milli=true_peak_db_milli,
        active_audio_ratio_milli=active_audio_ratio_milli,
        voice_true_peak_db_milli=(
            None if voice_signal is None else voice_signal.true_peak_db_milli
        ),
        voice_active_audio_ratio_milli=(
            None if voice_signal is None else voice_signal.active_audio_ratio_milli
        ),
        ffprobe_binary_sha256=_hash_file(Path(probe_executable)).sha256,
        voice_correlation_db_milli=(
            None if voice_signal is None else voice_signal.correlation_db_milli
        ),
        findings=tuple(findings),
    )


class _CacheLease:
    """Cross-process kernel lease scoped to one render cache key."""

    def __init__(self, path: Path, timeout: float = 30.0) -> None:
        self.path = path
        self.timeout = timeout
        self._handle: BinaryIO | None = None

    @staticmethod
    def _try_lock(handle: BinaryIO) -> bool:
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
    def _unlock(handle: BinaryIO) -> None:
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def __enter__(self) -> "_CacheLease":
        self.path.parent.mkdir(parents=True, exist_ok=True)
        handle = self.path.open("a+b")
        if handle.tell() == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        deadline = time.monotonic() + self.timeout
        while not self._try_lock(handle):
            if time.monotonic() >= deadline:
                handle.close()
                raise TimeoutError(f"render cache lease timeout: {self.path.name}")
            time.sleep(0.01)
        self._handle = handle
        return self

    def __exit__(self, *_exc: object) -> None:
        if self._handle is not None:
            self._unlock(self._handle)
            self._handle.close()
            self._handle = None


def _reachable_blobs(timeline: TimelineIR) -> tuple[BlobRef, ...]:
    return tuple(
        sorted(
            {
                blob
                for snapshot in timeline.assets
                for blob in snapshot.revision.reachable_blobs
            },
            key=lambda ref: (ref.sha256, ref.size),
        )
    )


def _verify_metadata(resolver: ObjectResolver, ref: BlobRef) -> None:
    verifier = getattr(resolver, "verify_metadata", None)
    if verifier is None:
        path = resolver.path_for(ref)
        if not path.is_file() or path.stat().st_size != ref.size:
            raise ValueError(f"missing object: {ref.sha256}")
        return
    verifier(ref)


def _atomic_copy_verified(
    source: Path,
    output: Path,
    expected: BlobRef,
) -> None:
    """Copy once while verifying bytes; cache correctness needs no local secret."""

    temp = output.with_name(f".{output.name}.{uuid.uuid4().hex}.tmp")
    try:
        digest = hashlib.sha256()
        size = 0
        with source.open("rb") as reader, temp.open("xb") as writer:
            while chunk := reader.read(1024 * 1024):
                digest.update(chunk)
                size += len(chunk)
                writer.write(chunk)
            writer.flush()
            os.fsync(writer.fileno())
        if size != expected.size or digest.hexdigest() != expected.sha256:
            raise ValueError("render cache payload hash mismatch")
        os.replace(temp, output)
    finally:
        temp.unlink(missing_ok=True)


def _load_cache_hit(
    cache_root: Path,
    cache_key: str,
    output: Path,
) -> RenderResult | None:
    manifest_path = cache_root / "manifests" / f"{cache_key}.json"
    if not manifest_path.is_file():
        return None
    try:
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        sha256 = str(manifest["sha256"])
        size = int(manifest["size"])
        if (
            manifest.get("schema") != "dlstudio.render_cache"
            or manifest.get("version") != 1
            or manifest.get("cache_key") != cache_key
        ):
            return None
        artifact = BlobRef(sha256, size)
        cached = cache_root / "objects" / f"{sha256}.mp4"
        if not cached.is_file() or cached.stat().st_size != size:
            return None
        _atomic_copy_verified(cached, output, artifact)
        return RenderResult(artifact, output, cache_key, True, ())
    except (KeyError, OSError, TypeError, ValueError, json.JSONDecodeError):
        return None


def _publish_cache(
    cache_root: Path,
    cache_key: str,
    source: Path,
    artifact: BlobRef,
) -> None:
    objects = cache_root / "objects"
    manifests = cache_root / "manifests"
    objects.mkdir(parents=True, exist_ok=True)
    manifests.mkdir(parents=True, exist_ok=True)
    cached = objects / f"{artifact.sha256}.mp4"
    if not cached.exists() or _hash_file(cached) != artifact:
        stage = objects / f".{artifact.sha256}.{uuid.uuid4().hex}.tmp"
        try:
            shutil.copyfile(source, stage)
            if _hash_file(stage) != artifact:
                raise RuntimeError("render cache publish verification failed")
            os.replace(stage, cached)
        finally:
            stage.unlink(missing_ok=True)
    payload = {
        "schema": "dlstudio.render_cache",
        "version": 1,
        "cache_key": cache_key,
        "sha256": artifact.sha256,
        "size": artifact.size,
    }
    manifest = manifests / f"{cache_key}.json"
    stage_manifest = manifests / f".{cache_key}.{uuid.uuid4().hex}.tmp"
    try:
        stage_manifest.write_text(
            json.dumps(payload, sort_keys=True, separators=(",", ":")),
            encoding="utf-8",
        )
        os.replace(stage_manifest, manifest)
    finally:
        stage_manifest.unlink(missing_ok=True)


def _seconds(value_ns: int) -> str:
    whole, remainder = divmod(value_ns, 1_000_000_000)
    return f"{whole}.{remainder:09d}".rstrip("0").rstrip(".")


def _escape_filter_text(value: str) -> str:
    return (
        value.replace("\\", "\\\\")
        .replace(":", "\\:")
        .replace("'", r"\'")
        .replace(",", r"\,")
        .replace("[", r"\[")
        .replace("]", r"\]")
        .replace("%", r"\%")
        .replace("\n", r"\n")
    )


def _find_animation(
    instruction: object, prop: str
) -> AnimationInstruction | None:
    for animation in getattr(instruction, "animations", ()):
        if animation.prop == prop:
            return animation
    return None


def _animation_value(
    animation: AnimationInstruction,
    *,
    clock: str,
    origin_ns: int = 0,
) -> str:
    start = _seconds(animation.start_ns - origin_ns)
    duration = _seconds(animation.end_ns - animation.start_ns)
    progress = f"clip(({clock}-{start})/{duration},0,1)"
    if animation.ease == "linear":
        eased = progress
    elif animation.ease == "in":
        eased = f"pow({progress},3)"
    elif animation.ease == "out":
        eased = f"1-pow(1-({progress}),3)"
    elif animation.ease == "in_out":
        eased = (
            f"if(lt({progress},0.5),4*pow({progress},3),"
            f"1-pow(-2*({progress})+2,3)/2)"
        )
    else:
        eased = (
            f"1+2.70158*pow(({progress})-1,3)"
            f"+1.70158*pow(({progress})-1,2)"
        )
    delta = animation.end_milli - animation.start_milli
    return f"({animation.start_milli}+({delta})*({eased}))/1000"


def _asset_map(timeline: TimelineIR) -> dict[object, AssetSnapshot]:
    return {snapshot.ref: snapshot for snapshot in timeline.assets}


def _build_command(
    timeline: TimelineIR,
    fingerprint: ExecutionFingerprint,
    options: RenderOptions,
    resolver: ObjectResolver,
    output: Path,
) -> list[str]:
    snapshots = _asset_map(timeline)
    used_sources = {
        (visual.asset, visual.loop)
        for visual in timeline.visuals
        if visual.asset is not None
    } | {(audio.asset, audio.loop) for audio in timeline.audio}
    ordered_sources = sorted(
        used_sources,
        key=lambda item: (
            item[0].asset_id,
            item[0].revision_hash,
            item[1],
        ),
    )
    input_index: dict[tuple[object, bool], int] = {}
    command = [
        fingerprint.ffmpeg,
        "-hide_banner",
        "-loglevel",
        "error",
        "-f",
        "lavfi",
        "-i",
        (
            f"color=c={timeline.background}:s={timeline.width}x{timeline.height}:"
            f"r={timeline.fps_num}/{timeline.fps_den}:"
            f"d={_seconds(timeline.duration_ns)}"
        ),
    ]
    for ref, loop in ordered_sources:
        snapshot = snapshots[ref]
        resolver.verify(snapshot.blob)
        input_index[(ref, loop)] = len(input_index) + 1
        if snapshot.media.kind == "image":
            command.extend(
                [
                    "-loop",
                    "1",
                    "-framerate",
                    f"{timeline.fps_num}/{timeline.fps_den}",
                    "-f",
                    "image2",
                ]
            )
        elif loop:
            command.extend(["-stream_loop", "-1"])
        command.extend(["-i", str(resolver.path_for(snapshot.blob))])
    silent_index = len(input_index) + 1
    command.extend(
        [
            "-f",
            "lavfi",
            "-i",
            f"anullsrc=r=48000:cl=stereo:d={_seconds(timeline.duration_ns)}",
        ]
    )

    filters: list[str] = ["[0:v]setpts=PTS-STARTPTS[v0]"]
    current = "v0"
    media_counter = 0
    ordered_visuals = sorted(
        timeline.visuals, key=lambda item: (item.z, item.start_ns, item.kind)
    )
    base_media = _base_transition_track(timeline)
    base_instruction_ids: set[int] = set()
    if base_media is not None:
        filters.append("[v0]nullsink")
        base_labels: list[str] = []
        for position, instruction in enumerate(base_media):
            assert instruction.asset is not None
            base_instruction_ids.add(id(instruction))
            snapshot = snapshots[instruction.asset]
            index = input_index[(instruction.asset, instruction.loop)]
            duration = _seconds(instruction.duration_ns)
            geometry = media_geometry_filter(
                instruction,
                background=timeline.background,
            )
            padding = ""
            if instruction.freeze_at_end:
                padding = (
                    f",tpad=stop_mode=clone:stop_duration={duration},"
                    f"trim=duration={duration}"
                )
            motion = ""
            if instruction.ken_burns:
                motion = (
                    ",zoompan=z='min(zoom+0.0003,1.08)':"
                    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                    f"d=1:s={instruction.width}x{instruction.height}:"
                    f"fps={timeline.fps_num}/{timeline.fps_den}"
                )
            label = f"base{position}"
            filters.append(
                f"[{index}:v]trim=start={_seconds(instruction.source_start_ns)}:"
                f"duration={duration},setpts=PTS-STARTPTS{padding},"
                f"{geometry}{motion},setsar=1,"
                f"fps={timeline.fps_num}/{timeline.fps_den},"
                f"settb=expr=AVTB,format=yuv420p[{label}]"
            )
            base_labels.append(label)
        base_current = base_labels[0]
        cumulative_ns = 0
        transition_names = {
            "fade": "fade",
            "dip_black": "fadeblack",
            "slide_left": "slideleft",
            "slide_right": "slideright",
        }
        for position in range(1, len(base_media)):
            left = base_media[position - 1]
            right = base_media[position]
            cumulative_ns += left.duration_ns - (
                right.transition_ns if right.transition != "cut" else 0
            )
            result = f"basejoin{position}"
            if right.transition == "cut":
                filters.append(
                    f"[{base_current}][{base_labels[position]}]"
                    f"concat=n=2:v=1:a=0[{result}]"
                )
            else:
                filters.append(
                    f"[{base_current}][{base_labels[position]}]"
                    f"xfade=transition={transition_names[right.transition]}:"
                    f"duration={_seconds(right.transition_ns)}:"
                    f"offset={_seconds(cumulative_ns)}[{result}]"
                )
            base_current = result
        filters.append(
            f"[{base_current}]trim=duration={_seconds(timeline.duration_ns)},"
            "setpts=PTS-STARTPTS[vbase]"
        )
        current = "vbase"

    for instruction in ordered_visuals:
        if id(instruction) in base_instruction_ids:
            continue
        start = _seconds(instruction.start_ns)
        end = _seconds(instruction.end_ns)
        next_label = f"v{media_counter + 1}"
        if instruction.kind == "solid":
            alpha = instruction.opacity_milli / 1000
            color = f"{instruction.color}@{alpha:.3f}"
            filters.append(
                f"[{current}]drawbox=x={instruction.x}:y={instruction.y}:"
                f"w={instruction.width}:h={instruction.height}:color={color}:"
                f"t=fill:enable='between(t,{start},{end})'[{next_label}]"
            )
        elif instruction.kind == "text":
            assert instruction.font_asset is not None
            font = snapshots[instruction.font_asset]
            resolver.verify(font.blob)
            font_path = _escape_filter_text(str(resolver.path_for(font.blob)))
            text = _escape_filter_text(instruction.text or "")
            alpha = instruction.opacity_milli / 1000
            text_base = f"textbase{media_counter}"
            text_layer = f"textlayer{media_counter}"
            filters.append(
                f"color=c=black@0.0:s={instruction.width}x{instruction.height}:"
                f"r={timeline.fps_num}/{timeline.fps_den}:"
                f"d={_seconds(instruction.duration_ns)},format=rgba[{text_base}]"
            )
            fades = ""
            if instruction.transition == "fade":
                fades += (
                    f",fade=t=in:st=0:"
                    f"d={_seconds(instruction.transition_ns)}:alpha=1"
                )
            filters.append(
                f"[{text_base}]drawtext=fontfile='{font_path}':text='{text}':"
                f"x=0:y=0:fontsize={instruction.font_size}:"
                f"fontcolor={instruction.color}@{alpha:.3f},"
                f"setpts=PTS-STARTPTS{fades},"
                f"setpts=PTS-STARTPTS+{start}/TB[{text_layer}]"
            )
            filters.append(
                f"[{current}][{text_layer}]overlay=x={instruction.x}:"
                f"y={instruction.y}:eof_action=pass:"
                f"enable='between(t,{start},{end})'[{next_label}]"
            )
        else:
            assert instruction.asset is not None
            snapshot = snapshots[instruction.asset]
            index = input_index[(instruction.asset, instruction.loop)]
            layer = f"layer{media_counter}"
            duration = _seconds(instruction.duration_ns)
            geometry = media_geometry_filter(
                instruction,
                background=timeline.background,
            )
            motion = ""
            if instruction.ken_burns:
                motion = (
                    ",zoompan=z='min(zoom+0.0003,1.08)':"
                    "x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                    f"d=1:s={instruction.width}x{instruction.height}:"
                    f"fps={timeline.fps_num}/{timeline.fps_den}"
                )
            scale_animation = _find_animation(instruction, "scale")
            if scale_animation is not None:
                scale_value = _animation_value(
                    scale_animation,
                    clock="t",
                    origin_ns=instruction.start_ns,
                )
                motion += (
                    f",scale=w='iw*({scale_value})':"
                    f"h='ih*({scale_value})':eval=frame,"
                    f"pad=w='max(iw,{instruction.width})':"
                    f"h='max(ih,{instruction.height})':"
                    "x='(ow-iw)/2':y='(oh-ih)/2':"
                    "color=black@0:eval=frame,"
                    f"crop={instruction.width}:{instruction.height}"
                )
            rotate_animation = _find_animation(instruction, "rotate")
            if rotate_animation is not None:
                rotate_value = _animation_value(
                    rotate_animation,
                    clock="t",
                    origin_ns=instruction.start_ns,
                )
                motion += (
                    f",rotate=a='({rotate_value})*PI/180':"
                    "ow=rotw(iw):oh=roth(ih):c=none,"
                    f"crop={instruction.width}:{instruction.height}"
                )
            fade = ""
            opacity_animation = _find_animation(instruction, "opacity")
            if instruction.transition == "fade" and opacity_animation is None:
                fade = (
                    f",fade=t=in:st={start}:"
                    f"d={_seconds(instruction.transition_ns)}:alpha=1"
                )
            if instruction.fade_out_ns and opacity_animation is None:
                fade += (
                    f",fade=t=out:st={_seconds(instruction.end_ns - instruction.fade_out_ns)}:"
                    f"d={_seconds(instruction.fade_out_ns)}:alpha=1"
                )
            animated_opacity = ""
            if opacity_animation is not None:
                opacity_value = _animation_value(
                    opacity_animation,
                    clock="T",
                    origin_ns=instruction.start_ns,
                )
                animated_opacity = (
                    ",geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
                    f"a='alpha(X,Y)*({opacity_value})'"
                )
            filters.append(
                f"[{index}:v]trim=start={_seconds(instruction.source_start_ns)}:"
                f"duration={duration},setpts=PTS-STARTPTS,"
                f"{geometry}{motion},format=rgba,colorchannelmixer=aa="
                f"{instruction.opacity_milli / 1000:.3f},"
                f"setpts=PTS-STARTPTS{animated_opacity},"
                f"setpts=PTS-STARTPTS+{start}/TB{fade}[{layer}]"
            )
            x_animation = _find_animation(instruction, "x")
            y_animation = _find_animation(instruction, "y")
            x_position = (
                str(instruction.x)
                if x_animation is None
                else f"'({_animation_value(x_animation, clock='t')})'"
            )
            y_position = (
                str(instruction.y)
                if y_animation is None
                else f"'({_animation_value(y_animation, clock='t')})'"
            )
            filters.append(
                f"[{current}][{layer}]overlay=x={x_position}:y={y_position}:"
                f"eof_action={'repeat' if instruction.freeze_at_end or snapshot.media.kind == 'image' else 'pass'}:"
                f"enable='between(t,{start},{end})'[{next_label}]"
            )
        current = next_label
        media_counter += 1

    for position, fade in enumerate(timeline.video_fades):
        fade_layer = f"vfadelayer{position}"
        faded = f"vfade{position}"
        start = _seconds(fade.start_ns)
        duration = _seconds(fade.duration_ns)
        progress = f"T/{duration}"
        alpha = (
            f"min(1\\,max(0\\,{progress}))"
            if fade.direction == "out"
            else f"1-min(1\\,max(0\\,{progress}))"
        )
        layer_duration = (
            fade.duration_ns
            + math.ceil(
                1_000_000_000 * timeline.fps_den / timeline.fps_num
            )
        )
        filters.append(
            f"color=c={fade.color}@1:s={timeline.width}x{timeline.height}:"
            f"r={timeline.fps_num}/{timeline.fps_den}:"
            f"d={_seconds(layer_duration)},format=rgba,"
            "geq=r='r(X,Y)':g='g(X,Y)':b='b(X,Y)':"
            f"a='255*({alpha})',"
            f"setpts=PTS-STARTPTS+{start}/TB"
            f"[{fade_layer}]"
        )
        filters.append(
            f"[{current}][{fade_layer}]overlay=x=0:y=0:eof_action=pass:"
            f"enable='between(t,{_seconds(fade.start_ns)},"
            f"{_seconds(fade.end_ns)})'[{faded}]"
        )
        current = faded

    audio_labels = ["asilent"]
    filters.append(
        f"[{silent_index}:a]atrim=duration={_seconds(timeline.duration_ns)},"
        "asetpts=PTS-STARTPTS[asilent]"
    )
    prepared: list[tuple[str, AudioInstruction]] = []
    for position, item in enumerate(timeline.audio):
        index = input_index[(item.asset, item.loop)]
        label = f"a{position}"
        delay_ms = round(item.start_ns / 1_000_000)
        effects = (
            "aformat=sample_rates=48000:channel_layouts=stereo,"
        )
        if item.role == "music":
            effects += "apad,"
        effects += (
            f"atrim=start={_seconds(item.source_start_ns)}:"
            f"duration={_seconds(item.duration_ns)},"
            "asetpts=N/SR/TB,"
            f"volume={item.gain_db_milli / 1000:.3f}dB"
        )
        if item.fade_in_ns:
            effects += f",afade=t=in:st=0:d={_seconds(item.fade_in_ns)}"
        if item.fade_out_ns:
            fade_start = item.duration_ns - item.fade_out_ns
            effects += (
                f",afade=t=out:st={_seconds(fade_start)}:"
                f"d={_seconds(item.fade_out_ns)}"
            )
        filters.append(
            f"[{index}:a]{effects},"
            f"adelay=delays={delay_ms}:all=1"
            f"[{label}]"
        )
        prepared.append((label, item))

    ducked = [entry for entry in prepared if entry[1].duck]
    voices = [entry for entry in prepared if entry[1].role == "voice"]
    final_labels: list[str] = []
    if ducked and voices:
        sidechain_parts: list[str] = []
        voice_final: dict[str, str] = {}
        for position, (label, _item) in enumerate(voices):
            final_label = f"{label}final"
            side_label = f"{label}side"
            filters.append(f"[{label}]asplit=2[{final_label}][{side_label}]")
            voice_final[label] = final_label
            sidechain_parts.append(side_label)
        side_inputs = "".join(f"[{label}]" for label in sidechain_parts)
        filters.append(
            f"{side_inputs}amix=inputs={len(sidechain_parts)}:"
            "normalize=0[sidechain]"
        )
        split_labels = [f"sidechain{index}" for index in range(len(ducked))]
        filters.append(
            f"[sidechain]asplit={len(split_labels)}"
            + "".join(f"[{label}]" for label in split_labels)
        )
        duck_index = 0
        threshold = 10 ** (timeline.duck_threshold_db_milli / 20_000)
        ratio = max(
            2.0,
            min(
                20.0,
                1.0 + abs(timeline.duck_amount_db_milli / 1000) / 2.0,
            ),
        )
        for label, item in prepared:
            if item.duck:
                result_label = f"{label}ducked"
                filters.append(
                    f"[{label}][{split_labels[duck_index]}]"
                    f"sidechaincompress=threshold={threshold:.6f}:"
                    f"ratio={ratio:.4f}:"
                    f"attack={timeline.duck_attack_ms}:"
                    f"release={timeline.duck_release_ms}:"
                    f"makeup=1[{result_label}]"
                )
                duck_index += 1
                final_labels.append(result_label)
            else:
                final_labels.append(voice_final.get(label, label))
    else:
        final_labels.extend(label for label, _item in prepared)
    audio_labels.extend(final_labels)
    mix_inputs = "".join(f"[{label}]" for label in audio_labels)
    loudness = ""
    if timeline.audio:
        loudness = (
            f",loudnorm=I={timeline.target_lufs_milli / 1000:.3f}:"
            f"TP={timeline.true_peak_db_milli / 1000:.3f}:LRA=11"
        )
    filters.append(
        f"{mix_inputs}amix=inputs={len(audio_labels)}:normalize=0:"
        f"duration=longest,atrim=duration={_seconds(timeline.duration_ns)}"
        f"{loudness}[aout]"
    )
    command.extend(
        [
            "-filter_complex",
            ";".join(filters),
            "-map",
            f"[{current}]",
            "-map",
            "[aout]",
            "-t",
            _seconds(timeline.duration_ns),
            "-r",
            f"{timeline.fps_num}/{timeline.fps_den}",
            "-c:v",
            fingerprint.video_encoder,
            "-preset",
            options.preset,
            "-crf",
            str(options.crf),
            "-pix_fmt",
            options.pixel_format,
            "-c:a",
            fingerprint.audio_encoder,
            "-b:a",
            options.audio_bitrate,
            "-movflags",
            "+faststart",
            "-map_metadata",
            "-1",
            "-y",
            str(output),
        ]
    )
    return command


def _hash_file(path: Path) -> BlobRef:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return BlobRef(digest.hexdigest(), size)


def execution_key(
    timeline: TimelineIR,
    fingerprint: ExecutionFingerprint,
    options: RenderOptions,
) -> str:
    return canonical_hash(
        {
            "timeline_id": timeline.timeline_id,
            "execution": fingerprint.as_payload(),
            "options": options.as_payload(),
        },
        domain="dlstudio.render_cache",
    )


def render(
    timeline: TimelineIR,
    fingerprint: ExecutionFingerprint,
    options: RenderOptions,
    resolver: ObjectResolver,
    *,
    output: Path,
    cache_root: Path | None = None,
) -> RenderResult:
    fingerprint = fingerprint.validate_executor()
    report = check_timeline(timeline)
    if report.blocking:
        raise ValueError(f"timeline checks failed: {report.findings}")
    cache_key = execution_key(timeline, fingerprint, options)
    output = output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    for blob in _reachable_blobs(timeline):
        _verify_metadata(resolver, blob)

    def execute(cache: Path | None) -> RenderResult:
        if cache is not None:
            cached = _load_cache_hit(cache, cache_key, output)
            if cached is not None:
                return cached
        fd, raw_temp = tempfile.mkstemp(
            prefix=f".{output.name}.", suffix=".mp4", dir=output.parent
        )
        os.close(fd)
        temp = Path(raw_temp)
        try:
            command = _build_command(
                timeline, fingerprint, options, resolver, temp
            )
            subprocess.run(command, check=True)
            artifact = _hash_file(temp)
            if artifact.size == 0:
                raise RuntimeError("FFmpeg produced an empty artifact")
            if cache is not None:
                _publish_cache(cache, cache_key, temp, artifact)
            os.replace(temp, output)
            return RenderResult(
                artifact, output, cache_key, False, tuple(command)
            )
        finally:
            temp.unlink(missing_ok=True)

    if cache_root is None:
        return execute(None)
    cache = cache_root.resolve()
    with _CacheLease(cache / "locks" / f"{cache_key}.lock"):
        return execute(cache)


from dlstudio.rendering._presentation import (  # noqa: E402
    PresentationCacheLimits,
    PresentationFileResult,
    PresentationFingerprint,
    PresentationWaveformResult,
    extract_presentation_frame,
    extract_presentation_waveform,
)
