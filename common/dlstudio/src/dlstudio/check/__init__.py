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

from dlstudio.ir import CheckIssue, CheckReport, IRSegment, Timeline

_EPS = 1e-3
_MAX_DIM = 4096          # x264 practical safety ceiling per axis
_MAX_UPSCALE = 2.2       # full-bleed upscale factor cap (the 3840x6826 OOM class)


def run_checks(
    timeline: Timeline,
    *,
    strict_assets: bool | None = None,
) -> CheckReport:
    if strict_assets is None:
        # Direct callers retain the IR policy contract. Render entry points
        # always pass an explicit value so draft/preview can inspect a
        # production-authored edit without turning delivery rules into a
        # draft blocker.
        strict_assets = timeline.asset_policy == "production"
    issues: list[CheckIssue] = []
    issues += _check_assets(timeline)
    issues += _check_asset_identities(timeline, strict=strict_assets)
    issues += _check_source_windows(timeline, strict=strict_assets)
    issues += _check_words(timeline)
    issues += _check_resolution(timeline)
    issues += _check_geometry(timeline)
    issues += _check_boundaries(timeline)
    issues += _check_public_copy(timeline, strict=strict_assets)
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


def _check_public_copy(timeline: Timeline, *, strict: bool) -> list[CheckIssue]:
    if not strict:
        return []
    from dlstudio.services.editorial_preflight import public_copy_issues

    texts: list[tuple[str, str]] = []
    for beat in timeline.beats:
        for index, overlay in enumerate(beat.overlays):
            texts.extend(
                (f"{beat.id}:overlay{index}", text)
                for text in overlay.public_text
            )
        texts.extend(
            (f"{beat.id}:caption", caption.text)
            for caption in beat.captions
        )
    return public_copy_issues(Path.cwd(), texts)


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


# ─── VQ-ASSET-ID ────────────────────────────────────────────────────────────

