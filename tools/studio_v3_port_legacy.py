"""One-shot v2 Edit -> static v3 authoring source generator.

This tool is intentionally outside the importable runtime.  Generated files
contain only v3 contracts and literal, hash-bound facts; they never import or
resolve a v2 object at runtime.
"""

from __future__ import annotations

import argparse
import array
import base64
import bisect
import hashlib
import importlib
import json
import math
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

from PIL import Image

import dlstudio.render.beat as render_beat_module
from dlstudio.compile import build_timeline
from dlstudio.render import RenderOpts, assemble, render_beat
from dlstudio.render.raster import render_caption_png, render_chunk_png


def _sha(path: Path) -> tuple[str, int]:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return digest.hexdigest(), size


def _frame_evidence_from_raw(
    raw: bytes,
    *,
    frame_index: int,
    fps_num: int,
    fps_den: int,
) -> dict[str, Any]:
    if len(raw) != 64 * 36:
        raise RuntimeError(f"invalid frame payload at index {frame_index}")
    bits = 0
    for row in range(36):
        offset = row * 64
        for column in range(63):
            bits = (bits << 1) | (
                raw[offset + column] > raw[offset + column + 1]
            )
    return {
        "frame_index": frame_index,
        "second": round(frame_index * fps_den / fps_num, 6),
        "gray64x36_sha256": hashlib.sha256(raw).hexdigest(),
        "gray64x36_base64": base64.b64encode(raw).decode("ascii"),
        "dhash63x36": f"{bits:0567x}",
    }


def _frame_series(path: Path) -> list[tuple[int, bytes]]:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "info",
            "-i",
            str(path),
            "-vf",
            "scale=64:36,format=gray,showinfo",
            "-vsync",
            "0",
            "-f",
            "rawvideo",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    frame_size = 64 * 36
    if not completed.stdout or len(completed.stdout) % frame_size:
        raise RuntimeError("legacy frame-series extraction failed")
    frames = [
        completed.stdout[offset : offset + frame_size]
        for offset in range(0, len(completed.stdout), frame_size)
    ]
    stderr = completed.stderr.decode("utf-8", errors="replace")
    pts_ns = [
        round(float(match.group(1)) * 1_000_000_000)
        for match in re.finditer(r"showinfo.*?pts_time:\s*([0-9.eE+-]+)", stderr)
    ]
    if len(pts_ns) != len(frames):
        raise RuntimeError(
            "legacy frame timestamps do not match decoded frame payloads"
        )
    return list(zip(pts_ns, frames, strict=True))


def _nearest_frame(
    frames: list[tuple[int, bytes]],
    target_ns: int,
) -> tuple[int, bytes]:
    timestamps = [item[0] for item in frames]
    index = bisect.bisect_left(timestamps, target_ns)
    candidates = [
        candidate
        for candidate in (index - 1, index)
        if 0 <= candidate < len(frames)
    ]
    nearest = min(
        candidates,
        key=lambda candidate: abs(timestamps[candidate] - target_ns),
    )
    return frames[nearest]


def _timeline_frame_evidence(
    frames: list[tuple[int, bytes]],
    *,
    frame_index: int,
    fps_num: int,
    fps_den: int,
) -> dict[str, Any]:
    target_ns = round(
        frame_index * 1_000_000_000 * fps_den / fps_num
    )
    source_pts_ns, raw = _nearest_frame(frames, target_ns)
    return {
        **_frame_evidence_from_raw(
            raw,
            frame_index=frame_index,
            fps_num=fps_num,
            fps_den=fps_den,
        ),
        "source_pts_ns": source_pts_ns,
        "timing_delta_ns": source_pts_ns - target_ns,
    }


def _interval_frame_indices(
    start_ns: int,
    end_ns: int,
    *,
    fps_num: int,
    fps_den: int,
) -> range:
    frame_ns_denominator = 1_000_000_000 * fps_den
    first = math.ceil(start_ns * fps_num / frame_ns_denominator)
    stop = math.ceil(end_ns * fps_num / frame_ns_denominator)
    return range(max(0, first), max(0, stop))


