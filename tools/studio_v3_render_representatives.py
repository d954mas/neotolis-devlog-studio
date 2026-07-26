"""Compile representative v3 ports and render each IR in a fresh process."""

from __future__ import annotations

import argparse
import array
import base64
import bisect
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
from pathlib import Path

from dlstudio.authoring.compiler import compile_edit
from dlstudio.authoring.loader import load_edit


def _hash(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
    return digest.hexdigest()


def _frame_evidence_from_raw(raw: bytes) -> dict[str, object]:
    if len(raw) != 64 * 36:
        raise RuntimeError("invalid frame payload")
    bits = 0
    for row in range(36):
        offset = row * 64
        for column in range(63):
            bits = (bits << 1) | (
                raw[offset + column] > raw[offset + column + 1]
            )
    return {
        "gray": raw,
        "sha256": hashlib.sha256(raw).hexdigest(),
        "dhash": f"{bits:0567x}",
    }


def _frame_series(
    path: Path,
) -> list[tuple[int, dict[str, object]]]:
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
        raise RuntimeError("frame-series extraction failed")
    frames: list[dict[str, object]] = []
    for index in range(len(completed.stdout) // frame_size):
        raw = completed.stdout[index * frame_size : (index + 1) * frame_size]
        frames.append(_frame_evidence_from_raw(raw))
    stderr = completed.stderr.decode("utf-8", errors="replace")
    pts_ns = [
        round(float(match.group(1)) * 1_000_000_000)
        for match in re.finditer(r"showinfo.*?pts_time:\s*([0-9.eE+-]+)", stderr)
    ]
    if len(pts_ns) != len(frames):
        raise RuntimeError(
            "frame timestamps do not match decoded frame payloads"
        )
    return list(zip(pts_ns, frames, strict=True))


def _nearest_frame(
    frames: list[tuple[int, dict[str, object]]],
    target_ns: int,
) -> tuple[int, dict[str, object]]:
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


def _interval_frame_indices(
    start_ns: int,
    end_ns: int,
    *,
    fps_num: int,
    fps_den: int,
) -> range:
    denominator = 1_000_000_000 * fps_den
    first = math.ceil(start_ns * fps_num / denominator)
    stop = math.ceil(end_ns * fps_num / denominator)
    return range(max(0, first), max(0, stop))


def _audio_pcm(path: Path, rate: int = 1000) -> array.array[int]:
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
            str(rate),
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
    return samples


def _aligned_audio_correlation(
    reference: array.array[int],
    actual: array.array[int],
    *,
    max_lag: int = 20,
    stride: int = 5,
) -> dict[str, object]:
    best: tuple[float, int, float] | None = None
    for lag in range(-max_lag, max_lag + 1):
        ref_start = max(0, lag)
        actual_start = max(0, -lag)
        count = min(
            len(reference) - ref_start,
            len(actual) - actual_start,
        )
        if count <= 0:
            continue
        ref_values = reference[ref_start : ref_start + count : stride]
        actual_values = actual[actual_start : actual_start + count : stride]
        n = len(ref_values)
        if n == 0:
            continue
        sum_ref = sum(ref_values)
        sum_actual = sum(actual_values)
        sum_ref_sq = sum(value * value for value in ref_values)
        sum_actual_sq = sum(value * value for value in actual_values)
        sum_product = sum(
            left * right
            for left, right in zip(ref_values, actual_values, strict=True)
        )
        covariance = sum_product - sum_ref * sum_actual / n
        variance_ref = sum_ref_sq - sum_ref * sum_ref / n
        variance_actual = sum_actual_sq - sum_actual * sum_actual / n
        correlation = covariance / max(
            1.0, (variance_ref * variance_actual) ** 0.5
        )
        error_rms = (
            sum(
                (left - right) ** 2
                for left, right in zip(ref_values, actual_values, strict=True)
            )
            / n
        ) ** 0.5
        candidate = (correlation, -abs(lag), -error_rms)
        if best is None or candidate > (best[0], -abs(best[1]), -best[2]):
            best = (correlation, lag, error_rms)
    if best is None:
        raise RuntimeError("audio alignment has no comparable samples")
    return {
        "correlation": round(best[0], 6),
        "lag_ms": best[1],
        "error_rms_s16": round(best[2], 3),
    }


def _audio_fingerprint(path: Path) -> dict[str, object]:
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
        "pcm_sha256": hashlib.sha256(completed.stdout).hexdigest(),
        "sample_count": len(samples),
        "rms_s16": round(rms, 3),
        "integrated_lufs": float(measured["input_i"]),
        "true_peak_dbfs": float(measured["input_tp"]),
    }


def _hamming(left: str, right: str) -> int:
    return (int(left, 16) ^ int(right, 16)).bit_count()


def _mae(left: bytes, right: bytes) -> float:
    return sum(
        abs(left_value - right_value)
        for left_value, right_value in zip(left, right, strict=True)
    ) / len(left)


def _mean_gray(frame: bytes) -> float:
    return sum(frame) / len(frame)


def _anti_cut_group(
    group: dict[str, object],
    references: dict[int, bytes],
    actuals: dict[int, bytes],
) -> dict[str, object]:
    indices = [int(value) for value in group["frame_indices"]]
    reference_before = references[int(group["before_frame_index"])]
    reference_after = references[int(group["after_frame_index"])]
    actual_before = actuals[int(group["before_frame_index"])]
    actual_after = actuals[int(group["after_frame_index"])]
    discriminating = 0
    discriminating_indices: list[int] = []
    for frame_index in indices:
        reference = references[frame_index]
        separation = min(
            _mae(reference, reference_before),
            _mae(reference, reference_after),
        )
        if separation < 8.0:
            continue
        discriminating += 1
        discriminating_indices.append(frame_index)
    required = max(1, math.ceil(len(indices) * 0.3))
    reference_endpoint_separation = _mae(
        reference_before, reference_after
    )
    actual_endpoint_separation = _mae(actual_before, actual_after)
    reference_direction_delta = (
        _mean_gray(references[indices[-1]])
        - _mean_gray(references[indices[0]])
    )
    kind = str(group["kind"])
    direction_matches = (
        reference_direction_delta >= 8.0
        if kind == "video_fade:in"
        else (
            reference_direction_delta <= -8.0
            if kind == "video_fade:out"
            else True
        )
    )
    observable = (
        discriminating >= required
        and reference_endpoint_separation >= 8.0
        and direction_matches
    )
    best_cut_distance = 0.0
    if observable:
        candidate_distances = []
        for cut_after in range(indices[0] - 1, indices[-1] + 1):
            candidate_distances.append(
                sum(
                    _mae(
                        actuals[frame_index],
                        (
                            reference_before
                            if frame_index <= cut_after
                            else reference_after
                        ),
                    )
                    for frame_index in discriminating_indices
                )
            )
        best_cut_distance = min(candidate_distances)
    passed = (
        not observable
        or best_cut_distance / discriminating >= 6.0
    )
    return {
        "kind": group["kind"],
        "start_ns": group["start_ns"],
        "end_ns": group["end_ns"],
        "frames": len(indices),
        "discriminating": discriminating,
        "required_discriminating": required,
        "observable": observable,
        "reference_endpoint_separation": round(
            reference_endpoint_separation, 4
        ),
        "reference_direction_delta": round(
            reference_direction_delta, 4
        ),
        "direction_matches": direction_matches,
        "actual_endpoint_separation": round(
            actual_endpoint_separation, 4
        ),
        "best_cut_distance": round(best_cut_distance, 4),
        "pass": passed,
    }


def _guard_integrity(
    guard_frames: list[dict[str, object]],
) -> dict[str, int | float | bool]:
    if not guard_frames:
        return {
            "frames": 0,
            "strong_matches": 0,
            "strong_ratio": 1.0,
            "mean_mae": 0.0,
            "max_mae": 0.0,
            "pass": True,
        }
    strong = [
        item
        for item in guard_frames
        if (
            float(item["mae_gray"]) <= 20.0
            or int(item["dhash_hamming"]) <= 250
            or float(item["global_ssim"]) >= 0.75
        )
    ]
    mean_mae = sum(
        float(item["mae_gray"]) for item in guard_frames
    ) / len(guard_frames)
    max_mae = max(float(item["mae_gray"]) for item in guard_frames)
    strong_ratio = len(strong) / len(guard_frames)
    return {
        "frames": len(guard_frames),
        "strong_matches": len(strong),
        "strong_ratio": round(strong_ratio, 6),
        "mean_mae": round(mean_mae, 4),
        "max_mae": round(max_mae, 4),
        "pass": (
            strong_ratio >= 0.7
            and mean_mae <= 45.0
            and max_mae <= 200.0
        ),
    }


def _global_ssim(left: bytes, right: bytes) -> float:
    count = len(left)
    mean_left = sum(left) / count
    mean_right = sum(right) / count
    variance_left = sum((value - mean_left) ** 2 for value in left) / count
    variance_right = sum((value - mean_right) ** 2 for value in right) / count
    covariance = sum(
        (lvalue - mean_left) * (rvalue - mean_right)
        for lvalue, rvalue in zip(left, right, strict=True)
    ) / count
    c1 = (0.01 * 255) ** 2
    c2 = (0.03 * 255) ** 2
    return (
        (2 * mean_left * mean_right + c1) * (2 * covariance + c2)
    ) / (
        (mean_left**2 + mean_right**2 + c1)
        * (variance_left + variance_right + c2)
    )


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--workspace", type=Path, required=True)
    parser.add_argument("--work", type=Path, required=True)
    parser.add_argument("--report", type=Path, required=True)
    args = parser.parse_args()
    workspace = args.workspace.resolve()
    work = args.work.resolve()
    work.mkdir(parents=True, exist_ok=True)
    objects = work / "objects"
    objects.mkdir(exist_ok=True)
    ports = {
        "vertical": workspace
        / "not_a_trolley_problem/reels/2026_07_18_reel_02/v3_port.py",
        "longform": workspace
        / "not_a_trolley_problem/devlogs/2026_07_22_devlog_01/v3_port.py",
        "capture_vo": workspace
        / "not_a_trolley_problem/devlogs/2026_07_17_devlog_01/v3_port.py",
    }
    baseline_paths = {
        "vertical": workspace
        / "docs/studio_v3/phase3/vertical_legacy_baseline.json",
        "longform": workspace
        / "docs/studio_v3/phase3/longform_legacy_baseline.json",
        "capture_vo": workspace
        / "docs/studio_v3/phase3/capture_vo_legacy_baseline.json",
    }
    entries: list[dict[str, object]] = []
    env = dict(os.environ)
    package_root = workspace / "common" / "dlstudio" / "src"
    env["PYTHONPATH"] = str(package_root)
    for name, port in ports.items():
        edit = load_edit(port)
        timeline = compile_edit(edit)
        baseline = json.loads(baseline_paths[name].read_text(encoding="utf-8"))
        for snapshot in timeline.assets:
            logical_source = snapshot.revision.provenance.logical_source
            if logical_source is None:
                raise RuntimeError(
                    f"representative {snapshot.ref.asset_id} has no logical source"
                )
            source = port.parent / logical_source
            if _hash(source) != snapshot.blob.sha256:
                raise RuntimeError(
                    f"representative {snapshot.ref.asset_id} source hash mismatch"
                )
            target = objects / snapshot.blob.sha256
            if not target.exists():
                shutil.copy2(source, target)
        ir = work / f"{name}.timeline.json"
        ir.write_bytes(timeline.canonical_bytes())
        output = work / f"{name}.mp4"
        completed = subprocess.run(
            [
                sys.executable,
                "-m",
                "dlstudio.rendering.worker",
                "--ir",
                str(ir),
                "--objects",
                str(objects),
                "--output",
                str(output),
                "--cache",
                str(work / "cache"),
            ],
            check=False,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            env=env,
        )
        if completed.returncode:
            raise RuntimeError(f"{name} render failed: {completed.stderr}")
        probe = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-show_entries",
                "stream=codec_type,width,height:format=duration",
                "-of",
                "json",
                str(output),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        actual_assets = sorted(
            snapshot.ref.asset_id for snapshot in timeline.assets
        )
        actual_visual_kinds = sorted(
            {instruction.kind for instruction in timeline.visuals}
        )
        actual_audio_assets = sorted(
            {instruction.asset.asset_id for instruction in timeline.audio}
        )
        expected_blob_hashes = sorted(
            item["sha256"] for item in baseline["assets"]
        )
        actual_blob_hashes = sorted(
            snapshot.blob.sha256 for snapshot in timeline.assets
        )
        expected_segments = [
            segment
            for beat in baseline["beat_graph"]
            for segment in beat["segments"]
        ]
        actual_segments = sorted(
            (
                instruction
                for instruction in timeline.visuals
                if instruction.kind == "media" and instruction.z == 0
            ),
            key=lambda item: (item.start_ns, item.z),
        )
        snapshot_by_ref = {
            snapshot.ref: snapshot for snapshot in timeline.assets
        }
        actual_rasters = sorted(
            (
                item.start_ns,
                item.duration_ns,
                item.z,
                snapshot_by_ref[item.asset].blob.sha256,
                item.transition,
                item.transition_ns,
                item.fade_out_ns,
                tuple(
                    (
                        animation.prop,
                        animation.start_milli,
                        animation.end_milli,
                        animation.ease,
                        animation.start_ns,
                        animation.end_ns,
                    )
                    for animation in item.animations
                ),
            )
            for item in timeline.visuals
            if item.kind == "media" and item.z > 0
        )
        expected_rasters = sorted(
            [
                (
                    item["start_ns"],
                    item["duration_ns"],
                    20 + item["z"],
                    item["raster_sha256"],
                    (
                        item["transition_in"]["kind"]
                        if item["transition_in"] is not None
                        else "fade"
                    ),
                    (
                        round(item["transition_in"]["dur"] * 1_000_000_000)
                        if item["transition_in"] is not None
                        and item["transition_in"]["kind"] != "cut"
                        else (
                            0
                            if item["transition_in"] is not None
                            else min(200_000_000, item["duration_ns"] // 4)
                        )
                    ),
                    min(200_000_000, item["duration_ns"] // 5),
                    tuple(
                        (
                            animation["prop"],
                            round(animation["start"] * 1000),
                            round(animation["end"] * 1000),
                            animation["ease"],
                            beat["start_ns"] + round(animation["t0"] * 1_000_000_000),
                            beat["start_ns"] + round(animation["t1"] * 1_000_000_000),
                        )
                        for animation in item["anims"]
                    ),
                )
                for beat in baseline["beat_graph"]
                for item in beat["overlays"]
            ]
            + [
                (
                    item["start_ns"],
                    item["duration_ns"],
                    100,
                    item["raster_sha256"],
                    "fade",
                    min(80_000_000, item["duration_ns"] * 2 // 5),
                    min(80_000_000, item["duration_ns"] * 2 // 5),
                    (),
                )
                for beat in baseline["beat_graph"]
                for item in beat["captions"]
            ]
        )
        expected_voice = sorted(
            (
                beat["start_ns"],
                beat["duration_ns"],
                beat["audio_sha256"],
            )
            for beat in baseline["beat_graph"]
        )
        actual_voice = sorted(
            (
                item.start_ns,
                item.duration_ns,
                snapshot_by_ref[item.asset].blob.sha256,
            )
            for item in timeline.audio
            if item.role == "voice"
        )
        expected_music = sorted(
            (
                round(item["t0"] * 1_000_000_000),
                round((item["t1"] - item["t0"]) * 1_000_000_000),
                round(item["offset"] * 1_000_000_000),
                round(item["gain_db"] * 1000),
                round(item["fade_in"] * 1_000_000_000),
                round(item["fade_out"] * 1_000_000_000),
                item["duck"],
                True,
                item["sha256"],
            )
            for item in baseline["music_graph"]
        )
        actual_music = sorted(
            (
                item.start_ns,
                item.duration_ns,
                item.source_start_ns,
                item.gain_db_milli,
                item.fade_in_ns,
                item.fade_out_ns,
                item.duck,
                item.loop,
                snapshot_by_ref[item.asset].blob.sha256,
            )
            for item in timeline.audio
            if item.role == "music"
        )
        frame_tolerance_ns = (
            1_000_000_000 * timeline.fps_den + timeline.fps_num - 1
        ) // timeline.fps_num

        def close(left: int, right: int) -> bool:
            return abs(left - right) <= frame_tolerance_ns

        incoming_transitions: list[dict[str, object] | None] = []
        expected_render_durations: list[int] = []
        for beat in baseline["beat_graph"]:
            incoming: dict[str, object] | None = None
            for segment in beat["segments"]:
                incoming_transitions.append(incoming)
                outgoing = segment["xfade"]
                expected_render_durations.append(
                    segment["duration_ns"]
                    + (
                        round(outgoing["dur"] * 1_000_000_000)
                        if outgoing is not None and outgoing["kind"] != "cut"
                        else 0
                    )
                )
                incoming = outgoing
        exact_segments = len(actual_segments) == len(expected_segments) and all(
            (
                close(actual.start_ns, expected["start_ns"])
                and close(actual.duration_ns, render_duration)
                and snapshot_by_ref[actual.asset].blob.sha256
                == expected["sha256"]
                and close(
                    actual.source_start_ns, expected["source_start_ns"]
                )
                and actual.fit == expected["fit"]
                and actual.loop == expected["loop"]
                and actual.ken_burns == expected["ken_burns"]
                and actual.transition
                == ("cut" if incoming is None else incoming["kind"])
                and close(
                    actual.transition_ns,
                    (
                        0
                        if incoming is None or incoming["kind"] == "cut"
                        else round(incoming["dur"] * 1_000_000_000)
                    ),
                )
                and actual.transition_intent == expected["transition_intent"]
                and (
                    actual.geometry.as_payload()
                    if actual.geometry is not None
                    else None
                )
                == (
                    None
                    if expected["geometry"] is None
                    else {
                        key: expected["geometry"][key]
                        for key in (
                            "source_width",
                            "source_height",
                            "scaled_width",
                            "scaled_height",
                            "crop_x",
                            "crop_y",
                            "pad_x",
                            "pad_y",
                        )
                    }
                )
            )
            for actual, expected, render_duration, incoming in zip(
                actual_segments,
                expected_segments,
                expected_render_durations,
                incoming_transitions,
                strict=True,
            )
        )
        exact_voice = len(actual_voice) == len(expected_voice) and all(
            close(actual[0], expected[0])
            and close(actual[1], expected[1])
            and actual[2] == expected[2]
            for actual, expected in zip(
                actual_voice, expected_voice, strict=True
            )
        )
        exact_music = len(actual_music) == len(expected_music) and all(
            close(actual[0], expected[0])
            and close(actual[1], expected[1])
            and close(actual[2], expected[2])
            and actual[3:] == expected[3:]
            for actual, expected in zip(
                actual_music, expected_music, strict=True
            )
        )
        actual_video_fades = [
            (
                fade.direction,
                fade.start_ns,
                fade.duration_ns,
                fade.color,
            )
            for fade in timeline.video_fades
        ]
        expected_video_fades: list[tuple[str, int, int, str]] = []
        for index, beat in enumerate(baseline["beat_graph"][:-1]):
            transition = beat["transition_out"]
            if (
                transition is None
                or transition["kind"] == "cut"
                or transition["dur"] <= 0
            ):
                continue
            half_ns = round(transition["dur"] * 500_000_000)
            boundary_ns = beat["start_ns"] + beat["duration_ns"]
            next_start_ns = baseline["beat_graph"][index + 1]["start_ns"]
            expected_video_fades.extend(
                (
                    ("out", boundary_ns - half_ns, half_ns, "black"),
                    ("in", next_start_ns, half_ns, "black"),
                )
            )
        legacy_frames = baseline["legacy_artifact"]["frames"]
        output_frames = _frame_series(output)
        max_frame_index = (
            math.ceil(
                timeline.duration_ns
                * timeline.fps_num
                / (1_000_000_000 * timeline.fps_den)
            )
            - 1
        )
        expected_transition_indices: set[int] = set()
        expected_transition_groups: list[dict[str, object]] = []
        for beat in baseline["beat_graph"]:
            for segment in beat["segments"]:
                transition = segment["xfade"]
                if (
                    transition is None
                    or transition["kind"] == "cut"
                    or transition["dur"] <= 0
                ):
                    continue
                start_ns = (
                    segment["start_ns"] + segment["duration_ns"]
                )
                end_ns = start_ns + round(
                    transition["dur"] * 1_000_000_000
                )
                indices = list(
                    _interval_frame_indices(
                        start_ns,
                        min(end_ns, timeline.duration_ns),
                        fps_num=timeline.fps_num,
                        fps_den=timeline.fps_den,
                    )
                )
                expected_transition_indices.update(indices)
                expected_transition_groups.append(
                    {
                        "kind": f"xfade:{transition['kind']}",
                        "start_ns": start_ns,
                        "end_ns": end_ns,
                        "frame_indices": indices,
                        "before_frame_index": max(0, indices[0] - 1),
                        "after_frame_index": min(
                            max_frame_index, indices[-1] + 1
                        ),
                    }
                )
        for fade in expected_video_fades:
            end_ns = min(fade[1] + fade[2], timeline.duration_ns)
            indices = list(
                _interval_frame_indices(
                    fade[1],
                    end_ns,
                    fps_num=timeline.fps_num,
                    fps_den=timeline.fps_den,
                )
            )
            expected_transition_indices.update(indices)
            expected_transition_groups.append(
                {
                    "kind": f"video_fade:{fade[0]}",
                    "start_ns": fade[1],
                    "end_ns": end_ns,
                    "frame_indices": indices,
                    "before_frame_index": max(0, indices[0] - 1),
                    "after_frame_index": min(
                        max_frame_index, indices[-1] + 1
                    ),
                }
            )
        baseline_transition_indices = {
            int(item["frame_index"])
            for item in legacy_frames
            if item["sample_kind"] == "transition"
        }
        frame_comparison = []
        reference_frames: dict[int, bytes] = {}
        actual_frames: dict[int, bytes] = {}
        for expected in legacy_frames:
            reference = base64.b64decode(expected["gray64x36_base64"])
            frame_index = int(expected["frame_index"])
            target_ns = round(
                frame_index
                * 1_000_000_000
                * timeline.fps_den
                / timeline.fps_num
            )
            actual_pts_ns, actual = _nearest_frame(
                output_frames,
                target_ns,
            )
            gray = actual["gray"]
            assert isinstance(gray, bytes)
            reference_frames[frame_index] = reference
            actual_frames[frame_index] = gray
            mae = sum(
                abs(left - right)
                for left, right in zip(reference, gray, strict=True)
            ) / len(reference)
            frame_comparison.append(
                {
                    "second": expected["second"],
                    "frame_index": frame_index,
                    "reference_timing_delta_ns": expected[
                        "timing_delta_ns"
                    ],
                    "actual_timing_delta_ns": actual_pts_ns - target_ns,
                    "sample_kind": expected["sample_kind"],
                    "mae_gray": round(mae, 4),
                    "dhash_hamming": _hamming(
                        expected["dhash63x36"], str(actual["dhash"])
                    ),
                    "global_ssim": round(_global_ssim(reference, gray), 6),
                }
            )
        anti_cut_groups = [
            _anti_cut_group(group, reference_frames, actual_frames)
            for group in expected_transition_groups
        ]
        audio = _audio_fingerprint(output)
        legacy_audio = baseline["legacy_artifact"]["audio"]
        legacy_artifact_path = (
            port.parent / baseline["legacy_artifact"]["logical_path"]
        )
        aligned_audio = _aligned_audio_correlation(
            _audio_pcm(legacy_artifact_path),
            _audio_pcm(output),
        )
        rms_ratio = float(audio["rms_s16"]) / max(
            1.0, float(legacy_audio["rms_s16"])
        )
        transition_frames = [
            item
            for item in frame_comparison
            if item["sample_kind"] == "transition"
        ]
        transition_strong_matches = [
            item
            for item in transition_frames
            if item["mae_gray"] <= 20.0
            or item["dhash_hamming"] <= 250
            or item["global_ssim"] >= 0.75
        ]
        transition_outliers = [
            item
            for item in transition_frames
            if not (
                item["mae_gray"] <= 90.0
                or item["dhash_hamming"] <= 900
                or item["global_ssim"] >= 0.25
            )
        ]
        non_transition_frames = [
            item
            for item in frame_comparison
            if item["sample_kind"]
            not in {"transition", "transition_guard"}
        ]
        guard_frames = [
            item
            for item in frame_comparison
            if item["sample_kind"] == "transition_guard"
        ]
        guard_integrity = _guard_integrity(guard_frames)
        semantic_checks = {
            "canvas_matches": (
                timeline.width,
                timeline.height,
                timeline.fps_num,
                timeline.fps_den,
            )
            == (
                baseline["canvas"]["width"],
                baseline["canvas"]["height"],
                baseline["canvas"]["fps_num"],
                baseline["canvas"]["fps_den"],
            ),
            "duration_matches": timeline.duration_ns == baseline["duration_ns"],
            "kind_matches": timeline.metadata["kind"]
            == {
                "vertical": "reel",
                "longform": "devlog",
                "capture_vo": "capture_vo",
            }[name],
            "exact_reachable_assets": actual_blob_hashes
            == expected_blob_hashes,
            "exact_segment_graph": exact_segments,
            "exact_raster_graph": actual_rasters == expected_rasters,
            "exact_voice_graph": exact_voice,
            "exact_music_graph": exact_music,
            "exact_video_fades": actual_video_fades == expected_video_fades,
            "exact_mix_policy": (
                timeline.target_lufs_milli,
                timeline.true_peak_db_milli,
                timeline.duck_amount_db_milli,
                timeline.duck_threshold_db_milli,
                timeline.duck_attack_ms,
                timeline.duck_release_ms,
            )
            == (
                baseline["mix"]["target_lufs_milli"],
                baseline["mix"]["true_peak_db_milli"],
                round(baseline["mix"]["duck"]["amount_db"] * 1000),
                round(baseline["mix"]["duck"]["threshold_db"] * 1000),
                baseline["mix"]["duck"]["attack_ms"],
                baseline["mix"]["duck"]["release_ms"],
            ),
            "legacy_artifact_hash_frozen": _hash(
                port.parent / baseline["legacy_artifact"]["logical_path"]
            )
            == baseline["legacy_artifact"]["sha256"],
            "legacy_visual_equivalence": all(
                item["mae_gray"] <= 15.0
                or item["dhash_hamming"] <= 200
                or item["global_ssim"] >= 0.75
                for item in non_transition_frames
            )
            and (
                not transition_frames
                or (
                    len(transition_outliers)
                    <= math.ceil(len(transition_frames) * 0.02)
                    and len(transition_strong_matches)
                    / len(transition_frames)
                    >= 0.5
                )
            ),
            "native_transition_graph_exact": exact_segments
            and baseline_transition_indices == expected_transition_indices
            and baseline["legacy_artifact"]["transition_groups"]
            == expected_transition_groups
            and all(bool(item["pass"]) for item in anti_cut_groups)
            and all(
                abs(int(item["reference_timing_delta_ns"]))
                <= math.ceil(
                    1_000_000_000
                    * timeline.fps_den
                    / timeline.fps_num
                )
                and abs(int(item["actual_timing_delta_ns"]))
                <= math.ceil(
                    1_000_000_000
                    * timeline.fps_den
                    / timeline.fps_num
                )
                for item in frame_comparison
                if item["sample_kind"] == "transition"
            ),
            "transition_guard_integrity": (
                bool(guard_integrity["pass"])
            ),
            "legacy_audio_equivalence": (
                abs(
                    float(audio["integrated_lufs"])
                    - float(legacy_audio["integrated_lufs"])
                )
                <= 1.5
                and 0.75 <= rms_ratio <= 1.25
                and abs(
                    int(audio["sample_count"])
                    - int(legacy_audio["sample_count"])
                )
                <= 800
                and float(aligned_audio["correlation"]) >= 0.98
            ),
            "delivery_loudness_postcondition": (
                abs(
                    float(audio["integrated_lufs"])
                    - timeline.target_lufs_milli / 1000
                )
                <= 1.0
                and float(audio["true_peak_dbfs"])
                <= timeline.true_peak_db_milli / 1000 + 0.5
            ),
        }
        if not all(semantic_checks.values()):
            failing_visual_frames = [
                item
                for item in frame_comparison
                if not (
                    (
                        item["mae_gray"] <= 90.0
                        or item["dhash_hamming"] <= 900
                        or item["global_ssim"] >= 0.25
                    )
                    if item["sample_kind"] == "transition"
                    else (
                        item["mae_gray"] <= 15.0
                        or item["dhash_hamming"] <= 200
                        or item["global_ssim"] >= 0.75
                    )
                )
            ]
            raise RuntimeError(
                f"{name} semantic baseline failed: {semantic_checks}; "
                f"transition_strong={len(transition_strong_matches)}/"
                f"{len(transition_frames)}; "
                f"transition_outliers={len(transition_outliers)}/"
                f"{len(transition_frames)}; "
                f"failed_anti_cut_groups="
                f"{[item for item in anti_cut_groups if not item['pass']]}; "
                f"guard_integrity={guard_integrity}; "
                f"failing_visual_frames={failing_visual_frames}; "
                f"audio={audio}; "
                f"legacy_audio={legacy_audio}"
            )
        entries.append(
            {
                "name": name,
                "port": port.relative_to(workspace).as_posix(),
                "timeline_id": timeline.timeline_id,
                "ir_sha256": _hash(ir),
                "artifact_path": output.relative_to(workspace).as_posix(),
                "artifact_sha256": _hash(output),
                "artifact_bytes": output.stat().st_size,
                "probe": json.loads(probe.stdout),
                "fresh_process": True,
                "graph": {
                    "asset_ids": actual_assets,
                    "visual_kinds": actual_visual_kinds,
                    "audio_asset_ids": actual_audio_assets,
                },
                "legacy_frame_comparison": frame_comparison,
                "transition_frame_gate": {
                    "total": len(transition_frames),
                    "strong_matches": len(transition_strong_matches),
                    "outliers": len(transition_outliers),
                    "max_outliers": math.ceil(
                        len(transition_frames) * 0.02
                    ),
                    "anti_cut_groups": anti_cut_groups,
                    "guard_integrity": guard_integrity,
                },
                "audio_fingerprint": audio,
                "legacy_audio": legacy_audio,
                "aligned_audio": aligned_audio,
                "legacy_audio_rms_ratio": round(rms_ratio, 5),
                "semantic_checks": semantic_checks,
            }
        )
    report = {
        "schema": "studio_v3.phase3_representative_e2e",
        "version": 1,
        "entries": entries,
        "result": "PASS",
    }
    args.report.parent.mkdir(parents=True, exist_ok=True)
    args.report.write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