def _check_asset_identities(
    timeline: Timeline,
    *,
    strict: bool,
) -> list[CheckIssue]:
    from dlstudio.services.asset_registry import (
        AssetRegistryError,
        load_asset_registry,
        resolve_approved_asset,
    )
    from dlstudio.services.hyperframes import validate_hyperframes_render_manifest

    out: list[CheckIssue] = []
    root = Path.cwd().resolve()
    registry = load_asset_registry(root)
    by_id = {asset.asset_id: asset for asset in registry.assets}
    for beat in timeline.beats:
        for index, segment in enumerate(beat.segments):
            where = f"{beat.id}:seg{index}"
            if strict and segment.kind == "video" and not segment.editorial_role:
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-ASSET-CLASS",
                    message=(
                        "production video requires editorial_role "
                        "(gameplay/debug_proof/presentation/reference)"
                    ),
                    where=where,
                ))
            if strict and segment.kind == "video":
                if segment.asset_id and segment.render_manifest:
                    out.append(CheckIssue(
                        severity="error",
                        code="VQ-ASSET-ID",
                        message=(
                            "production video must use exactly one identity source: "
                            "asset_id or render_manifest"
                        ),
                        where=where,
                    ))
                    continue
                if not segment.asset_id and not segment.render_manifest:
                    out.append(CheckIssue(
                        severity="error",
                        code="VQ-ASSET-ID",
                        message=(
                            "production video requires an approved asset_id or "
                            "a hash-bound render_manifest"
                        ),
                        where=where,
                    ))
            if strict and segment.editorial_role == "gameplay":
                missing_expectations = [
                    name
                    for name, value in (
                        ("expected_state_id", segment.expected_state_id),
                        ("expected_build_id", segment.expected_build_id),
                    )
                    if not value
                ]
                if missing_expectations:
                    out.append(CheckIssue(
                        severity="error",
                        code="VQ-ASSET-EXPECTATION",
                        message=(
                            "production gameplay requires "
                            + ", ".join(missing_expectations)
                        ),
                        where=where,
                    ))
                if segment.render_manifest:
                    out.append(CheckIssue(
                        severity="error",
                        code="VQ-ASSET-ID",
                        message="gameplay must use approved capture asset_id, not render_manifest",
                        where=where,
                    ))
                    continue
            if strict and segment.editorial_role == "gameplay" and not segment.asset_id:
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-ASSET-ID",
                    message="declared gameplay requires an approved asset_id",
                    where=where,
                ))
                continue
            if segment.render_manifest:
                try:
                    validate_hyperframes_render_manifest(
                        segment.src,
                        segment.render_manifest,
                        root,
                        require_final=strict,
                    )
                except RuntimeError as exc:
                    out.append(CheckIssue(
                        severity="error",
                        code="VQ-ASSET-ID",
                        message=str(exc),
                        where=where,
                    ))
                continue
            if not strict:
                # Draft/preview is allowed to use provisional or not-yet
                # approved footage. Delivery re-runs this gate with strict
                # identity and current-proof validation.
                continue
            if not segment.asset_id:
                continue
            record = by_id.get(segment.asset_id)
            if record is None:
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-ASSET-ID",
                    message=f"unknown asset_id: {segment.asset_id}",
                    where=where,
                ))
                continue
            expected_identity = (
                ("state_id", segment.expected_state_id, record.state_id),
                ("build_id", segment.expected_build_id, record.build_id),
                ("action_id", segment.expected_action_id, record.action_id),
            )
            for field, expected, actual in expected_identity:
                if expected is not None and expected != actual:
                    out.append(CheckIssue(
                        severity="error",
                        code="VQ-ASSET-EXPECTATION",
                        message=(
                            f"{field} mismatch for {segment.asset_id}: "
                            f"expected {expected}, registry has {actual}"
                        ),
                        where=where,
                    ))
            if (
                segment.editorial_role is not None
                and record.editorial_role != segment.editorial_role
            ):
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-ASSET-ID",
                    message=(
                        f"asset role {record.editorial_role} does not satisfy "
                        f"{segment.editorial_role}: {segment.asset_id}"
                    ),
                    where=where,
                ))
                continue
            if record.editorial_role == "gameplay":
                presentation = record.presentation or {}
                expected_fit = presentation.get("fit")
                output_width = presentation.get("output_width")
                output_height = presentation.get("output_height")
                geometry = segment.geometry
                presentation_mismatch = (
                    expected_fit not in {"cover", "contain"}
                    or segment.fit != expected_fit
                    or geometry is None
                    or geometry.fit != expected_fit
                    or geometry.anchor_x != 0.5
                    or geometry.anchor_y != 0.5
                    or geometry.output_width != output_width
                    or geometry.output_height != output_height
                )
                if presentation_mismatch:
                    out.append(CheckIssue(
                        severity="error",
                        code="VQ-ASSET-PRESENTATION",
                        message=(
                            "compiled gameplay transform does not match the "
                            f"validated centered presentation for {segment.asset_id}"
                        ),
                        where=where,
                    ))
                    continue
            try:
                approved_path = resolve_approved_asset(root, segment.asset_id)
            except AssetRegistryError as exc:
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-ASSET-ID",
                    message=str(exc),
                    where=where,
                ))
                continue
            source = Path(segment.src)
            resolved_source = (
                source.resolve() if source.is_absolute() else (root / source).resolve()
            )
            if resolved_source != approved_path:
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-ASSET-ID",
                    message=(
                        f"asset_id {segment.asset_id} resolves to "
                        f"{record.artifact_path}, not {segment.src}"
                    ),
                    where=where,
                ))
    return out


def _check_source_windows(
    timeline: Timeline,
    *,
    strict: bool,
) -> list[CheckIssue]:
    """Prevent the loop/freeze/restart class before FFmpeg sees the graph."""
    if not strict:
        return []

    from dlstudio.services.asset_registry import load_asset_registry

    registry = load_asset_registry(Path.cwd().resolve())
    by_id = {asset.asset_id: asset for asset in registry.assets}
    out: list[CheckIssue] = []
    for beat in timeline.beats:
        for index, segment in enumerate(beat.segments):
            if segment.editorial_role != "gameplay":
                continue
            where = f"{beat.id}:seg{index}"
            if segment.loop:
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-GAMEPLAY-LOOP",
                    message="production gameplay cannot loop or restart at EOF",
                    where=where,
                ))
            record = by_id.get(segment.asset_id or "")
            if record is None:
                continue
            head = record.head_handle_seconds or 0.0
            tail = record.tail_handle_seconds or 0.0
            duration = record.duration
            if duration is None:
                probe = timeline.assets.get(segment.src)
                duration = probe.duration if probe is not None else None
            if duration is None:
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-SOURCE-WINDOW",
                    message="approved gameplay has no proven source duration",
                    where=where,
                ))
                continue
            outgoing_transition = 0.0
            if index < len(beat.segments) - 1:
                if segment.xfade is None:
                    outgoing_transition = timeline.design.crossfade_dur
                elif segment.xfade.kind != "cut":
                    outgoing_transition = segment.xfade.dur
            source_end = (
                segment.offset
                + max(0.0, segment.t1 - segment.t0)
                + outgoing_transition
            )
            allowed_end = duration - tail
            if segment.offset < head - _EPS:
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-SOURCE-WINDOW",
                    message=(
                        f"gameplay offset {segment.offset:.3f}s consumes "
                        f"{head:.3f}s reserved head handle"
                    ),
                    where=where,
                ))
            if source_end > allowed_end + _EPS:
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-SOURCE-WINDOW",
                    message=(
                        f"gameplay source window ends at {source_end:.3f}s, "
                        f"past the safe end {allowed_end:.3f}s "
                        f"(tail handle {tail:.3f}s)"
                    ),
                    where=where,
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