def _audio_evidence(path: Path) -> dict[str, Any]:
    completed = subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-i",
            str(path),
            "-vn",
            "-ac",
            "1",
            "-ar",
            "8000",
            "-f",
            "s16le",
            "-",
        ],
        check=True,
        capture_output=True,
    )
    samples = array.array("h")
    samples.frombytes(completed.stdout)
    if sys.byteorder != "little":
        samples.byteswap()
    rms = (
        0.0
        if not samples
        else (sum(value * value for value in samples) / len(samples)) ** 0.5
    )
    analysis = subprocess.run(
        [
            "ffmpeg",
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vn",
            "-af",
            "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
            "-f",
            "null",
            "-",
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    start = analysis.stderr.rfind("{")
    measured, _end = json.JSONDecoder().raw_decode(analysis.stderr[start:])
    return {
        "pcm_mono_8k_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "sample_count": len(samples),
        "rms_s16": round(rms, 3),
        "integrated_lufs": float(measured["input_i"]),
        "true_peak_dbfs": float(measured["input_tp"]),
    }


def _ns(seconds: float) -> int:
    return round(seconds * 1_000_000_000)


def _sfx_specs(
    timeline: Any,
    placement: dict[str, float],
    total_ns: int,
    inspect: Any,
) -> list[tuple[Any, int, int]]:
    specs: list[tuple[Any, int, int]] = []
    for beat in timeline.beats:
        for sfx in beat.sfx:
            start_ns = _ns(placement[beat.id] + sfx.t)
            media = inspect(sfx.src, "audio")
            duration_ns = min(int(media["duration_ns"]), total_ns - start_ns)
            if duration_ns > 0:
                specs.append((sfx, start_ns, duration_ns))
    return specs


def _media(path: Path, kind_hint: str | None = None) -> dict[str, Any]:
    suffix = path.suffix.lower()
    if suffix in {".ttf", ".otf", ".ttc"}:
        return {"kind": "font", "format_name": suffix.lstrip(".")}
    if suffix in {".png", ".jpg", ".jpeg", ".webp"}:
        with Image.open(path) as image:
            width, height = image.size
        return {
            "kind": "image",
            "format_name": suffix.lstrip("."),
            "width": width,
            "height": height,
        }
    completed = subprocess.run(
        [
            "ffprobe",
            "-v",
            "error",
            "-show_entries",
            (
                "stream=codec_type,codec_name,width,height,r_frame_rate,"
                "sample_rate,channels:format=format_name,duration"
            ),
            "-of",
            "json",
            str(path),
        ],
        check=True,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    probe = json.loads(completed.stdout)
    streams = probe["streams"]
    video = next(
        (stream for stream in streams if stream["codec_type"] == "video"),
        None,
    )
    audio = next(
        (stream for stream in streams if stream["codec_type"] == "audio"),
        None,
    )
    duration_ns = _ns(float(probe["format"]["duration"]))
    format_name = str(probe["format"]["format_name"]).split(",")[0]
    if video is not None and kind_hint != "audio":
        fps_num, fps_den = (
            int(value) for value in video["r_frame_rate"].split("/")
        )
        return {
            "kind": "video",
            "format_name": format_name,
            "duration_ns": duration_ns,
            "width": int(video["width"]),
            "height": int(video["height"]),
            "fps_num": fps_num,
            "fps_den": fps_den,
            "codec": video.get("codec_name"),
        }
    if audio is None:
        raise RuntimeError(f"no supported media stream: {path}")
    return {
        "kind": "audio",
        "format_name": format_name,
        "duration_ns": duration_ns,
        "sample_rate": int(audio["sample_rate"]),
        "channels": int(audio["channels"]),
        "codec": audio.get("codec_name"),
    }


def _catalog(project: Path) -> tuple[str | None, dict[str, dict[str, Any]]]:
    path = project / "data/assets/catalog.json"
    if not path.is_file():
        return None, {}
    digest, _size = _sha(path)
    raw = json.loads(path.read_text(encoding="utf-8"))
    return digest, {str(item["path"]): item for item in raw.get("assets", [])}


def _literal(value: Any) -> str:
    return repr(value)


def _blob_ref(path: Path) -> dict[str, Any]:
    sha256, size = _sha(path)
    return {"sha256": sha256, "size": size}


def _asset_expression(
    *,
    asset_id: str,
    logical_path: str,
    sha256: str,
    size: int,
    media: dict[str, Any],
    catalog_ref: dict[str, Any] | None,
    catalog_entry: dict[str, Any] | None,
    is_voice: bool,
    script_ref: dict[str, Any] | None,
    voice_receipt_ref: dict[str, Any] | None,
    music_license_ref: dict[str, Any] | None,
    derived_source_ref: dict[str, Any] | None,
) -> str:
    catalog_matches = (
        catalog_ref is not None
        and catalog_entry is not None
        and catalog_entry.get("sha256") == sha256
        and int(catalog_entry.get("size", -1)) == size
    )
    if derived_source_ref is not None:
        provenance = {
            "origin": "derived",
            "capture_method": "v3_static_raster_port",
            "logical_source": logical_path,
            "provider_receipt_ref": derived_source_ref,
        }
        license_payload = {
            "license_id": "derived-from-legacy-source-license-unverified",
            "attribution_required": False,
            "redistribution_allowed": False,
        }
        approval = {
            "status": "validated",
            "evidence_refs": (derived_source_ref,),
        }
    elif is_voice:
        if script_ref is None or voice_receipt_ref is None:
            raise RuntimeError(f"voice evidence is incomplete: {logical_path}")
        provenance = {
            "origin": "recorded",
            "capture_method": "voice_take",
            "logical_source": logical_path,
            "state_id": f"legacy:{logical_path}",
            "script_ref": script_ref,
            "provider_receipt_ref": voice_receipt_ref,
        }
        license_payload = {
            "license_id": "creator-owned-voice",
            "attribution_required": False,
        }
    elif logical_path.startswith("data/infographics/"):
        provenance = {
            "origin": "generated",
            "capture_method": "legacy_generated_port",
            "logical_source": logical_path,
        }
        license_payload = {
            "license_id": "legacy-generated-license-unverified",
            "attribution_required": False,
            "redistribution_allowed": False,
        }
    elif logical_path.startswith("data/footage/"):
        provenance = {
            "origin": "migrated",
            "capture_method": "legacy_capture_unverified",
            "logical_source": logical_path,
        }
        license_payload = {
            "license_id": "legacy-capture-license-unverified",
            "attribution_required": False,
            "redistribution_allowed": False,
        }
    else:
        provenance = {
            "origin": "provided",
            "capture_method": "legacy_project_asset",
            "logical_source": logical_path,
        }
        license_payload = {
            "license_id": "legacy-license-unverified",
            "attribution_required": False,
            "redistribution_allowed": False,
        }
    if derived_source_ref is not None:
        approval = {
            "status": "validated",
            "evidence_refs": (derived_source_ref,),
        }
    else:
        evidence = (catalog_ref,) if catalog_matches else ()
        approval = {
            "status": "validated" if evidence else "pending",
            "evidence_refs": evidence,
            "reason": None if evidence else "no exact v3 migration evidence",
        }
    if (
        logical_path.endswith("first_day_in_a_loop.ogg")
        and music_license_ref is not None
    ):
        provenance = {
            "origin": "provided",
            "capture_method": "purchased_library",
            "logical_source": logical_path,
            "provider_receipt_ref": music_license_ref,
        }
        license_payload = {
            "license_id": "purchased-premium-royalty-free",
            "attribution_required": False,
        }
        approval = {
            "status": "approved",
            "evidence_refs": tuple(
                value
                for value in (
                    catalog_ref if catalog_matches else None,
                    music_license_ref,
                )
                if value is not None
            ),
        }
    return (
        "    AssetRevision(\n"
        f"        asset_id={asset_id!r},\n"
        f"        blob=BlobRef({sha256!r}, {size}),\n"
        f"        media=MediaFacts.from_payload({_literal(media)}),\n"
        f"        provenance=Provenance.from_payload({_literal(provenance)}),\n"
        f"        approval=Approval.from_payload({_literal(approval)}),\n"
        f"        license=License.from_payload({_literal(license_payload)}),\n"
        "    ),"
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--project", type=Path, required=True)
    parser.add_argument("--module", default="edit")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument("--production-id", required=True)
    parser.add_argument(
        "--kind", choices=("reel", "devlog", "capture_vo"), required=True
    )
    parser.add_argument("--story", required=True)
    parser.add_argument(
        "--legacy-artifact",
        type=Path,
        help="Frozen legacy output used only to record comparison evidence.",
    )
    parser.add_argument(
        "--render-current-reference",
        type=Path,
        help=(
            "Render the current v2 graph into an isolated reference artifact "
            "before freezing comparison evidence."
        ),
    )
    args = parser.parse_args()

    project = args.project.resolve()
    sys.path.insert(0, str(project))
    module = importlib.import_module(args.module)
    edit = module.EDIT
    timeline = build_timeline(edit, probe=True)
    if args.render_current_reference is not None:
        reference = (
            args.render_current_reference
            if args.render_current_reference.is_absolute()
            else project / args.render_current_reference
        )
        reference.parent.mkdir(parents=True, exist_ok=True)
        reference_timeline = timeline.model_copy(
            update={"output": str(reference.resolve())}
        )
        render_options = RenderOpts(
            quality="preview",
            workdir=reference.parent / f"{reference.stem}_beats",
        )
        render_beat_module.set_chunk_resolver(
            lambda beat_id, chunk_index: edit.beats[beat_id].chunks[chunk_index]
        )
        try:
            beat_files = {
                beat.id: render_beat(
                    beat,
                    reference_timeline.design,
                    None,
                    render_options,
                )
                for beat in reference_timeline.beats
            }
            assemble(reference_timeline, beat_files, render_options)
        finally:
            render_beat_module.set_chunk_resolver(None)
        args.legacy_artifact = reference
    placement = {item.beat_id: item.t0 for item in timeline.placements}
    beat_by_id = {beat.id: beat for beat in timeline.beats}
    total_ns = max(
        (_ns(placement[beat.id] + beat.duration) for beat in timeline.beats),
        default=0,
    )
    _catalog_sha, catalog = _catalog(project)
    catalog_path = project / "data/assets/catalog.json"
    catalog_ref = _blob_ref(catalog_path) if catalog_path.is_file() else None
    music_license = project / "data/publish/music_license.md"
    music_license_ref = (
        _blob_ref(music_license) if music_license.is_file() else None
    )

    voice_script_bytes = {
        beat.audio: edit.beats[beat.id].vo.encode("utf-8")
        for beat in timeline.beats
    }
    paths: dict[str, str] = {}
    evidence_objects: dict[str, tuple[dict[str, Any], bytes]] = {}
    derived_source_receipts: dict[str, dict[str, Any]] = {}
    media_cache: dict[tuple[str, str | None], dict[str, Any]] = {}
    rasterizer_digest = hashlib.sha256()
    rasterizer_root = Path(render_chunk_png.__code__.co_filename).parent
    for rasterizer_source in sorted(rasterizer_root.rglob("*.py")):
        rasterizer_digest.update(
            rasterizer_source.relative_to(rasterizer_root).as_posix().encode("utf-8")
        )
        rasterizer_digest.update(rasterizer_source.read_bytes())
    rasterizer_sha256 = rasterizer_digest.hexdigest()

    def inspect(logical: str, kind_hint: str | None = None) -> dict[str, Any]:
        key = (logical, kind_hint)
        if key not in media_cache:
            media_cache[key] = _media(project / logical, kind_hint)
        return media_cache[key]

    def register(logical: str) -> str:
        if logical not in paths:
            normalized = logical.replace("\\", "/").casefold()
            slug = re.sub(r"[^a-z0-9]+", ".", normalized).strip(".")
            path_hash = hashlib.sha256(normalized.encode()).hexdigest()[:8]
            paths[logical] = f"asset.{slug}.{path_hash}"
        return paths[logical]

    raster_root = project / "data/v3_port/raster"
    raster_root.mkdir(parents=True, exist_ok=True)
    def publish_evidence(raw: bytes) -> dict[str, Any]:
        sha256 = hashlib.sha256(raw).hexdigest()
        ref = {"sha256": sha256, "size": len(raw)}
        evidence_objects[sha256] = (ref, raw)
        return ref

    voice_evidence: dict[
        str, tuple[dict[str, Any], dict[str, Any]]
    ] = {}
    for logical, script_bytes in voice_script_bytes.items():
        script_ref = publish_evidence(script_bytes)
        media_ref = _blob_ref(project / logical)
        receipt_bytes = json.dumps(
            {
                "schema": "studio_v3.legacy_voice_port",
                "version": 1,
                "logical_source": logical,
                "media": media_ref,
                "script": script_ref,
                "capture_audit": "unavailable",
                "approval": "pending",
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        voice_evidence[logical] = (
            script_ref,
            publish_evidence(receipt_bytes),
        )

    def source_receipt(
        payload: dict[str, Any],
    ) -> tuple[str, dict[str, Any]]:
        raw = json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        ref = publish_evidence(raw)
        return ref["sha256"], ref

    def register_overlay_raster(beat_id: str, overlay: Any) -> str:
        chunk = edit.beats[beat_id].chunks[overlay.chunk_index]
        receipt, receipt_ref = source_receipt(
            {
                "kind": "legacy_chunk_raster",
                "chunk": chunk.model_dump(mode="json"),
                "design": edit.design.model_dump(mode="json"),
                "rasterizer_sha256": rasterizer_sha256,
            }
        )
        logical = f"data/v3_port/raster/overlay-{receipt}.png"
        destination = project / logical
        render_chunk_png(chunk, edit.design, destination)
        derived_source_receipts[logical] = receipt_ref
        register(logical)
        return logical

    def register_caption_raster(text: str) -> str:
        receipt, receipt_ref = source_receipt(
            {
                "kind": "legacy_caption_raster",
                "text": text,
                "design": edit.design.model_dump(mode="json"),
                "rasterizer_sha256": rasterizer_sha256,
            }
        )
        logical = f"data/v3_port/raster/caption-{receipt}.png"
        destination = project / logical
        render_caption_png(text, edit.design, destination)
        derived_source_receipts[logical] = receipt_ref
        register(logical)
        return logical

    visual_rows: list[str] = []

    def effective_geometry(segment: Any) -> Any:
        geometry = segment.geometry
        if (
            segment.ken_burns
            and geometry is not None
            and geometry.fit == "contain"
        ):
            return geometry.resolve(
                fit="cover",
                anchor_x=geometry.anchor_x,
                anchor_y=geometry.anchor_y,
                source_width=geometry.source_width,
                source_height=geometry.source_height,
                output_width=timeline.design.resolution[0],
                output_height=timeline.design.resolution[1],
            )
        return geometry

    for beat in timeline.beats:
        beat_start = placement[beat.id]
        incoming = None
        for segment in beat.segments:
            asset_id = register(segment.src)
            transition = incoming.kind if incoming is not None else "cut"
            transition_ns = (
                _ns(incoming.dur) if transition != "cut" else 0
            )
            start_ns = _ns(beat_start + segment.t0)
            duration_ns = min(
                _ns(
                    segment.t1
                    - segment.t0
                    + (
                        segment.xfade.dur
                        if segment.xfade is not None
                        and segment.xfade.kind != "cut"
                        else 0.0
                    )
                ),
                total_ns - start_ns,
            )
            facts = inspect(segment.src)
            source_duration = facts.get("duration_ns")
            freeze_at_end = (
                not segment.loop
                and source_duration is not None
                and _ns(segment.offset) + duration_ns > source_duration
            )
            geometry = effective_geometry(segment)
            geometry_expression = ""
            if (
                geometry is not None
                and geometry.source_width is not None
                and geometry.source_height is not None
                and geometry.scaled_width is not None
                and geometry.scaled_height is not None
            ):
                geometry_expression = (
                    ", geometry=MediaGeometry("
                    f"{geometry.source_width}, {geometry.source_height}, "
                    f"{geometry.scaled_width}, {geometry.scaled_height}, "
                    f"crop_x={geometry.crop_x!r}, crop_y={geometry.crop_y!r}, "
                    f"pad_x={geometry.pad_x!r}, pad_y={geometry.pad_y!r})"
                )
            visual_rows.append(
                "        MediaLayer("
                f"{asset_id!r}, {start_ns}, "
                f"{duration_ns}, 0, 0, 0, "
                f"{timeline.design.resolution[0]}, "
                f"{timeline.design.resolution[1]}, fit={segment.fit!r}, "
                f"source_start_ns={_ns(segment.offset)}, loop={segment.loop!r}, "
                f"freeze_at_end={freeze_at_end!r}, "
                f"ken_burns={segment.ken_burns!r}, transition={transition!r}, "
                f"transition_ns={transition_ns}, "
                f"transition_intent={segment.transition_intent!r}"
                f"{geometry_expression}),"
            )
            incoming = segment.xfade
        for overlay in beat.overlays:
            logical = register_overlay_raster(beat.id, overlay)
            transition = (
                overlay.transition_in.kind
                if overlay.transition_in is not None
                else "fade"
            )
            transition_ns = (
                _ns(overlay.transition_in.dur)
                if overlay.transition_in is not None
                and overlay.transition_in.kind != "cut"
                else (1_000_000 if transition == "cut" else min(
                    200_000_000, _ns(overlay.t1 - overlay.t0) // 4
                ))
            )
            if transition == "cut":
                transition_ns = 0
            start_ns = _ns(beat_start + overlay.t0)
            duration_ns = min(
                _ns(overlay.t1 - overlay.t0), total_ns - start_ns
            )
            animation_expressions = ", ".join(
                "Animation("
                f"prop={animation.prop!r}, "
                f"start_milli={round(animation.start * 1000)}, "
                f"end_milli={round(animation.end * 1000)}, "
                f"ease={animation.ease!r}, "
                f"start_ns={_ns(beat_start + animation.t0)}, "
                f"end_ns={_ns(beat_start + animation.t1)})"
                for animation in overlay.anims
            )
            animations = (
                f", animations=({animation_expressions},)"
                if animation_expressions
                else ""
            )
            visual_rows.append(
                "        MediaLayer("
                f"{paths[logical]!r}, {start_ns}, {duration_ns}, "
                f"{20 + overlay.z}, 0, 0, "
                f"{timeline.design.resolution[0]}, "
                f"{timeline.design.resolution[1]}, fit='stretch', "
                f"transition={transition!r}, transition_ns={transition_ns}, "
                f"fade_out_ns={min(200_000_000, duration_ns // 5)}"
                f"{animations}),"
            )
        for caption in beat.captions:
            logical = register_caption_raster(caption.text)
            start_ns = _ns(beat_start + caption.t0)
            duration_ns = min(
                _ns(caption.t1 - caption.t0), total_ns - start_ns
            )
            visual_rows.append(
                "        MediaLayer("
                f"{paths[logical]!r}, {start_ns}, {duration_ns}, "
                f"100, 0, 0, {timeline.design.resolution[0]}, "
                f"{timeline.design.resolution[1]}, fit='stretch', "
                f"transition='fade', transition_ns={min(80_000_000, duration_ns * 2 // 5)}, "
                f"fade_out_ns={min(80_000_000, duration_ns * 2 // 5)}),"
            )

    audio_rows: list[str] = []
    for beat in timeline.beats:
        asset_id = register(beat.audio)
        start_ns = _ns(placement[beat.id])
        duration_ns = min(_ns(beat.duration), total_ns - start_ns)
        audio_rows.append(
            "        AudioClip("
            f"{asset_id!r}, {start_ns}, {duration_ns}, "
            "role='voice'),"
        )
    for sfx, sfx_start_ns, sfx_duration_ns in _sfx_specs(
        timeline,
        placement,
        total_ns,
        inspect,
    ):
        asset_id = register(sfx.src)
        audio_rows.append(
            "        AudioClip("
            f"{asset_id!r}, {sfx_start_ns}, "
            f"{sfx_duration_ns}, "
            f"gain_db_milli={round(sfx.gain_db * 1000)}, "
            "role='sfx'),"
        )
    video_fade_rows: list[str] = []
    for index, beat in enumerate(timeline.beats[:-1]):
        transition = beat.transition_out
        if (
            transition is None
            or transition.kind == "cut"
            or transition.dur <= 0
        ):
            continue
        half_ns = _ns(transition.dur / 2)
        boundary_ns = _ns(placement[beat.id] + beat.duration)
        next_start_ns = _ns(placement[timeline.beats[index + 1].id])
        video_fade_rows.extend(
            (
                "        VideoFade("
                f"'out', {boundary_ns - half_ns}, {half_ns}),",
                "        VideoFade("
                f"'in', {next_start_ns}, {half_ns}),",
            )
        )
    for music in timeline.mix.music:
        asset_id = register(music.src)
        start_ns = _ns(music.t0)
        duration_ns = min(_ns(music.t1 - music.t0), total_ns - start_ns)
        audio_rows.append(
            "        AudioClip("
            f"{asset_id!r}, {start_ns}, {duration_ns}, "
            f"source_start_ns={_ns(music.offset)}, "
            f"gain_db_milli={round(music.gain_db * 1000)}, "
            f"fade_in_ns={_ns(music.fade_in)}, "
            f"fade_out_ns={_ns(music.fade_out)}, role='music', "
            f"duck={music.duck!r}, loop=True),"
        )

    asset_rows: list[str] = []
    emitted_asset_ids: set[str] = set()
    for logical_path, asset_id in sorted(paths.items()):
        if asset_id in emitted_asset_ids:
            continue
        emitted_asset_ids.add(asset_id)
        source = project / logical_path
        sha256, size = _sha(source)
        catalog_entry = catalog.get(logical_path)
        if (
            catalog_ref is not None
            and catalog_entry is not None
            and catalog_entry.get("sha256") == sha256
            and int(catalog_entry.get("size", -1)) == size
        ):
            evidence_objects[catalog_ref["sha256"]] = (
                catalog_ref,
                catalog_path.read_bytes(),
            )
        if (
            music_license_ref is not None
            and logical_path.endswith("first_day_in_a_loop.ogg")
        ):
            evidence_objects[music_license_ref["sha256"]] = (
                music_license_ref,
                music_license.read_bytes(),
            )
        asset_rows.append(
            _asset_expression(
                asset_id=asset_id,
                logical_path=logical_path,
                sha256=sha256,
                size=size,
                media=inspect(
                    logical_path,
                    "audio" if logical_path in voice_script_bytes else None,
                ),
                catalog_ref=catalog_ref,
                catalog_entry=catalog_entry,
                is_voice=logical_path in voice_script_bytes,
                script_ref=(
                    voice_evidence[logical_path][0]
                    if logical_path in voice_evidence
                    else None
                ),
                voice_receipt_ref=(
                    voice_evidence[logical_path][1]
                    if logical_path in voice_evidence
                    else None
                ),
                music_license_ref=music_license_ref,
                derived_source_ref=derived_source_receipts.get(logical_path),
            )
        )

    evidence_rows = [
        f"    (BlobRef({ref['sha256']!r}, {ref['size']}), {raw!r}),"
        for ref, raw in (
            evidence_objects[sha256]
            for sha256 in sorted(evidence_objects)
        )
    ]
    source = f'''"""Generated static Studio v3 port; no legacy runtime imports."""

from dlstudio.assets.api import Approval, AssetRevision, License, MediaFacts, Provenance
from dlstudio.authoring.api import Animation, AudioClip, Edit, MediaGeometry, MediaLayer, VideoFade
from dlstudio.foundation.api import BlobRef

EVIDENCE_OBJECTS = (
{chr(10).join(evidence_rows)}
)

MIGRATION_ASSETS = (
{chr(10).join(asset_rows)}
)

EDIT = Edit(
    production_id={args.production_id!r},
    width={timeline.design.resolution[0]},
    height={timeline.design.resolution[1]},
    fps_num={timeline.design.fps},
    fps_den=1,
    duration_ns={total_ns},
    background={timeline.design.palette.tokens.get("bg", "#000000")!r},
    visuals=(
{chr(10).join(visual_rows)}
    ),
    audio=(
{chr(10).join(audio_rows)}
    ),
    video_fades=(
{chr(10).join(video_fade_rows)}
    ),
    target_lufs_milli={round(timeline.mix.target_lufs * 1000)},
    true_peak_db_milli={round(timeline.mix.true_peak_db * 1000)},
    duck_amount_db_milli={round(timeline.mix.duck.amount_db * 1000)},
    duck_threshold_db_milli={round(timeline.mix.duck.threshold_db * 1000)},
    duck_attack_ms={timeline.mix.duck.attack_ms},
    duck_release_ms={timeline.mix.duck.release_ms},
    standalone_story={args.story!r},
    kind={args.kind!r},
)
'''
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(source, encoding="utf-8", newline="\n")
    summary = {
        "schema": "studio_v3.legacy_port",
        "version": 1,
        "production_id": args.production_id,
        "duration_ns": total_ns,
        "beats": len(timeline.beats),
        "segments": sum(len(beat.segments) for beat in timeline.beats),
        "overlays": sum(len(beat.overlays) for beat in timeline.beats),
        "captions": sum(len(beat.captions) for beat in timeline.beats),
        "asset_count": len(asset_rows),
        "warnings": timeline.warnings,
        "diagnostics": [
            item.model_dump(mode="json") for item in timeline.diagnostics
        ],
        "canvas": {
            "width": timeline.design.resolution[0],
            "height": timeline.design.resolution[1],
            "fps_num": timeline.design.fps,
            "fps_den": 1,
        },
        "assets": [],
        "beat_graph": [
            {
                "beat_id": beat.id,
                "start_ns": _ns(placement[beat.id]),
                "duration_ns": _ns(beat.duration),
                "audio_sha256": _sha(project / beat.audio)[0],
                "transition_out": (
                    None
                    if beat.transition_out is None
                    else beat.transition_out.model_dump(mode="json")
                ),
                "segments": [
                    {
                        "kind": segment.kind,
                        "sha256": _sha(project / segment.src)[0],
                        "start_ns": _ns(placement[beat.id] + segment.t0),
                        "duration_ns": _ns(segment.t1 - segment.t0),
                        "source_start_ns": _ns(segment.offset),
                        "fit": segment.fit,
                        "geometry": (
                            None
                            if effective_geometry(segment) is None
                            else effective_geometry(segment).model_dump(mode="json")
                        ),
                        "loop": segment.loop,
                        "ken_burns": segment.ken_burns,
                        "transition_intent": segment.transition_intent,
                        "xfade": (
                            None
                            if segment.xfade is None
                            else segment.xfade.model_dump(mode="json")
                        ),
                    }
                    for segment in beat.segments
                ],
                "overlays": [
                    {
                        "start_ns": _ns(placement[beat.id] + overlay.t0),
                        "duration_ns": _ns(overlay.t1 - overlay.t0),
                        "z": overlay.z,
                        "public_text": overlay.public_text,
                        "content_hash": overlay.content_hash,
                        "asset_paths": overlay.asset_paths,
                        "anims": [
                            anim.model_dump(mode="json") for anim in overlay.anims
                        ],
                        "transition_in": (
                            None
                            if overlay.transition_in is None
                            else overlay.transition_in.model_dump(mode="json")
                        ),
                        "raster_logical_path": register_overlay_raster(
                            beat.id, overlay
                        ),
                        "raster_sha256": _sha(
                            project / register_overlay_raster(beat.id, overlay)
                        )[0],
                    }
                    for overlay in beat.overlays
                ],
                "captions": [
                    {
                        "text": caption.text,
                        "start_ns": _ns(placement[beat.id] + caption.t0),
                        "duration_ns": _ns(caption.t1 - caption.t0),
                        "raster_logical_path": register_caption_raster(
                            caption.text
                        ),
                        "raster_sha256": _sha(
                            project / register_caption_raster(caption.text)
                        )[0],
                    }
                    for caption in beat.captions
                ],
            }
            for beat in timeline.beats
        ],
        "music_graph": [
            {
                **music.model_dump(mode="json"),
                "sha256": _sha(project / music.src)[0],
            }
            for music in timeline.mix.music
        ],
        "mix": {
            "target_lufs_milli": round(timeline.mix.target_lufs * 1000),
            "true_peak_db_milli": round(timeline.mix.true_peak_db * 1000),
            "duck": timeline.mix.duck.model_dump(mode="json"),
        },
    }
    if args.legacy_artifact is not None:
        legacy_artifact = (
            args.legacy_artifact
            if args.legacy_artifact.is_absolute()
            else project / args.legacy_artifact
        )
        artifact_sha, artifact_size = _sha(legacy_artifact)
        duration = total_ns / 1_000_000_000
        evidence_times = [
            0.5,
            duration * 0.25,
            duration * 0.5,
            duration * 0.75,
            max(0.5, duration - 0.5),
        ]
        transition_intervals_ns: list[tuple[int, int]] = []
        transition_group_specs: list[dict[str, Any]] = []
        for beat in timeline.beats:
            for segment in beat.segments:
                transition = segment.xfade
                if (
                    transition is None
                    or transition.kind == "cut"
                    or transition.dur <= 0
                ):
                    continue
                start_ns = _ns(placement[beat.id] + segment.t1)
                end_ns = _ns(
                    placement[beat.id] + segment.t1 + transition.dur
                )
                transition_intervals_ns.append((start_ns, end_ns))
                transition_group_specs.append(
                    {
                        "kind": f"xfade:{transition.kind}",
                        "start_ns": start_ns,
                        "end_ns": end_ns,
                    }
                )
        for index, beat in enumerate(timeline.beats[:-1]):
            transition = beat.transition_out
            if (
                transition is None
                or transition.kind == "cut"
                or transition.dur <= 0
            ):
                continue
            half_ns = _ns(transition.dur / 2)
            boundary_ns = _ns(placement[beat.id] + beat.duration)
            next_start_ns = _ns(placement[timeline.beats[index + 1].id])
            transition_intervals_ns.extend(
                (
                    (boundary_ns - half_ns, boundary_ns),
                    (next_start_ns, next_start_ns + half_ns),
                )
            )
            transition_group_specs.extend(
                (
                    {
                        "kind": "video_fade:out",
                        "start_ns": boundary_ns - half_ns,
                        "end_ns": boundary_ns,
                    },
                    {
                        "kind": "video_fade:in",
                        "start_ns": next_start_ns,
                        "end_ns": next_start_ns + half_ns,
                    },
                )
            )
        overlay_times = [
            placement[beat.id] + (overlay.t0 + overlay.t1) / 2
            for beat in timeline.beats
            for overlay in beat.overlays
        ][:3]
        caption_times = [
            placement[beat.id] + (caption.t0 + caption.t1) / 2
            for beat in timeline.beats
            for caption in beat.captions
        ][:3]
        fps_num = timeline.design.fps
        fps_den = 1
        all_frames = _frame_series(legacy_artifact)
        output_frame_count = math.ceil(
            total_ns * fps_num / (1_000_000_000 * fps_den)
        )
        sample_kinds: dict[int, str] = {}
        for kind, times in (
            ("core", evidence_times),
            ("overlay", overlay_times),
            ("caption", caption_times),
        ):
            for value in times:
                frame_index = round(value * fps_num / fps_den)
                if 0 <= frame_index < output_frame_count:
                    sample_kinds[frame_index] = kind
        for start_ns, end_ns in transition_intervals_ns:
            for frame_index in _interval_frame_indices(
                start_ns,
                min(end_ns, total_ns),
                fps_num=fps_num,
                fps_den=fps_den,
            ):
                if frame_index < output_frame_count:
                    sample_kinds[frame_index] = "transition"
        transition_groups: list[dict[str, Any]] = []
        for group in transition_group_specs:
            indices = [
                frame_index
                for frame_index in _interval_frame_indices(
                    int(group["start_ns"]),
                    min(int(group["end_ns"]), total_ns),
                    fps_num=fps_num,
                    fps_den=fps_den,
                )
                if frame_index < output_frame_count
            ]
            if not indices:
                continue
            before = max(0, indices[0] - 1)
            after = min(output_frame_count - 1, indices[-1] + 1)
            sample_kinds.setdefault(before, "transition_guard")
            sample_kinds.setdefault(after, "transition_guard")
            transition_groups.append(
                {
                    **group,
                    "frame_indices": indices,
                    "before_frame_index": before,
                    "after_frame_index": after,
                }
            )
        transition_frame_indices = sorted(
            frame_index
            for frame_index, kind in sample_kinds.items()
            if kind == "transition"
        )
        summary["legacy_artifact"] = {
            "logical_path": legacy_artifact.relative_to(project).as_posix(),
            "sha256": artifact_sha,
            "size": artifact_size,
            "frames": [
                {
                    **_timeline_frame_evidence(
                        all_frames,
                        frame_index=frame_index,
                        fps_num=fps_num,
                        fps_den=fps_den,
                    ),
                    "sample_kind": sample_kinds[frame_index],
                }
                for frame_index in sorted(sample_kinds)
            ],
            "transition_frame_indices": transition_frame_indices,
            "transition_groups": transition_groups,
            "audio": _audio_evidence(legacy_artifact),
        }
    seen_baseline_hashes: set[str] = set()
    for logical_path in sorted(paths):
        sha256 = _sha(project / logical_path)[0]
        if sha256 not in seen_baseline_hashes:
            summary["assets"].append(
                {"logical_path": logical_path, "sha256": sha256}
            )
            seen_baseline_hashes.add(sha256)
    if args.baseline is not None:
        args.baseline.parent.mkdir(parents=True, exist_ok=True)
        args.baseline.write_text(
            json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True)
            + "\n",
            encoding="utf-8",
            newline="\n",
        )
    print(json.dumps(summary, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
