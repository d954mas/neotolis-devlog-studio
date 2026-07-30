from __future__ import annotations

from dataclasses import replace

import pytest

from dlstudio.application import review as review_application
from dlstudio.foundation.api import BlobRef, CorruptObject
from dlstudio.review.api import (
    ReviewFinding,
    ReviewLocator,
    ReviewRound,
    ReviewVerdict,
)
from dlstudio.timeline.api import CheckReport, TimelineIR, VisualInstruction


class _Workflows:
    def __init__(self, latest: BlobRef | None) -> None:
        self.latest = latest

    def read_latest_review_round_ref(self) -> BlobRef | None:
        return self.latest


class _Store:
    def __init__(self, objects: dict[BlobRef, bytes]) -> None:
        self.objects = objects

    def read(self, ref: BlobRef) -> bytes:
        return self.objects[ref]


def _fixture(
    *,
    target_ids: tuple[str, ...] = ("visual.000",),
    frames: tuple[int, int] = (12, 24),
) -> tuple[_Workflows, _Store, ReviewRound, ReviewVerdict, TimelineIR]:
    timeline = TimelineIR(
        production_id="fixture.reel",
        width=1080,
        height=1920,
        fps_num=30,
        fps_den=1,
        duration_ns=2_000_000_000,
        background="black",
        visuals=(
            VisualInstruction(
                "solid",
                400_000_000,
                800_000_000,
                2,
                100,
                200,
                880,
                320,
                color="#112233",
            ),
        ),
    )
    policy = BlobRef("a" * 64, 10)
    report = CheckReport(timeline.ref, policy, ())
    finding = ReviewFinding(
        "studio.ui.001",
        "Переход слишком резкий.",
        True,
        ReviewLocator(*frames, target_ids=target_ids),
    )
    verdict = ReviewVerdict(
        artifact=BlobRef("b" * 64, 100),
        outcome="changes_requested",
        check_report=report.ref,
        constraints=BlobRef("c" * 64, 20),
        scope=("visual",),
        reviewer="author",
        reviewed_at="2026-07-30T00:00:00Z",
        findings=(finding,),
    )
    review_round = ReviewRound(verdict.ref)
    objects = {
        timeline.ref: timeline.canonical_bytes(),
        report.ref: report.canonical_bytes(),
        verdict.ref: verdict.canonical_bytes(),
        review_round.ref: review_round.canonical_bytes(),
    }
    return (
        _Workflows(review_round.ref),
        _Store(objects),
        review_round,
        verdict,
        timeline,
    )


def test_task_pack_is_absent_without_a_submitted_round() -> None:
    result = review_application.query_review_task_pack(  # type: ignore[attr-defined]
        _Workflows(None),
        _Store({}),
    )

    assert result is None


def test_task_pack_uses_only_the_exact_round_timeline_and_unique_targets() -> None:
    workflows, store, review_round, verdict, timeline = _fixture()

    pack = review_application.query_review_task_pack(  # type: ignore[attr-defined]
        workflows,
        store,
    )

    assert pack is not None
    assert pack.latest_round == review_round.ref
    assert pack.review_round == review_round
    assert pack.verdict_ref == verdict.ref
    assert pack.verdict == verdict
    assert pack.artifact == verdict.artifact
    assert pack.timeline == timeline.ref
    assert pack.check_report == verdict.check_report
    assert pack.constraints == verdict.constraints
    assert (
        pack.width,
        pack.height,
        pack.fps_num,
        pack.fps_den,
        pack.duration_ns,
    ) == (1080, 1920, 30, 1, 2_000_000_000)
    assert [
        (
            target.item_id,
            target.kind,
            target.lane,
            target.label,
            target.start_ns,
            target.duration_ns,
        )
        for target in pack.target_snapshots
    ] == [
        (
            "visual.000",
            "visual",
            "layer.2",
            "solid #112233",
            400_000_000,
            800_000_000,
        )
    ]
    assert pack.source_mapping.status == "unavailable"


