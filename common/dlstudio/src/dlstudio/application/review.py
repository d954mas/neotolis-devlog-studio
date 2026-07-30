"""Read-only projection for frame-accurate review of the exact final artifact."""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from functools import lru_cache
from pathlib import Path
from typing import Literal

from dlstudio.foundation.api import BlobRef, CorruptObject
from dlstudio.rendering.api import (
    PresentationFingerprint,
    extract_presentation_frame,
    extract_presentation_waveform,
)
from dlstudio.review.api import (
    ReviewRegion,
    ReviewRound,
    ReviewVerdict,
    validate_review_round_transition,
)
from dlstudio.timeline.api import CheckReport, TimelineIR
from dlstudio.workflow.api import WorkflowStore, WorkflowRun

from .release import BlobStore

MAX_REVIEW_LINEAGE_DEPTH = 1024
MAX_REVIEW_TASK_TARGETS = 4096
MAX_REVIEW_TASK_PACK_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class ReviewTimelineItem:
    item_id: str
    kind: Literal["visual", "audio", "transition"]
    lane: str
    label: str
    start_ns: int
    duration_ns: int
    z: int | None = None


@dataclass(frozen=True, slots=True)
class ReviewContext:
    artifact: BlobRef
    timeline: BlobRef
    check_report: BlobRef
    constraints: BlobRef
    latest_round: BlobRef | None
    latest_verdict: ReviewVerdict | None
    width: int
    height: int
    fps_num: int
    fps_den: int
    duration_ns: int
    items: tuple[ReviewTimelineItem, ...]


@dataclass(frozen=True, slots=True)
class ReviewHistoryEntry:
    round_ref: BlobRef
    review_round: ReviewRound
    verdict: ReviewVerdict
    timeline: BlobRef


@dataclass(frozen=True, slots=True)
class ReviewSourceMapping:
    status: Literal["unavailable"] = "unavailable"


@dataclass(frozen=True, slots=True)
class ReviewTaskPack:
    latest_round: BlobRef
    review_round: ReviewRound
    verdict_ref: BlobRef
    verdict: ReviewVerdict
    artifact: BlobRef
    timeline: BlobRef
    check_report: BlobRef
    constraints: BlobRef
    width: int
    height: int
    fps_num: int
    fps_den: int
    duration_ns: int
    target_snapshots: tuple[ReviewTimelineItem, ...]
    source_mapping: ReviewSourceMapping


@dataclass(frozen=True, slots=True)
class ReviewArtifactContext:
    artifact: BlobRef
    timeline: BlobRef
    width: int
    height: int
    fps_num: int
    fps_den: int
    duration_ns: int


@dataclass(frozen=True, slots=True)
class ReviewFrameEvidence:
    content_ref: BlobRef
    content: bytes
    media_type: str


@dataclass(frozen=True, slots=True)
class ReviewWaveform:
    artifact: BlobRef
    duration_ns: int
    sample_count: int
    has_audio: bool
    peaks_milli: tuple[int, ...]


@dataclass(frozen=True, slots=True)
class _VerifiedPresentationSource:
    artifact: BlobRef
    path: Path

    def path_for(self, ref: BlobRef) -> Path:
        if ref != self.artifact:
            raise ValueError("presentation source identity changed")
        return self.path

    def verify(self, ref: BlobRef) -> None:
        self.verify_metadata(ref)

    def verify_metadata(self, ref: BlobRef) -> None:
        if ref != self.artifact:
            raise ValueError("presentation source identity changed")
        if not self.path.is_file() or self.path.stat().st_size != ref.size:
            raise ValueError("verified presentation source changed")


def _outputs(workflow: WorkflowRun, stage: str) -> dict[str, BlobRef]:
    attempt = next(
        (
            item
            for item in workflow.attempts
            if item.stage == stage and item.state == "succeeded"
        ),
        None,
    )
    if attempt is None:
        raise ValueError(f"workflow has no completed {stage} stage")
    return {item.name: item.blob for item in attempt.outputs}


def _visual_label(visual: object) -> str:
    kind = str(getattr(visual, "kind"))
    if kind == "text":
        text = str(getattr(visual, "text") or "")
        return text if len(text) <= 48 else f"{text[:45]}..."
    asset = getattr(visual, "asset")
    if asset is not None:
        return str(asset.asset_id)
    color = getattr(visual, "color")
    return f"solid {color}"