# ─── VQ-GEOMETRY ────────────────────────────────────────────────────────────

def _check_geometry(timeline: Timeline) -> list[CheckIssue]:
    out: list[CheckIssue] = []
    for beat in timeline.beats:
        for index, segment in enumerate(beat.segments):
            geometry = segment.geometry
            if geometry is None:
                continue
            where = f"{beat.id}:seg{index}"
            output_width = geometry.output_width
            output_height = geometry.output_height
            if geometry.fit != segment.fit:
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-GEOMETRY",
                    message=(
                        f"segment fit {segment.fit} disagrees with resolved "
                        f"geometry fit {geometry.fit}"
                    ),
                    where=where,
                ))
                continue

            probe = timeline.assets.get(segment.src)
            if probe is not None and probe.width and probe.height:
                if (
                    geometry.source_width != probe.width
                    or geometry.source_height != probe.height
                ):
                    out.append(CheckIssue(
                        severity="error",
                        code="VQ-GEOMETRY",
                        message=(
                            "geometry source dimensions do not match probe: "
                            f"{geometry.source_width}x{geometry.source_height} vs "
                            f"{probe.width}x{probe.height}"
                        ),
                        where=where,
                    ))
                    continue

            if not all((
                geometry.source_width,
                geometry.source_height,
                geometry.scaled_width,
                geometry.scaled_height,
            )):
                if segment.editorial_role == "gameplay":
                    out.append(CheckIssue(
                        severity="error",
                        code="VQ-GEOMETRY",
                        message="approved gameplay has unresolved source geometry",
                        where=where,
                    ))
                continue

            expected = geometry.for_output(output_width, output_height)
            if geometry != expected:
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-GEOMETRY",
                    message="resolved fit/anchor transform is internally inconsistent",
                    where=where,
                ))
    return out


# ─── VQ-BOUNDARY / VQ-RESTART ───────────────────────────────────────────────

def _check_boundaries(timeline: Timeline) -> list[CheckIssue]:
    from dlstudio.services.boundary_report import BOUNDARY_OFFSET_TOLERANCE

    placement_by_beat = {item.beat_id: item.t0 for item in timeline.placements}
    entries: list[tuple[float, str, int, IRSegment]] = []
    for beat in timeline.beats:
        beat_start = placement_by_beat.get(beat.id, 0.0)
        for index, segment in enumerate(beat.segments):
            entries.append((beat_start + segment.t0, beat.id, index, segment))
    entries.sort(key=lambda item: item[0])

    out: list[CheckIssue] = []
    last_source_end: dict[str, float] = {}
    explicit_restart_intents = {
        "motivated_cut",
        "before_after",
        "chapter_boundary",
    }
    for position, (_, beat_id, index, right) in enumerate(entries):
        where = f"{beat_id}:seg{index}"
        source_key = right.asset_id or right.src
        prior_end = last_source_end.get(source_key)

        if position > 0:
            left = entries[position - 1][3]
            gameplay_boundary = (
                left.editorial_role == "gameplay"
                or right.editorial_role == "gameplay"
            )
            intent = right.transition_intent
            if gameplay_boundary and intent is None:
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-BOUNDARY",
                    message="gameplay boundary requires explicit transition_intent",
                    where=where,
                ))
            elif gameplay_boundary and intent == "no_cut":
                out.append(CheckIssue(
                    severity="error",
                    code="VQ-BOUNDARY",
                    message="transition_intent=no_cut contradicts a compiled boundary",
                    where=where,
                ))
            elif gameplay_boundary and intent == "continuous_same_take":
                left_key = left.asset_id or left.src
                expected_offset = left.offset + max(0.0, left.t1 - left.t0)
                if source_key != left_key:
                    out.append(CheckIssue(
                        severity="error",
                        code="VQ-BOUNDARY",
                        message=(
                            "continuous_same_take requires the same source asset "
                            f"({left_key} -> {source_key})"
                        ),
                        where=where,
                    ))
                elif abs(right.offset - expected_offset) > BOUNDARY_OFFSET_TOLERANCE:
                    out.append(CheckIssue(
                        severity="error",
                        code="VQ-RESTART",
                        message=(
                            "continuous_same_take source offset is discontinuous: "
                            f"expected {expected_offset:.3f}s, got {right.offset:.3f}s"
                        ),
                        where=where,
                    ))

        if (
            prior_end is not None
            and right.offset < prior_end - BOUNDARY_OFFSET_TOLERANCE
            and right.transition_intent not in explicit_restart_intents
        ):
            out.append(CheckIssue(
                severity="error",
                code="VQ-RESTART",
                message=(
                    f"source {source_key} restarts/rewinds from {prior_end:.3f}s "
                    f"to {right.offset:.3f}s without explicit cut intent"
                ),
                where=where,
            ))
        last_source_end[source_key] = (
            right.offset + max(0.0, right.t1 - right.t0)
        )
    return out


