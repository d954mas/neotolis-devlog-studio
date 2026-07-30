from __future__ import annotations

import hashlib
from typing import Mapping

import pytest

from dlstudio.application.review import (
    MAX_REVIEW_LINEAGE_DEPTH,
    query_authorized_review_artifacts,
    query_review_history,
)
from dlstudio.foundation.api import BlobRef, CorruptObject
from dlstudio.review.api import ReviewRound, ReviewVerdict
from dlstudio.timeline.api import CheckReport, TimelineIR, VisualInstruction
from dlstudio.workflow.api import NamedRef, WorkflowRun


class _Workflows:
    def __init__(
        self,
        latest_round: BlobRef | None,
        current: WorkflowRun | None = None,
    ) -> None:
        self.latest_round = latest_round
        self.current = current

    def read_current(self) -> WorkflowRun | None:
        return self.current

    def read_latest_review_round_ref(self) -> BlobRef | None:
        return self.latest_round


class _Store:
    def __init__(self, objects: Mapping[BlobRef, bytes]) -> None:
        self.objects = dict(objects)

    def read(self, ref: BlobRef) -> bytes:
        return self.objects[ref]


def _raw_ref(raw: bytes) -> BlobRef:
    return BlobRef(hashlib.sha256(raw).hexdigest(), len(raw))


def _report(timeline: BlobRef | None = None) -> CheckReport:
    return CheckReport(
        timeline or BlobRef("1" * 64, 101),
        BlobRef("2" * 64, 102),
        (),
    )


def _verdict(
    report: CheckReport,
    *,
    artifact: BlobRef | None = None,
) -> ReviewVerdict:
    return ReviewVerdict(
        artifact=artifact or BlobRef("3" * 64, 103),
        outcome="block",
        check_report=report.ref,
        constraints=BlobRef("4" * 64, 104),
        scope=("audio", "constraints", "visual"),
        reviewer="video.reviewer",
        reviewed_at="2026-07-30T00:00:00Z",
    )


def _lineage(
    length: int,
    *,
    report: CheckReport | None = None,
    artifact: BlobRef | None = None,
) -> tuple[_Workflows, _Store, tuple[BlobRef, ...]]:
    check_report = report or _report()
    verdict = _verdict(check_report, artifact=artifact)
    objects = {
        check_report.ref: check_report.canonical_bytes(),
        verdict.ref: verdict.canonical_bytes(),
    }
    previous: ReviewRound | None = None
    oldest_first: list[BlobRef] = []
    for _ in range(length):
        current = ReviewRound(
            verdict.ref,
            None if previous is None else previous.ref,
        )
        objects[current.ref] = current.canonical_bytes()
        oldest_first.append(current.ref)
        previous = current
    latest = None if previous is None else previous.ref
    return (
        _Workflows(latest),
        _Store(objects),
        tuple(reversed(oldest_first)),
    )


def _succeed(
    workflow: WorkflowRun,
    stage: str,
    outputs: tuple[NamedRef, ...],
) -> WorkflowRun:
    running = workflow.start(stage, (), contract=f"fixture.{stage}.v1")
    return running.succeed(running.attempts[-1].operation_id, outputs)


def _review_ready_workflow(
    timeline: TimelineIR,
    report: CheckReport,
    *,
    artifact: BlobRef,
    constraints: BlobRef,
) -> WorkflowRun:
    workflow = WorkflowRun("run.main", "fixture.reel", "reel")
    workflow = _succeed(
        workflow,
        "prepare",
        (
            NamedRef("timeline", timeline.ref),
            NamedRef("check_policy", report.policy),
            NamedRef("check_report", report.ref),
            NamedRef("constraints", constraints),
        ),
    )
    workflow = _succeed(
        workflow,
        "draft",
        (NamedRef("artifact", BlobRef("5" * 64, 105)),),
    )
    return _succeed(
        workflow,
        "final",
        (
            NamedRef("artifact", artifact),
            NamedRef("execution", BlobRef("6" * 64, 106)),
            NamedRef("render_options", BlobRef("7" * 64, 107)),
        ),
    )


def test_history_loads_101_valid_linked_rounds_latest_first() -> None:
    workflows, store, expected_refs = _lineage(101)

    history = query_review_history(workflows, store)  # type: ignore[arg-type]

    assert len(history) == 101
    assert tuple(entry.round_ref for entry in history) == expected_refs
    assert all(entry.timeline == BlobRef("1" * 64, 101) for entry in history)


def test_history_accepts_exact_depth_limit() -> None:
    workflows, store, expected_refs = _lineage(MAX_REVIEW_LINEAGE_DEPTH)

    history = query_review_history(workflows, store)  # type: ignore[arg-type]

    assert len(history) == MAX_REVIEW_LINEAGE_DEPTH
    assert history[0].round_ref == expected_refs[0]
    assert history[-1].round_ref == expected_refs[-1]