def _audio_label(audio: object) -> str:
    asset = getattr(audio, "asset")
    details = [str(asset.asset_id)]
    gain = int(getattr(audio, "gain_db_milli"))
    if gain:
        details.append(f"{gain / 1000:+g} dB")
    fade_in = int(getattr(audio, "fade_in_ns"))
    fade_out = int(getattr(audio, "fade_out_ns"))
    if fade_in or fade_out:
        details.append(
            f"fade {fade_in / 1_000_000_000:g}/"
            f"{fade_out / 1_000_000_000:g}s"
        )
    if bool(getattr(audio, "duck")):
        details.append("duck")
    if bool(getattr(audio, "loop")):
        details.append("loop")
    return " · ".join(details)


def _timeline_items(timeline: TimelineIR) -> tuple[ReviewTimelineItem, ...]:
    items: list[ReviewTimelineItem] = []
    for index, visual in enumerate(timeline.visuals):
        visual_id = f"visual.{index:03d}"
        items.append(
            ReviewTimelineItem(
                visual_id,
                "visual",
                f"layer.{visual.z}",
                _visual_label(visual),
                visual.start_ns,
                visual.duration_ns,
                visual.z,
            )
        )
        if visual.transition != "cut" and visual.transition_ns:
            items.append(
                ReviewTimelineItem(
                    f"transition.visual.{index:03d}",
                    "transition",
                    "transitions",
                    visual.transition.replace("_", " "),
                    visual.start_ns,
                    visual.transition_ns,
                    visual.z,
                )
            )
        if visual.fade_out_ns:
            items.append(
                ReviewTimelineItem(
                    f"transition.fadeout.{index:03d}",
                    "transition",
                    "transitions",
                    "fade out",
                    visual.end_ns - visual.fade_out_ns,
                    visual.fade_out_ns,
                    visual.z,
                )
            )
    for index, fade in enumerate(timeline.video_fades):
        items.append(
            ReviewTimelineItem(
                f"transition.fade.{index:03d}",
                "transition",
                "transitions",
                f"fade {fade.direction}",
                fade.start_ns,
                fade.duration_ns,
            )
        )
    for index, audio in enumerate(timeline.audio):
        items.append(
            ReviewTimelineItem(
                f"audio.{index:03d}",
                "audio",
                f"audio.{audio.role}",
                _audio_label(audio),
                audio.start_ns,
                audio.duration_ns,
            )
        )
    return tuple(
        sorted(
            items,
            key=lambda item: (
                item.lane,
                item.start_ns,
                item.item_id,
            ),
        )
    )


def query_review_context(
    workflows: WorkflowStore,
    store: BlobStore,
) -> ReviewContext:
    """Project only immutable inputs needed by the current review surface."""

    workflow = workflows.read_current()
    if workflow is None:
        raise ValueError("production has no workflow")
    prepared = _outputs(workflow, "prepare")
    finalized = _outputs(workflow, "final")
    if "timeline" not in prepared or "artifact" not in finalized:
        raise ValueError("review inputs are incomplete")
    timeline_ref = prepared["timeline"]
    timeline = TimelineIR.from_canonical_bytes(store.read(timeline_ref))
    report_ref = prepared.get("check_report")
    if report_ref is None:
        raise ValueError("review check report is missing")
    constraints_ref = prepared.get("constraints")
    if constraints_ref is None:
        raise ValueError("review constraints are missing")
    report = CheckReport.from_canonical_bytes(store.read(report_ref))
    if report.timeline != timeline_ref:
        raise ValueError("review timeline differs from its check report")
    latest_round = workflows.read_latest_review_round_ref()
    history = _load_review_history(latest_round, store)
    return ReviewContext(
        artifact=finalized["artifact"],
        timeline=timeline_ref,
        check_report=report_ref,
        constraints=constraints_ref,
        latest_round=latest_round,
        latest_verdict=None if not history else history[0].verdict,
        width=timeline.width,
        height=timeline.height,
        fps_num=timeline.fps_num,
        fps_den=timeline.fps_den,
        duration_ns=timeline.duration_ns,
        items=_timeline_items(timeline),
    )