def test_task_pack_rejects_a_target_missing_from_its_exact_timeline() -> None:
    workflows, store, _, _, _ = _fixture(
        target_ids=("visual.999",),
    )

    with pytest.raises(CorruptObject, match="unknown review targets"):
        review_application.query_review_task_pack(  # type: ignore[attr-defined]
            workflows,
            store,
        )


def test_task_pack_rejects_a_timeline_with_the_wrong_identity() -> None:
    workflows, store, review_round, verdict, timeline = _fixture()
    other = replace(timeline, background="#010203")
    report = CheckReport(other.ref, BlobRef("d" * 64, 10), ())
    forged_verdict = replace(verdict, check_report=report.ref)
    forged_round = ReviewRound(forged_verdict.ref)
    store.objects[report.ref] = report.canonical_bytes()
    store.objects[forged_verdict.ref] = forged_verdict.canonical_bytes()
    store.objects[forged_round.ref] = forged_round.canonical_bytes()
    store.objects[other.ref] = timeline.canonical_bytes()
    workflows.latest = forged_round.ref

    with pytest.raises(CorruptObject, match="timeline"):
        review_application.query_review_task_pack(  # type: ignore[attr-defined]
            workflows,
            store,
        )


def test_task_pack_rejects_a_target_outside_the_finding_range() -> None:
    workflows, store, _, _, _ = _fixture(frames=(0, 1))

    with pytest.raises(CorruptObject, match="inactive review targets"):
        review_application.query_review_task_pack(  # type: ignore[attr-defined]
            workflows,
            store,
        )


def test_task_pack_selects_the_latest_round_only_once() -> None:
    workflows, store, review_round, verdict, _ = _fixture()

    class _ChangingWorkflows:
        def __init__(self) -> None:
            self.calls = 0

        def read_latest_review_round_ref(self) -> BlobRef | None:
            self.calls += 1
            return review_round.ref if self.calls == 1 else None

    changing = _ChangingWorkflows()
    pack = review_application.query_review_task_pack(  # type: ignore[attr-defined]
        changing,
        store,
    )

    assert pack is not None
    assert pack.latest_round == review_round.ref
    assert pack.verdict == verdict
    assert changing.calls == 1


def test_task_pack_rejects_an_oversized_projection_without_truncation() -> None:
    workflows, store, _, verdict, _ = _fixture()
    huge_finding = replace(
        verdict.findings[0],
        text="x" * 2_096_000,
    )
    huge_verdict = replace(verdict, findings=(huge_finding,))
    huge_round = ReviewRound(huge_verdict.ref)
    store.objects[huge_verdict.ref] = huge_verdict.canonical_bytes()
    store.objects[huge_round.ref] = huge_round.canonical_bytes()
    workflows.latest = huge_round.ref

    with pytest.raises(CorruptObject, match="task-pack limit"):
        review_application.query_review_task_pack(  # type: ignore[attr-defined]
            workflows,
            store,
        )


@pytest.mark.parametrize(
    ("outcome", "keep_findings"),
    (("block", True), ("pass", False)),
)
def test_task_pack_returns_the_latest_exact_outcome(
    outcome: str,
    keep_findings: bool,
) -> None:
    workflows, store, _, verdict, _ = _fixture()
    selected = replace(
        verdict,
        outcome=outcome,
        findings=verdict.findings if keep_findings else (),
    )
    selected_round = ReviewRound(selected.ref)
    store.objects[selected.ref] = selected.canonical_bytes()
    store.objects[selected_round.ref] = selected_round.canonical_bytes()
    workflows.latest = selected_round.ref

    pack = review_application.query_review_task_pack(  # type: ignore[attr-defined]
        workflows,
        store,
    )

    assert pack is not None
    assert pack.verdict.outcome == outcome
    if keep_findings:
        assert [item.item_id for item in pack.target_snapshots] == [
            "visual.000"
        ]
    else:
        assert pack.target_snapshots == ()
