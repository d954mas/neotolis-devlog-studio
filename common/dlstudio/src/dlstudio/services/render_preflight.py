"""Frame-level QC for an exact rendered MP4 artifact.

The IR checks run before rendering; these checks deliberately run after it.
Frames are decoded in presentation order without an ``fps`` filter, reduced to
a small grayscale analysis plane, and paired with their ffprobe PTS.  The
analysis is deterministic and has no computer-vision runtime dependency.
"""
from __future__ import annotations

import json
import math
from dataclasses import dataclass
from pathlib import Path
import shutil
import subprocess
from typing import Any, Iterable, Sequence

import numpy as np

from dlstudio.ir import CheckIssue, CheckReport


_ANALYSIS_SIZE = 96
_BOUNDARY_RADIUS = 0.25
_FREEZE_FRAME_MAE = 0.35
_FREEZE_WARN_DURATION = 0.25
_FREEZE_BLOCK_DURATION = 0.40


class RenderInspectionUnavailable(RuntimeError):
    """A required local executable is unavailable."""


class RenderInspectionError(RuntimeError):
    """The artifact could not be decoded deterministically."""


@dataclass(frozen=True)
class FrameSample:
    index: int
    time: float
    luma: np.ndarray


MotionRange = tuple[float, float, str]
FreezeRange = tuple[float, float, str]


def _number(value: Any) -> float | None:
    if isinstance(value, bool):
        return None
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if math.isfinite(result) else None


def cut_times_from_shots(shots: Sequence[dict[str, Any]]) -> tuple[float, ...]:
    """Return internal hard-cut times from manifest shot starts."""
    starts = sorted({value for shot in shots if (value := _number(shot.get("t0"))) is not None})
    if len(starts) < 2:
        return ()
    return tuple(starts[1:])


