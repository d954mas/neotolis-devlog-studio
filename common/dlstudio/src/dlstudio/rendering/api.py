"""Fresh-process-capable rendering from TimelineIR and immutable objects."""

from __future__ import annotations

import hashlib
import json
import math
import os
import platform
import shutil
import subprocess
import sys
import tempfile
import time
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import BinaryIO, Protocol

from dlstudio.foundation.api import BlobRef, canonical_bytes, canonical_hash
from dlstudio.timeline.api import (
    AnimationInstruction,
    AssetSnapshot,
    AudioInstruction,
    TimelineIR,
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
    base_media = [
        item
        for item in ordered_visuals
        if item.kind == "media" and item.z == 0
    ]
    base_track_geometry_is_full_canvas = all(
        item.x == 0
        and item.y == 0
        and item.width == timeline.width
        and item.height == timeline.height
        and item.opacity_milli == 1000
        and not item.animations
        for item in base_media
    )
    base_track_is_contiguous = bool(base_media) and base_media[0].start_ns == 0
    for left, right in zip(base_media, base_media[1:]):
        outgoing_tail_ns = (
            right.transition_ns if right.transition != "cut" else 0
        )
        if left.end_ns - outgoing_tail_ns != right.start_ns:
            base_track_is_contiguous = False
            break
    if base_media and base_media[-1].end_ns != timeline.duration_ns:
        base_track_is_contiguous = False
    no_competing_base_layers = all(
        item.kind == "media" and item.z == 0 for item in ordered_visuals if item.z <= 0
    )
    use_xfade_track = (
        base_track_is_contiguous
        and base_track_geometry_is_full_canvas
        and no_competing_base_layers
    )
    base_instruction_ids: set[int] = set()
    if use_xfade_track:
        filters.append("[v0]nullsink")
        base_labels: list[str] = []
        for position, instruction in enumerate(base_media):
            assert instruction.asset is not None
            base_instruction_ids.add(id(instruction))
            snapshot = snapshots[instruction.asset]
            index = input_index[(instruction.asset, instruction.loop)]
            duration = _seconds(instruction.duration_ns)
            if instruction.geometry is not None:
                resolved = instruction.geometry
                geometry = (
                    f"scale={resolved.scaled_width}:{resolved.scaled_height}"
                )
                if resolved.crop_x is not None:
                    geometry += (
                        f",crop={instruction.width}:{instruction.height}:"
                        f"{resolved.crop_x}:{resolved.crop_y}"
                    )
                elif resolved.pad_x is not None:
                    geometry += (
                        f",pad={instruction.width}:{instruction.height}:"
                        f"{resolved.pad_x}:{resolved.pad_y}:"
                        f"color={timeline.background}"
                    )
            elif instruction.fit == "stretch":
                geometry = f"scale={instruction.width}:{instruction.height}"
            elif instruction.fit == "cover":
                geometry = (
                    f"scale={instruction.width}:{instruction.height}:"
                    "force_original_aspect_ratio=increase,"
                    f"crop={instruction.width}:{instruction.height}"
                )
            else:
                geometry = (
                    f"scale={instruction.width}:{instruction.height}:"
                    "force_original_aspect_ratio=decrease,"
                    f"pad={instruction.width}:{instruction.height}:"
                    "(ow-iw)/2:(oh-ih)/2:"
                    f"color={timeline.background}"
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
            if instruction.geometry is not None:
                resolved = instruction.geometry
                geometry = (
                    f"scale={resolved.scaled_width}:{resolved.scaled_height}"
                )
                if resolved.crop_x is not None:
                    geometry += (
                        f",crop={instruction.width}:{instruction.height}:"
                        f"{resolved.crop_x}:{resolved.crop_y}"
                    )
                elif resolved.pad_x is not None:
                    geometry += (
                        f",pad={instruction.width}:{instruction.height}:"
                        f"{resolved.pad_x}:{resolved.pad_y}:"
                        f"color={timeline.background}"
                    )
            elif instruction.fit == "stretch":
                geometry = f"scale={instruction.width}:{instruction.height}"
            else:
                mode = "increase" if instruction.fit == "cover" else "decrease"
                geometry = (
                    f"scale={instruction.width}:{instruction.height}:"
                    f"force_original_aspect_ratio={mode},"
                    f"crop={instruction.width}:{instruction.height}"
                    if instruction.fit == "cover"
                    else (
                        f"scale={instruction.width}:{instruction.height}:"
                        f"force_original_aspect_ratio=decrease,"
                        f"pad={instruction.width}:{instruction.height}:"
                        "(ow-iw)/2:(oh-ih)/2:color=black"
                    )
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
