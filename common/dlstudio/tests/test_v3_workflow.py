from __future__ import annotations

import pytest

from dlstudio.foundation.api import BlobRef
from dlstudio.workflow.api import NamedRef, STAGES, WorkflowRun


def test_empty_workflow_has_one_obvious_next_step() -> None:
    run = WorkflowRun("run.1", "fixture.reel", "reel")
    assert run.current_stage == "prepare"
    assert not run.completed
    assert WorkflowRun.from_canonical_bytes(run.canonical_bytes()) == run


def _complete_through(run: WorkflowRun, last: str) -> WorkflowRun:
    for stage in STAGES:
        if STAGES.index(stage) > STAGES.index(last):  # type: ignore[arg-type]
            break
        run = run.start(
            stage,
            (NamedRef("input", BlobRef(str(STAGES.index(stage) + 1) * 64, 1)),),
            contract=f"{stage}.v1",
        )
        operation_id = run.attempts[-1].operation_id
        outputs = (
            (NamedRef("receipt", BlobRef("f" * 64, 10)),)
            if stage == "deliver"
            else (NamedRef("output", BlobRef("a" * 64, 10)),)
        )
        run = run.succeed(operation_id, outputs)
        if stage == "package":
            run = run.allow_delivery(BlobRef("e" * 64, 10))
    return run


def test_stage_order_is_helpful_and_cannot_be_skipped() -> None:
    run = WorkflowRun("run.1", "fixture.reel", "reel")
    with pytest.raises(ValueError, match="prepare"):
        run.start("draft", (), contract="draft.v1")
    prepared = _complete_through(run, "prepare")
    assert prepared.current_stage == "draft"


def test_same_operation_and_success_are_idempotent() -> None:
    run = WorkflowRun("run.1", "fixture.reel", "reel")
    running = run.start("prepare", (), contract="prepare.v1")
    assert running.start("prepare", (), contract="prepare.v1") is running
    operation_id = running.attempts[0].operation_id
    outputs = (NamedRef("manifest", BlobRef("a" * 64, 2)),)
    succeeded = running.succeed(operation_id, outputs)
    assert succeeded.succeed(operation_id, outputs) is succeeded
    with pytest.raises(ValueError, match="different outputs"):
        succeeded.succeed(
            operation_id,
            (NamedRef("manifest", BlobRef("b" * 64, 2)),),
        )


def test_input_order_does_not_create_a_fake_new_attempt() -> None:
    run = WorkflowRun("run.1", "fixture.reel", "reel")
    first = NamedRef("first", BlobRef("1" * 64, 1))
    second = NamedRef("second", BlobRef("2" * 64, 1))
    running = run.start(
        "prepare", (second, first), contract="prepare.v1"
    )
    assert (
        running.start(
            "prepare", (first, second), contract="prepare.v1"
        )
        is running
    )


def test_changed_upstream_input_invalidates_downstream_and_eligibility() -> None:
    ready = _complete_through(
        WorkflowRun("run.1", "fixture.reel", "reel"),
        "package",
    )
    restarted = ready.start(
        "draft",
        (NamedRef("script", BlobRef("d" * 64, 3)),),
        contract="draft.v2",
    )
    assert [item.stage for item in restarted.attempts] == ["prepare", "draft"]
    assert restarted.eligible_candidate is None
    assert restarted.current_stage == "draft"


def test_failed_stage_retries_without_keeping_attempt_ledger() -> None:
    run = _complete_through(
        WorkflowRun("run.1", "fixture.reel", "reel"),
        "prepare",
    ).start("draft", (), contract="draft.v1")
    failed = run.fail(run.attempts[-1].operation_id, "ffmpeg stopped")
    retried = failed.start("draft", (), contract="draft.v1")
    assert len(retried.attempts) == 2
    assert retried.attempts[-1].state == "running"


def test_delivery_records_one_exact_receipt() -> None:
    ready = _complete_through(
        WorkflowRun("run.1", "fixture.reel", "capture_vo"),
        "package",
    )
    delivering = ready.start(
        "deliver",
        (NamedRef("candidate", ready.eligible_candidate),),  # type: ignore[arg-type]
        contract="local.delivery.v1",
    )
    delivered = delivering.succeed(
        delivering.attempts[-1].operation_id,
        (NamedRef("receipt", BlobRef("f" * 64, 10)),),
    )
    assert delivered.completed
    assert delivered.delivery_receipt == BlobRef("f" * 64, 10)