# ─── compile diagnostics -> issues ───────────────────────────────────────────

def _promote_warnings(timeline: Timeline) -> list[CheckIssue]:
    """Merge compile's structured diagnostics (VQ-WORDS out-of-range,
    VQ-OFFSET clamps) straight into the report. compile already builds these
    as CheckIssue objects with `where` set to the beat id -- nothing to
    parse or re-derive here."""
    return list(timeline.diagnostics)


# ─── VQ-SYNC postcondition ───────────────────────────────────────────────────

def _stream_duration(stream: dict) -> float | None:
    """A stream's own duration in seconds, or None when the container does
    not carry one (some formats only stamp it as a tags.DURATION string)."""
    raw = stream.get("duration")
    if raw not in (None, "N/A"):
        try:
            return float(raw)
        except (TypeError, ValueError):
            pass
    tag = (stream.get("tags") or {}).get("DURATION")
    if isinstance(tag, str) and tag.count(":") == 2:   # "HH:MM:SS.micros"
        try:
            hh, mm, ss = tag.split(":")
            return int(hh) * 3600 + int(mm) * 60 + float(ss)
        except ValueError:
            pass
    return None


def verify_output(
    video_path: str,
    expected_duration: float,
    *,
    tolerance: float = 0.25,
    require_audio: bool = True,
) -> None:
    """ffprobe the rendered file; raise RuntimeError when it disagrees with
    the expected Timeline duration. Renderers MUST call this after writing an
    MP4 — it is the postcondition that would have caught the v1 bug that
    produced a silent audio-only/truncated file for 22 blind iterations.

    Checked separately (defect 0.5 — the container duration is the MAX of
    the stream durations, so `video=1s, audio=3s, container=3s` sailed
    through a container-only check while the video track was truncated):
      - video stream presence
      - audio stream presence (`require_audio=False` for video-only files)
      - video stream duration vs expected
      - audio stream duration vs expected
      - container duration vs expected
    A stream that carries no readable duration skips its own duration check
    (the container check still applies); MP4 always carries both.
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
            encoding="utf-8", errors="replace",
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
    video_streams = [s for s in streams if s.get("codec_type") == "video"]
    audio_streams = [s for s in streams if s.get("codec_type") == "audio"]
    if not video_streams:
        raise RuntimeError(
            f"VQ-SYNC: {video_path} has no video stream "
            f"(expected {expected_duration:.3f}s of video)")
    if require_audio and not audio_streams:
        raise RuntimeError(
            f"VQ-SYNC: {video_path} has no audio stream "
            f"(expected {expected_duration:.3f}s of VO audio)")

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

    for kind, kind_streams in (("video", video_streams), ("audio", audio_streams)):
        if not kind_streams:
            continue
        sdur = _stream_duration(kind_streams[0])
        if sdur is None:
            continue
        sdelta = abs(sdur - expected_duration)
        if sdelta > tolerance:
            raise RuntimeError(
                f"VQ-SYNC: {kind} STREAM duration mismatch for {video_path}: "
                f"{kind} stream is {sdur:.3f}s vs expected "
                f"{expected_duration:.3f}s (delta {sdelta:.3f}s > tolerance "
                f"{tolerance:.3f}s); container duration alone hid this")
