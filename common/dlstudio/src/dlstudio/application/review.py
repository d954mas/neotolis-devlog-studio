"""Read-only projection for frame-accurate review of the exact final artifact."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from dlstudio.foundation.api import BlobRef, CorruptObject
from dlstudio.review.api import (
    ReviewRound,
    ReviewVerdict,
    validate_review_round_transition,
)
from dlstudio.timeline.api import CheckReport, TimelineIR
from dlstudio.workflow.api import WorkflowStore, WorkflowRun

from .release import BlobStore

MAX_REVIEW_LINEAGE_DEPTH = 1024


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