def _load_review_history(
    selected: BlobRef | None,
    store: BlobStore,
) -> tuple[ReviewHistoryEntry, ...]:
    entries: list[ReviewHistoryEntry] = []
    seen: set[BlobRef] = set()
    while selected is not None:
        if selected in seen:
            raise CorruptObject("review round lineage contains a cycle")
        if len(entries) == MAX_REVIEW_LINEAGE_DEPTH:
            raise CorruptObject("review round lineage exceeds its depth limit")
        seen.add(selected)
        try:
            review_round = ReviewRound.from_canonical_bytes(
                store.read(selected)
            )
            verdict = ReviewVerdict.from_canonical_bytes(
                store.read(review_round.verdict)
            )
            report = CheckReport.from_canonical_bytes(
                store.read(verdict.check_report)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptObject("invalid review round lineage") from exc
        entries.append(
            ReviewHistoryEntry(
                selected,
                review_round,
                verdict,
                report.timeline,
            )
        )
        selected = review_round.previous_round

    for index, entry in enumerate(entries):
        if entry.review_round.ref != entry.round_ref:
            raise CorruptObject("invalid review round lineage")
        previous = entries[index + 1] if index + 1 < len(entries) else None
        try:
            validate_review_round_transition(
                entry.review_round,
                entry.verdict,
                previous_round=(
                    None if previous is None else previous.review_round
                ),
                previous_verdict=(
                    None if previous is None else previous.verdict
                ),
            )
        except ValueError as exc:
            raise CorruptObject("invalid review round transition") from exc
    return tuple(entries)


def query_review_history(
    workflows: WorkflowStore,
    store: BlobStore,
) -> tuple[ReviewHistoryEntry, ...]:
    """Load and validate the bounded exact review lineage, latest first."""

    return _load_review_history(
        workflows.read_latest_review_round_ref(),
        store,
    )


def query_review_task_pack(
    workflows: WorkflowStore,
    store: BlobStore,
) -> ReviewTaskPack | None:
    """Build one bounded agent projection from the exact latest review."""

    history = query_review_history(workflows, store)
    if not history:
        return None
    latest = history[0]
    try:
        timeline = TimelineIR.from_canonical_bytes(
            store.read(latest.timeline)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CorruptObject("invalid task-pack timeline") from exc
    if timeline.ref != latest.timeline:
        raise CorruptObject("task-pack timeline identity changed")

    timeline_items = _timeline_items(timeline)
    by_id = {item.item_id: item for item in timeline_items}
    if len(by_id) != len(timeline_items):
        raise CorruptObject("task-pack timeline has duplicate target IDs")
    target_ids = {
        target_id
        for finding in latest.verdict.findings
        if finding.locator is not None
        for target_id in finding.locator.target_ids
    }
    unknown = target_ids - by_id.keys()
    if unknown:
        raise CorruptObject(
            f"task pack has unknown review targets: {sorted(unknown)}"
        )
    frame_denominator = 1_000_000_000 * timeline.fps_den
    inactive: set[str] = set()
    for finding in latest.verdict.findings:
        locator = finding.locator
        if locator is None:
            continue
        for target_id in locator.target_ids:
            item = by_id.get(target_id)
            if item is None:
                continue
            item_start = (
                item.start_ns * timeline.fps_num
                + frame_denominator
                - 1
            ) // frame_denominator
            item_end = (
                (item.start_ns + item.duration_ns) * timeline.fps_num
                + frame_denominator
                - 1
            ) // frame_denominator
            if (
                item_start >= locator.end_frame_exclusive
                or item_end <= locator.start_frame
            ):
                inactive.add(target_id)
    if inactive:
        raise CorruptObject(
            f"task pack has inactive review targets: {sorted(inactive)}"
        )
    if len(target_ids) > MAX_REVIEW_TASK_TARGETS:
        raise CorruptObject("review task pack has too many targets")
    selected_targets = tuple(
        by_id[target_id] for target_id in sorted(target_ids)
    )
    task_pack = ReviewTaskPack(
        latest_round=latest.round_ref,
        review_round=latest.review_round,
        verdict_ref=latest.review_round.verdict,
        verdict=latest.verdict,
        artifact=latest.verdict.artifact,
        timeline=latest.timeline,
        check_report=latest.verdict.check_report,
        constraints=latest.verdict.constraints,
        width=timeline.width,
        height=timeline.height,
        fps_num=timeline.fps_num,
        fps_den=timeline.fps_den,
        duration_ns=timeline.duration_ns,
        target_snapshots=selected_targets,
        source_mapping=ReviewSourceMapping(),
    )
    encoded = json.dumps(
        asdict(task_pack),
        ensure_ascii=False,
        allow_nan=False,
        separators=(",", ":"),
    ).encode("utf-8")
    if len(encoded) > MAX_REVIEW_TASK_PACK_BYTES:
        raise CorruptObject("review projection exceeds the task-pack limit")
    return task_pack


def query_current_review(
    workflows: WorkflowStore,
    store: BlobStore,
) -> ReviewVerdict:
    """Return the exact current verdict for UI reloads and agent consumption."""

    history = query_review_history(workflows, store)
    if not history:
        raise ValueError("workflow has no submitted review")
    return history[0].verdict


def query_authorized_review_artifacts(
    workflows: WorkflowStore,
    store: BlobStore,
) -> tuple[BlobRef, ...]:
    """Return exact current and historical artifacts authorized for review."""

    artifacts = {
        entry.verdict.artifact
        for entry in query_review_history(workflows, store)
    }
    workflow = workflows.read_current()
    if workflow is not None:
        try:
            current = _outputs(workflow, "final").get("artifact")
        except ValueError:
            current = None
        if current is not None:
            artifacts.add(current)
    return tuple(sorted(artifacts, key=lambda item: (item.sha256, item.size)))


def query_authorized_review_artifact_contexts(
    workflows: WorkflowStore,
    store: BlobStore,
) -> tuple[ReviewArtifactContext, ...]:
    """Map every authorized artifact to its exact clock and geometry."""

    timeline_cache: dict[BlobRef, TimelineIR] = {}
    contexts: dict[BlobRef, ReviewArtifactContext] = {}

    def add(artifact: BlobRef, timeline_ref: BlobRef) -> None:
        timeline = timeline_cache.get(timeline_ref)
        if timeline is None:
            try:
                timeline = TimelineIR.from_canonical_bytes(
                    store.read(timeline_ref)
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise CorruptObject(
                    "invalid authorized review timeline"
                ) from exc
            if timeline.ref != timeline_ref:
                raise CorruptObject(
                    "authorized review timeline identity changed"
                )
            timeline_cache[timeline_ref] = timeline
        candidate = ReviewArtifactContext(
            artifact=artifact,
            timeline=timeline_ref,
            width=timeline.width,
            height=timeline.height,
            fps_num=timeline.fps_num,
            fps_den=timeline.fps_den,
            duration_ns=timeline.duration_ns,
        )
        existing = contexts.get(artifact)
        if existing is not None:
            existing_clock = (
                existing.width,
                existing.height,
                existing.fps_num,
                existing.fps_den,
                existing.duration_ns,
            )
            candidate_clock = (
                candidate.width,
                candidate.height,
                candidate.fps_num,
                candidate.fps_den,
                candidate.duration_ns,
            )
            if existing_clock != candidate_clock:
                raise ValueError(
                    "review artifact has ambiguous timeline contexts"
                )
            return
        contexts[artifact] = candidate

    workflow = workflows.read_current()
    if workflow is not None:
        try:
            prepared = _outputs(workflow, "prepare")
            finalized = _outputs(workflow, "final")
        except ValueError:
            prepared = {}
            finalized = {}
        timeline_ref = prepared.get("timeline")
        artifact = finalized.get("artifact")
        if timeline_ref is not None and artifact is not None:
            add(artifact, timeline_ref)

    for entry in query_review_history(workflows, store):
        add(entry.verdict.artifact, entry.timeline)

    return tuple(
        contexts[key]
        for key in sorted(contexts, key=lambda ref: (ref.sha256, ref.size))
    )


@lru_cache(maxsize=1)
def _presentation_fingerprint() -> PresentationFingerprint:
    return PresentationFingerprint.detect()


def query_review_frame_evidence(
    context: ReviewArtifactContext,
    verified_source: Path,
    *,
    frame: int,
    width: int,
    region_milli: tuple[int, int, int, int] | None,
    cache_root: Path,
    fingerprint: PresentationFingerprint | None = None,
) -> ReviewFrameEvidence:
    """Extract one bounded frame/crop from an already authorized source."""

    region = (
        None
        if region_milli is None
        else ReviewRegion(*region_milli)
    )
    crop = (
        None
        if region is None
        else (
            region.x_milli,
            region.y_milli,
            region.width_milli,
            region.height_milli,
        )
    )
    result = extract_presentation_frame(
        context.artifact,
        _VerifiedPresentationSource(
            context.artifact,
            verified_source.resolve(strict=True),
        ),
        frame=frame,
        duration_ns=context.duration_ns,
        fps_num=context.fps_num,
        fps_den=context.fps_den,
        source_width=context.width,
        source_height=context.height,
        width=width,
        crop_milli=crop,
        cache_root=cache_root,
        fingerprint=fingerprint or _presentation_fingerprint(),
    )
    return ReviewFrameEvidence(
        content_ref=result.blob,
        content=result.content,
        media_type=result.media_type,
    )


def query_review_waveform(
    context: ReviewArtifactContext,
    verified_source: Path,
    *,
    sample_count: int,
    cache_root: Path,
    fingerprint: PresentationFingerprint | None = None,
) -> ReviewWaveform:
    """Extract one bounded final-mix peak envelope for review navigation."""

    result = extract_presentation_waveform(
        context.artifact,
        _VerifiedPresentationSource(
            context.artifact,
            verified_source.resolve(strict=True),
        ),
        duration_ns=context.duration_ns,
        sample_count=sample_count,
        cache_root=cache_root,
        fingerprint=fingerprint or _presentation_fingerprint(),
    )
    return ReviewWaveform(
        artifact=context.artifact,
        duration_ns=context.duration_ns,
        sample_count=sample_count,
        has_audio=result.has_audio,
        peaks_milli=result.samples,
    )