def test_history_rejects_lineage_past_depth_limit() -> None:
    workflows, store, _ = _lineage(MAX_REVIEW_LINEAGE_DEPTH + 1)

    with pytest.raises(CorruptObject, match="depth limit"):
        query_review_history(workflows, store)  # type: ignore[arg-type]


def test_history_rejects_self_cycle_as_corrupt() -> None:
    report = _report()
    verdict = _verdict(report)
    selected = BlobRef("8" * 64, 108)
    review_round = ReviewRound(verdict.ref, selected)
    store = _Store(
        {
            selected: review_round.canonical_bytes(),
            verdict.ref: verdict.canonical_bytes(),
            report.ref: report.canonical_bytes(),
        }
    )

    with pytest.raises(CorruptObject, match="cycle"):
        query_review_history(  # type: ignore[arg-type]
            _Workflows(selected),
            store,
        )


def test_history_rejects_two_node_cycle_as_corrupt() -> None:
    report = _report()
    verdict = _verdict(report)
    first_ref = BlobRef("8" * 64, 108)
    second_ref = BlobRef("9" * 64, 109)
    first = ReviewRound(verdict.ref, second_ref)
    second = ReviewRound(verdict.ref, first_ref)
    store = _Store(
        {
            first_ref: first.canonical_bytes(),
            second_ref: second.canonical_bytes(),
            verdict.ref: verdict.canonical_bytes(),
            report.ref: report.canonical_bytes(),
        }
    )

    with pytest.raises(CorruptObject, match="cycle"):
        query_review_history(  # type: ignore[arg-type]
            _Workflows(first_ref),
            store,
        )


@pytest.mark.parametrize("component", ["round", "verdict", "check_report"])
def test_history_reports_corrupt_linked_objects_as_corrupt(
    component: str,
) -> None:
    invalid_raw = b"{not canonical json"
    invalid_ref = _raw_ref(invalid_raw)
    report = _report()
    report_ref = invalid_ref if component == "check_report" else report.ref
    verdict = ReviewVerdict(
        artifact=BlobRef("3" * 64, 103),
        outcome="block",
        check_report=report_ref,
        constraints=BlobRef("4" * 64, 104),
        scope=("audio", "constraints", "visual"),
        reviewer="video.reviewer",
        reviewed_at="2026-07-30T00:00:00Z",
    )
    verdict_ref = invalid_ref if component == "verdict" else verdict.ref
    review_round = ReviewRound(verdict_ref)
    selected = invalid_ref if component == "round" else review_round.ref
    objects = {
        selected: (
            invalid_raw
            if component == "round"
            else review_round.canonical_bytes()
        ),
        verdict_ref: (
            invalid_raw
            if component == "verdict"
            else verdict.canonical_bytes()
        ),
        report_ref: (
            invalid_raw
            if component == "check_report"
            else report.canonical_bytes()
        ),
    }

    with pytest.raises(CorruptObject, match="invalid review round lineage"):
        query_review_history(  # type: ignore[arg-type]
            _Workflows(selected),
            _Store(objects),
        )


def test_authorized_artifacts_include_current_and_lineage_only() -> None:
    timeline = TimelineIR(
        production_id="fixture.reel",
        width=1080,
        height=1920,
        fps_num=30,
        fps_den=1,
        duration_ns=1_000_000_000,
        background="black",
        visuals=(
            VisualInstruction(
                "solid",
                0,
                1_000_000_000,
                0,
                0,
                0,
                1080,
                1920,
                color="black",
            ),
        ),
    )
    current_artifact = BlobRef("a" * 64, 201)
    historical_artifact = BlobRef("b" * 64, 202)
    unrelated_artifact = BlobRef("c" * 64, 203)
    report = _report(timeline.ref)
    constraints = BlobRef("4" * 64, 104)
    lineage_workflows, lineage_store, expected_refs = _lineage(
        2,
        report=report,
        artifact=historical_artifact,
    )
    workflow = _review_ready_workflow(
        timeline,
        report,
        artifact=current_artifact,
        constraints=constraints,
    )
    objects = dict(lineage_store.objects)
    objects[timeline.ref] = timeline.canonical_bytes()
    objects[unrelated_artifact] = b"unrelated"
    workflows = _Workflows(expected_refs[0], workflow)

    authorized = query_authorized_review_artifacts(  # type: ignore[arg-type]
        workflows,
        _Store(objects),
    )

    assert set(authorized) == {current_artifact, historical_artifact}
    assert current_artifact in authorized
    assert unrelated_artifact not in authorized