def load_shot_manifest(path: str | Path) -> tuple[dict[str, Any], ...]:
    """Load either supported shot-manifest JSON shape."""
    manifest = Path(path)
    try:
        payload = json.loads(manifest.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RenderInspectionError(f"cannot read shot manifest {manifest}: {exc}") from exc
    raw_shots = payload.get("shots") if isinstance(payload, dict) else payload
    if not isinstance(raw_shots, list) or not all(isinstance(shot, dict) for shot in raw_shots):
        raise RenderInspectionError(
            f"shot manifest {manifest} must be an array or an object with a shots array"
        )
    return tuple(raw_shots)


def motion_ranges_from_shots(shots: Sequence[dict[str, Any]]) -> tuple[MotionRange, ...]:
    """Select manifest spans where adjacent frames are expected to move.

    Only effects that promise continuous sub-frame motion are enforceable.
    Native gameplay, kinetic text and deliberate holds may legitimately contain
    unchanged runs; treating every video suffix as a smooth pan creates false
    final blockers.  Explicit zoom/pan/Ken Burns declarations remain checked.
    """
    ranges: list[MotionRange] = []
    for index, shot in enumerate(shots):
        t0 = _number(shot.get("t0"))
        t1 = _number(shot.get("t1"))
        if t0 is None or t1 is None or t1 <= t0:
            continue
        raw_motion = shot.get("motion")
        motion = "" if raw_motion is None else str(raw_motion).strip().casefold()
        explicitly_static = raw_motion is not None and motion in {"", "none", "static", "hold"}
        dynamic = not explicitly_static and (
            bool(shot.get("ken_burns"))
            or any(
                token in motion
                for token in (
                    "ken_burns",
                    "ken burns",
                    "zoom",
                    "pan",
                    "continuous",
                    "smooth",
                )
            )
        )
        if dynamic:
            ranges.append((t0, t1, str(shot.get("id") or f"shot-{index}")))
    return tuple(ranges)


def freeze_ranges_from_shots(shots: Sequence[dict[str, Any]]) -> tuple[FreezeRange, ...]:
    """Select shot spans where a whole-frame pause is suspicious.

    Static plates and explicit deliberate holds are excluded.  Other rendered
    video spans are candidates rather than assumptions: a detected pause is
    reported with an exact timestamp so a reviewer can decide whether it is an
    accidental gameplay/render stall or an intentional editorial beat.
    """
    ranges: list[FreezeRange] = []
    video_suffixes = {".avi", ".m4v", ".mkv", ".mov", ".mp4", ".webm"}
    static_motion = {"", "none", "static", "hold", "subtle"}
    static_intent = {
        "deliberate_hold",
        "deliberate hold",
        "deliberate_low_fps_demo",
        "deliberate low fps demo",
        "still",
        "pause",
    }
    for index, shot in enumerate(shots):
        t0 = _number(shot.get("t0"))
        t1 = _number(shot.get("t1"))
        if t0 is None or t1 is None or t1 <= t0:
            continue
        motion = str(shot.get("motion") or "").strip().casefold()
        intent = str(shot.get("intent") or "").strip().casefold()
        suffix = Path(str(shot.get("src") or "")).suffix.casefold()
        if intent in static_intent or motion in static_motion:
            continue
        if suffix in video_suffixes or motion:
            ranges.append((t0, t1, str(shot.get("id") or f"shot-{index}")))
    return tuple(ranges)


def _parse_rate(value: Any) -> float | None:
    text = str(value or "")
    if "/" in text:
        numerator, denominator = text.split("/", 1)
        top = _number(numerator)
        bottom = _number(denominator)
        if top is not None and bottom not in {None, 0.0}:
            return top / bottom
    return _number(text)


def _run_tool(command: list[str], *, binary: str, timeout: float) -> subprocess.CompletedProcess:
    executable = shutil.which(binary)
    if executable is None:
        raise RenderInspectionUnavailable(f"{binary} not found on PATH")
    command = [executable, *command[1:]]
    try:
        return subprocess.run(
            command,
            capture_output=True,
            check=False,
            timeout=timeout,
        )
    except FileNotFoundError as exc:  # pragma: no cover - guarded by which()
        raise RenderInspectionUnavailable(f"{binary} not found on PATH") from exc
    except subprocess.TimeoutExpired as exc:
        raise RenderInspectionError(f"{binary} timed out inspecting the render") from exc


def decode_rendered_frames(video_path: str | Path) -> tuple[FrameSample, ...]:
    """Decode every frame from ``video_path`` once, without frame resampling."""
    artifact = Path(video_path)
    if not artifact.is_file():
        raise RenderInspectionError(f"render artifact does not exist: {artifact}")

    probe = _run_tool(
        [
            "ffprobe", "-v", "error", "-select_streams", "v:0",
            "-show_entries",
            "frame=best_effort_timestamp_time:stream=avg_frame_rate,width,height",
            "-of", "json", str(artifact),
        ],
        binary="ffprobe",
        timeout=60,
    )
    if probe.returncode:
        detail = probe.stderr.decode("utf-8", errors="replace").strip()
        raise RenderInspectionError(f"ffprobe could not read {artifact}: {detail}")
    try:
        facts = json.loads(probe.stdout.decode("utf-8"))
        streams = facts.get("streams") or []
        frames = facts.get("frames") or []
        rate = _parse_rate(streams[0].get("avg_frame_rate")) if streams else None
    except (AttributeError, IndexError, json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise RenderInspectionError(f"ffprobe returned invalid frame metadata for {artifact}") from exc

    decoded = _run_tool(
        [
            "ffmpeg", "-v", "error", "-i", str(artifact), "-map", "0:v:0",
            "-vf", f"scale={_ANALYSIS_SIZE}:{_ANALYSIS_SIZE},format=gray",
            "-vsync", "0", "-f", "rawvideo", "-pix_fmt", "gray", "pipe:1",
        ],
        binary="ffmpeg",
        timeout=180,
    )
    if decoded.returncode:
        detail = decoded.stderr.decode("utf-8", errors="replace").strip()
        raise RenderInspectionError(f"ffmpeg could not decode {artifact}: {detail}")

    plane_bytes = _ANALYSIS_SIZE * _ANALYSIS_SIZE
    frame_count, remainder = divmod(len(decoded.stdout), plane_bytes)
    if remainder or frame_count == 0:
        raise RenderInspectionError(
            f"ffmpeg returned an invalid grayscale frame stream for {artifact}"
        )
    pixels = np.frombuffer(decoded.stdout, dtype=np.uint8).reshape(
        frame_count, _ANALYSIS_SIZE, _ANALYSIS_SIZE
    )

    timestamps: list[float] = []
    for index in range(frame_count):
        raw = frames[index].get("best_effort_timestamp_time") if index < len(frames) else None
        timestamp = _number(raw)
        if timestamp is None:
            timestamp = index / rate if rate and rate > 0 else float(index)
        timestamps.append(timestamp)
    return tuple(
        FrameSample(index=index, time=timestamps[index], luma=pixels[index])
        for index in range(frame_count)
    )


def _distance(left: np.ndarray, right: np.ndarray) -> float:
    return float(np.mean(np.abs(left.astype(np.int16) - right.astype(np.int16))))


def _boundary_issue(
    samples: Sequence[FrameSample],
    cut: float,
    *,
    final: bool,
) -> CheckIssue | None:
    strip = [sample for sample in samples if abs(sample.time - cut) <= _BOUNDARY_RADIUS + 1e-9]
    if not strip:
        return CheckIssue(
            severity="warn",
            code="VQ-BOUNDARY",
            message=f"no decoded frames within ±{_BOUNDARY_RADIUS:.2f}s of cut {cut:.3f}s",
            where=f"cut@{cut:.3f}s",
        )

    before_refs = [sample for sample in strip if sample.time < cut]
    after_refs = [sample for sample in strip if sample.time >= cut]
    pre_ref = before_refs[0] if before_refs else None
    post_ref = after_refs[-1] if after_refs else None
    reasons: list[str] = []
    times: list[float] = []

    if pre_ref is not None and post_ref is not None:
        refs_are_dark = float(pre_ref.luma.mean()) <= 20 and float(post_ref.luma.mean()) <= 20
        if not refs_are_dark:
            for sample in strip:
                mean = float(sample.luma.mean())
                std = float(sample.luma.std())
                if mean <= 12 or (mean <= 35 and std <= 2.5):
                    reasons.append("black/loading-like frame")
                    times.append(sample.time)
                    break

        # A foreign frame is only called stale after the new side has already
        # appeared.  This avoids treating the normal first hard-cut frame as a
        # timestamp rounding problem.
        seen_post = False
        for sample in after_refs:
            if _distance(sample.luma, post_ref.luma) <= 2.0:
                seen_post = True
            elif (
                seen_post
                and _distance(sample.luma, pre_ref.luma) <= 2.0
                and _distance(sample.luma, post_ref.luma) >= 8.0
            ):
                reasons.append("stale/foreign frame after cut")
                times.append(sample.time)
                break

    # Also catch an isolated one-frame flash whose source is neither side.
    for position in range(1, len(strip) - 1):
        previous, current, following = strip[position - 1 : position + 2]
        if (
            _distance(previous.luma, following.luma) <= 2.0
            and _distance(previous.luma, current.luma) >= 8.0
            and _distance(current.luma, following.luma) >= 8.0
        ):
            if not reasons:
                reasons.append("isolated stale/foreign flash")
                times.append(current.time)
            break

    if not reasons:
        return None
    unique_reasons = list(dict.fromkeys(reasons))
    timestamp = min(times, key=lambda value: abs(value - cut))
    return CheckIssue(
        severity="error" if final else "warn",
        code="VQ-BOUNDARY",
        message=(
            f"cut {cut:.3f}s contains {', '.join(unique_reasons)} at "
            f"{timestamp:.3f}s inside ±{_BOUNDARY_RADIUS:.2f}s strip"
        ),
        where=f"cut@{cut:.3f}s",
    )


def _motion_issue(
    samples: Sequence[FrameSample],
    motion_range: MotionRange,
    *,
    cut_times: Sequence[float],
    final: bool,
) -> CheckIssue | None:
    t0, t1, label = motion_range
    selected = [sample for sample in samples if t0 <= sample.time < t1]
    if len(selected) < 7:
        return None
    differences: list[float] = []
    for left, right in zip(selected, selected[1:]):
        if any(left.time < cut <= right.time for cut in cut_times):
            continue
        differences.append(_distance(left.luma, right.luma))
    if len(differences) < 6:
        return None

    duplicate = [value <= 0.6 for value in differences]
    active = [value >= 2.0 for value in differences]
    duplicate_count = sum(duplicate)
    duplicate_ratio = duplicate_count / len(differences)
    step_count = sum(
        duplicate[index] and active[index - 1] and active[index + 1]
        for index in range(1, len(differences) - 1)
    )
    step_ratio = step_count / len(differences)
    longest_run = 0
    current_run = 0
    for is_duplicate in duplicate:
        current_run = current_run + 1 if is_duplicate else 0
        longest_run = max(longest_run, current_run)

    duplicate_problem = duplicate_count >= 2 and duplicate_ratio >= 0.08
    stepped_problem = step_count >= 2 and step_ratio >= 0.08
    if not duplicate_problem and not stepped_problem:
        return None
    gross = duplicate_ratio >= 0.25 or step_ratio >= 0.20 or longest_run >= 3
    findings: list[str] = []
    if duplicate_problem:
        findings.append(
            f"adjacent duplicate ratio {duplicate_ratio:.1%} ({duplicate_count}/{len(differences)})"
        )
    if stepped_problem:
        findings.append(f"stepped-motion proxy {step_ratio:.1%} ({step_count} plateaus)")
    return CheckIssue(
        severity="error" if final and gross else "warn",
        code="VQ-MOTION-SMOOTH",
        message=f"{label} [{t0:.3f},{t1:.3f}) has " + "; ".join(findings),
        where=label,
    )


def _freeze_issues(
    samples: Sequence[FrameSample],
    freeze_ranges: Sequence[FreezeRange],
    *,
    cut_times: Sequence[float],
    final: bool,
) -> list[CheckIssue]:
    if len(samples) < 2 or not freeze_ranges:
        return []

    issues: list[CheckIssue] = []
    run_start: float | None = None
    run_end: float | None = None
    run_labels: set[str] = set()

    def flush() -> None:
        nonlocal run_start, run_end, run_labels
        if run_start is not None and run_end is not None:
            duration = run_end - run_start
            if duration + 1e-9 >= _FREEZE_WARN_DURATION:
                labels = ", ".join(sorted(run_labels)) or "dynamic shot"
                issues.append(CheckIssue(
                    severity=(
                        "error"
                        if final and duration + 1e-9 >= _FREEZE_BLOCK_DURATION
                        else "warn"
                    ),
                    code="VQ-FREEZE",
                    message=(
                        f"whole-frame freeze candidate {duration:.3f}s at "
                        f"[{run_start:.3f},{run_end:.3f}] in {labels}"
                    ),
                    where=f"freeze@{run_start:.3f}s",
                ))
        run_start = None
        run_end = None
        run_labels = set()

    for left, right in zip(samples, samples[1:]):
        midpoint = (left.time + right.time) / 2
        labels = {
            label for t0, t1, label in freeze_ranges
            if t0 <= midpoint < t1
        }
        crosses_cut = any(left.time < cut <= right.time for cut in cut_times)
        duplicate = (
            bool(labels)
            and not crosses_cut
            and _distance(left.luma, right.luma) <= _FREEZE_FRAME_MAE
        )
        if duplicate:
            if run_start is None:
                run_start = left.time
            run_end = right.time
            run_labels.update(labels)
        else:
            flush()
    flush()
    return issues


def _cadence_issues(
    samples: Sequence[FrameSample],
    freeze_ranges: Sequence[FreezeRange],
    *,
    cut_times: Sequence[float],
    final: bool,
) -> list[CheckIssue]:
    """Find stepped capture cadence such as 15 unique fps stored as 30 fps."""
    issues: list[CheckIssue] = []
    for t0, t1, label in freeze_ranges:
        differences: list[float] = []
        for left, right in zip(samples, samples[1:]):
            midpoint = (left.time + right.time) / 2
            if not (t0 <= midpoint < t1):
                continue
            if any(left.time < cut <= right.time for cut in cut_times):
                continue
            differences.append(_distance(left.luma, right.luma))
        if len(differences) < 12:
            continue

        duplicate = [value <= _FREEZE_FRAME_MAE for value in differences]
        active = [value >= 2.0 for value in differences]
        duplicate_count = sum(duplicate)
        isolated_count = sum(
            duplicate[index] and active[index - 1] and active[index + 1]
            for index in range(1, len(differences) - 1)
        )
        duplicate_ratio = duplicate_count / len(differences)
        isolated_ratio = isolated_count / len(differences)
        if duplicate_count < 4 or isolated_count < 4:
            continue
        if duplicate_ratio < 0.25 or isolated_ratio < 0.20:
            continue
        gross = duplicate_ratio >= 0.35 and isolated_ratio >= 0.20
        issues.append(CheckIssue(
            severity="error" if final and gross else "warn",
            code="VQ-CADENCE",
            message=(
                f"{label} [{t0:.3f},{t1:.3f}) has stepped capture cadence: "
                f"adjacent duplicates {duplicate_ratio:.1%} "
                f"({duplicate_count}/{len(differences)}); "
                f"alternating plateaus {isolated_ratio:.1%} "
                f"({isolated_count}/{len(differences)})"
            ),
            where=label,
        ))
    return issues


def analyze_frame_samples(
    samples: Sequence[FrameSample],
    *,
    cut_times: Iterable[float],
    motion_ranges: Iterable[MotionRange] = (),
    freeze_ranges: Iterable[FreezeRange] = (),
    final: bool = False,
) -> CheckReport:
    """Pure frame analysis seam used by tests and the ffmpeg adapter."""
    ordered = tuple(sorted(samples, key=lambda sample: (sample.time, sample.index)))
    cuts = tuple(sorted({float(value) for value in cut_times if math.isfinite(float(value))}))
    freezes = tuple(freeze_ranges)
    issues: list[CheckIssue] = []
    for cut in cuts:
        issue = _boundary_issue(ordered, cut, final=final)
        if issue is not None:
            issues.append(issue)
    issues.extend(_freeze_issues(
        ordered,
        freezes,
        cut_times=cuts,
        final=final,
    ))
    issues.extend(_cadence_issues(
        ordered,
        freezes,
        cut_times=cuts,
        final=final,
    ))
    for motion_range in motion_ranges:
        issue = _motion_issue(
            ordered, motion_range, cut_times=cuts, final=final
        )
        if issue is not None:
            issues.append(issue)
    return CheckReport(issues=issues)


def analyze_rendered_video(
    video_path: str | Path,
    *,
    shots: Sequence[dict[str, Any]] | None = None,
    shot_manifest: str | Path | None = None,
    cut_times: Iterable[float] | None = None,
    motion_ranges: Iterable[MotionRange] | None = None,
    freeze_ranges: Iterable[FreezeRange] | None = None,
    final: bool = False,
) -> CheckReport:
    """Run boundary, freeze and motion-smooth QC on one exact MP4.

    Boundaries are never guessed from frame content: callers provide explicit
    cut times or a shot manifest.  Motion spans use the same manifest unless
    explicitly supplied.
    """
    artifact = Path(video_path)
    if shots is not None and shot_manifest is not None:
        raise ValueError("pass shots or shot_manifest, not both")
    try:
        resolved_shots = load_shot_manifest(shot_manifest) if shot_manifest is not None else shots
    except RenderInspectionError as exc:
        return CheckReport(issues=[CheckIssue(
            severity="error" if final else "warn",
            code="VQ-BOUNDARY",
            message=str(exc),
            where=str(shot_manifest),
        )])
    try:
        samples = decode_rendered_frames(artifact)
    except RenderInspectionUnavailable as exc:
        return CheckReport(issues=[CheckIssue(
            severity="warn",
            code="VQ-RENDER-TOOLS",
            message=f"render artifact QC unavailable: {exc}",
            where=str(artifact),
        )])
    except RenderInspectionError as exc:
        return CheckReport(issues=[CheckIssue(
            severity="error" if final else "warn",
            code="VQ-RENDER-ARTIFACT",
            message=str(exc),
            where=str(artifact),
        )])

    boundary_missing = cut_times is None and resolved_shots is None
    resolved_cuts = (
        tuple(cut_times)
        if cut_times is not None
        else cut_times_from_shots(resolved_shots or ())
    )
    if motion_ranges is None:
        resolved_motion = motion_ranges_from_shots(resolved_shots or ())
    else:
        resolved_motion = tuple(motion_ranges)
    if freeze_ranges is None:
        resolved_freezes = freeze_ranges_from_shots(resolved_shots or ())
    else:
        resolved_freezes = tuple(freeze_ranges)
    report = analyze_frame_samples(
        samples,
        cut_times=resolved_cuts,
        motion_ranges=resolved_motion,
        freeze_ranges=resolved_freezes,
        final=final,
    )
    if boundary_missing:
        report.issues.insert(0, CheckIssue(
            severity="warn",
            code="VQ-BOUNDARY",
            message="boundary QC not evaluated: supply shot manifest or explicit cut_times",
            where=str(artifact),
        ))
    return report


__all__ = [
    "FrameSample",
    "FreezeRange",
    "MotionRange",
    "RenderInspectionError",
    "RenderInspectionUnavailable",
    "analyze_frame_samples",
    "analyze_rendered_video",
    "cut_times_from_shots",
    "decode_rendered_frames",
    "freeze_ranges_from_shots",
    "load_shot_manifest",
    "motion_ranges_from_shots",
]
