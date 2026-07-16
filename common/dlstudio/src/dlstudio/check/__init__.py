"""check — gates as code, run on the Timeline IR.

OWNER: compile-agent.

Every gate has a VQ code (see docs/ARCHITECTURE_V2.md). Baseline set:
- VQ-ASSET  missing/unreadable referenced assets (error)
- VQ-WORDS  word indices out of transcript range / overlapping chunks (error)
- VQ-SYNC   rendered output duration vs VO duration mismatch (error) —
            exposed as `verify_output()` for renderers to call as a
            POSTCONDITION (the v1 bug class that cost 22 blind iterations)
- VQ-RES    resolution sanity: absurd upscales / dims beyond encoder
            limits (the 3840x6826 x264 OOM class) (error)
- VQ-OFFSET scene offset at/past source EOF (warn, compile clamps)

Design note: chunk word indices and pre-clamp offsets are NOT stored in the
IR (contract freeze — no new fields), so the two facts that are lost after
resolution — out-of-range indices and offset-past-EOF — are recorded by
compile as structured `CheckIssue` objects directly on `Timeline.diagnostics`
(`_promote_warnings` merges them as-is, no parsing involved).
`Timeline.warnings` carries the same facts as human-readable "VQ-WORDS:"/
"VQ-OFFSET:" tagged strings for display only. Everything else (asset
existence/readability, window overlap, resolution) is derived directly from
the IR.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from dlstudio.ir import CheckIssue, CheckReport, Timeline

_EPS = 1e-3
_MAX_DIM = 4096          # x264 practical safety ceiling per axis
_MAX_UPSCALE = 2.2       # full-bleed upscale factor cap (the 3840x6826 OOM class)


def run_checks(timeline: Timeline) -> CheckReport:
    issues: list[CheckIssue] = []
    issues += _check_assets(timeline)
    issues += _check_words(timeline)
    issues += _check_resolution(timeline)
    issues += _promote_warnings(timeline)

    # dedupe exact repeats (defensive: gates are independent and could
    # in principle produce the same (code, message, where) triple)
    seen: set[tuple[str, str, str]] = set()
    unique: list[CheckIssue] = []
    for it in issues:
        key = (it.code, it.message, it.where)
        if key not in seen:
            seen.add(key)
            unique.append(it)
    return CheckReport(issues=unique)


# ─── VQ-ASSET ───────────────────────────────────────────────────────────────

def _check_assets(timeline: Timeline) -> list[CheckIssue]:
    out: list[CheckIssue] = []
    for path, probe in timeline.assets.items():
        if not probe.exists:
            out.append(CheckIssue(
                severity="error", code="VQ-ASSET",
                message=f"referenced {probe.kind} asset is missing: {path}",
                where=path,
            ))
        elif probe.readable is False:
            out.append(CheckIssue(
                severity="error", code="VQ-ASSET",
                message=f"referenced {probe.kind} asset is present but unreadable: {path}",
                where=path,
            ))
    return out


# ─── VQ-WORDS (IR-native overlap/order + compile-tagged out-of-range) ────────

def _check_words(timeline: Timeline) -> list[CheckIssue]:
    out: list[CheckIssue] = []
    for beat in timeline.beats:
        prev = None
        for ov in beat.overlays:
            if prev is not None:
                if ov.t0 < prev.t0 - _EPS:
                    out.append(CheckIssue(
                        severity="error", code="VQ-WORDS",
                        message=(f"overlay windows out of order: chunk "
                                 f"{ov.chunk_index} starts {ov.t0:.3f}s before "
                                 f"chunk {prev.chunk_index} at {prev.t0:.3f}s"),
                        where=f"{beat.id}:{ov.chunk_index}",
                    ))
                elif ov.t0 < prev.t1 - _EPS:
                    out.append(CheckIssue(
                        severity="error", code="VQ-WORDS",
                        message=(f"overlapping chunk windows: chunk "
                                 f"{prev.chunk_index} ends {prev.t1:.3f}s, chunk "
                                 f"{ov.chunk_index} starts {ov.t0:.3f}s"),
                        where=f"{beat.id}:{ov.chunk_index}",
                    ))
            prev = ov
    return out


# ─── VQ-RES ─────────────────────────────────────────────────────────────────

def _check_resolution(timeline: Timeline) -> list[CheckIssue]:
    out: list[CheckIssue] = []
    w, h = timeline.design.resolution
    if w > _MAX_DIM or h > _MAX_DIM:
        out.append(CheckIssue(
            severity="error", code="VQ-RES",
            message=(f"output resolution {w}x{h} exceeds encoder-safe "
                     f"{_MAX_DIM}px per axis (x264 OOM class)"),
            where=timeline.edit_name,
        ))
    for beat in timeline.beats:
        for si, seg in enumerate(beat.segments):
            probe = timeline.assets.get(seg.src)
            if probe is None or probe.width in (None, 0) or probe.height in (None, 0):
                continue
            scale = max(w / probe.width, h / probe.height)
            if scale > _MAX_UPSCALE + 1e-9:
                out.append(CheckIssue(
                    severity="error", code="VQ-RES",
                    message=(f"full-bleed {seg.kind} {seg.src} at "
                             f"{probe.width}x{probe.height} upscales "
                             f"{scale:.2f}x to {w}x{h} (> {_MAX_UPSCALE}x cap)"),
                    where=f"{beat.id}:seg{si}",
                ))
    return out


# ─── compile diagnostics -> issues ───────────────────────────────────────────

def _promote_warnings(timeline: Timeline) -> list[CheckIssue]:
    """Merge compile's structured diagnostics (VQ-WORDS out-of-range,
    VQ-OFFSET clamps) straight into the report. compile already builds these
    as CheckIssue objects with `where` set to the beat id -- nothing to
    parse or re-derive here."""
    return list(timeline.diagnostics)


# ─── VQ-SYNC postcondition ───────────────────────────────────────────────────

def verify_output(
    video_path: str,
    expected_duration: float,
    *,
    tolerance: float = 0.25,
) -> None:
    """ffprobe the rendered file; raise RuntimeError on duration mismatch or a
    missing/zero video stream. Renderers MUST call this after writing an MP4 —
    it is the postcondition that would have caught the v1 bug that produced a
    silent audio-only/truncated file for 22 blind iterations.
    """
    p = Path(video_path)
    if not p.exists():
        raise RuntimeError(
            f"VQ-SYNC: output does not exist: {video_path} "
            f"(expected {expected_duration:.3f}s)")

    try:
        r = subprocess.run(
            ["ffprobe", "-v", "error", "-print_format", "json",
             "-show_format", "-show_streams", video_path],
            capture_output=True, text=True,
        )
    except FileNotFoundError as e:  # pragma: no cover - ffprobe missing
        raise RuntimeError("ffprobe not found on PATH") from e

    if r.returncode != 0:
        raise RuntimeError(
            f"VQ-SYNC: ffprobe could not read {video_path}: {r.stderr.strip()}")

    try:
        data = json.loads(r.stdout)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"VQ-SYNC: ffprobe returned no parseable data for {video_path}") from e

    streams = data.get("streams", [])
    has_video = any(s.get("codec_type") == "video" for s in streams)
    if not has_video:
        raise RuntimeError(
            f"VQ-SYNC: {video_path} has no video stream "
            f"(expected {expected_duration:.3f}s of video)")

    dur_raw = data.get("format", {}).get("duration")
    try:
        actual = float(dur_raw)
    except (TypeError, ValueError):
        actual = 0.0
    if actual <= 0.0:
        raise RuntimeError(
            f"VQ-SYNC: {video_path} reports zero/invalid duration "
            f"({dur_raw!r}); expected {expected_duration:.3f}s")

    delta = abs(actual - expected_duration)
    if delta > tolerance:
        raise RuntimeError(
            f"VQ-SYNC: duration mismatch for {video_path}: "
            f"actual {actual:.3f}s vs expected {expected_duration:.3f}s "
            f"(delta {delta:.3f}s > tolerance {tolerance:.3f}s)")
