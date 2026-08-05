from __future__ import annotations

from pathlib import Path
from typing import Literal

import pytest

from dlstudio.foundation.api import BlobRef, CasConflict, CorruptObject
from dlstudio.persistence import ProductionRepository, WorkflowRepository
from dlstudio.review.api import (
    ReviewFinding,
    ReviewResolution,
    ReviewRound,
    ReviewVerdict,
)
from dlstudio.workflow.api import NamedRef, WorkflowRun


def _repository(tmp_path: Path) -> ProductionRepository:
    return ProductionRepository(
        object_root=tmp_path / "objects",
        state_root=tmp_path / "state",
        staging_root=tmp_path / "staging",
        lock_root=tmp_path / "locks",
        production_id="fixture.reel",
    )


def _save_transition(
    workflows: WorkflowRepository,
    previous: WorkflowRun,
    current: WorkflowRun,
) -> None:
    workflows.save(
        current,
        expected_workflow_revision=previous.revision,
        expected_head_revision=workflows.head_revision(),
    )


def _review_ready(
    storage: ProductionRepository,
) -> tuple[WorkflowRepository, WorkflowRun, dict[str, BlobRef]]:
    workflows = WorkflowRepository(storage)
    refs = {
        name: storage.objects.put_bytes(name.encode("utf-8"))
        for name in (
            "timeline",
            "check_policy",
            "check_report",
            "constraints",
            "draft_artifact",
            "final_artifact",
            "artifact_report",
            "publication_manifest",
            "execution",
            "render_options",
        )
    }
    current = WorkflowRun("run.main", "fixture.reel", "reel")
    workflows.save(
        current,
        expected_workflow_revision=-1,
        expected_head_revision=0,
    )

    stage_outputs = {
        "prepare": (
            NamedRef("timeline", refs["timeline"]),
            NamedRef("check_policy", refs["check_policy"]),
            NamedRef("check_report", refs["check_report"]),
            NamedRef("constraints", refs["constraints"]),
            NamedRef("publication_manifest", refs["publication_manifest"]),
        ),
        "draft": (NamedRef("artifact", refs["draft_artifact"]),),
        "final": (
            NamedRef("artifact", refs["final_artifact"]),
            NamedRef("artifact_report", refs["artifact_report"]),
            NamedRef("execution", refs["execution"]),
            NamedRef("render_options", refs["render_options"]),
        ),
    }
    for stage in ("prepare", "draft", "final"):
        running = current.start(
            stage, (), contract=f"{stage}.v1"  # type: ignore[arg-type]
        )
        _save_transition(workflows, current, running)
        succeeded = running.succeed(
            running.attempts[-1].operation_id,
            stage_outputs[stage],
        )
        _save_transition(workflows, running, succeeded)
        current = succeeded

    assert current.current_stage == "review"
    assert all(attempt.stage != "review" for attempt in current.attempts)
    return workflows, current, refs


def _store_round(
    storage: ProductionRepository,
    refs: dict[str, BlobRef],
    *,
    outcome: Literal["pass", "changes_requested", "block"],
    finding_id: str | None = None,
    previous_round: ReviewRound | None = None,
    resolutions: tuple[ReviewResolution, ...] = (),
) -> tuple[ReviewVerdict, ReviewRound]:
    findings = (
        ()
        if finding_id is None
        else (
            ReviewFinding(
                finding_id,
                f"Required correction for {finding_id}.",
                True,
            ),
        )
    )
    verdict = ReviewVerdict(
        artifact=refs["final_artifact"],
        artifact_report=refs["artifact_report"],
        publication_manifest=refs["publication_manifest"],
        outcome=outcome,
        check_report=refs["check_report"],
        constraints=refs["constraints"],
        scope=("audio", "visual", "constraints"),
        reviewer="video.reviewer",
        reviewed_at="2026-07-30T00:00:00Z",
        findings=findings,
    )
    verdict_ref = storage.objects.put_bytes(verdict.canonical_bytes())
    assert verdict_ref == verdict.ref
    review_round = ReviewRound(
        verdict_ref,
        None if previous_round is None else previous_round.ref,
        resolutions,
    )
    round_ref = storage.objects.put_bytes(review_round.canonical_bytes())
    assert round_ref == review_round.ref
    return verdict, review_round


def _passing_workflow(
    review_ready: WorkflowRun,
    verdict: ReviewVerdict,
) -> WorkflowRun:
    running = review_ready.start(
        "review",
        (
            NamedRef("artifact", verdict.artifact),
            NamedRef("artifact_report", verdict.artifact_report),
            NamedRef("publication_manifest", verdict.publication_manifest),
            NamedRef("check_report", verdict.check_report),
            NamedRef("constraints", verdict.constraints),
        ),
        contract=f"{ReviewVerdict.DOMAIN}.v{ReviewVerdict.VERSION}",
    )
    return running.succeed(
        running.attempts[-1].operation_id,
        (NamedRef("verdict", verdict.ref),),
    )


def test_review_latest_is_owned_and_cannot_be_written_generically(
    tmp_path: Path,
) -> None:
    storage = _repository(tmp_path)
    arbitrary = storage.objects.put_bytes(b"not an owner review round")

    with pytest.raises(ValueError, match="reserved record"):
        storage.update_records(
            {"review:latest": arbitrary},
            expected_revision=0,
        )


@pytest.mark.parametrize("outcome", ["changes_requested", "block"])
def test_non_pass_atomically_publishes_only_latest_round(
    tmp_path: Path,
    outcome: Literal["changes_requested", "block"],
) -> None:
    storage = _repository(tmp_path)
    workflows, review_ready, refs = _review_ready(storage)
    _, review_round = _store_round(
        storage,
        refs,
        outcome=outcome,
        finding_id=(
            "issue.transition" if outcome == "changes_requested" else None
        ),
    )
    before_head = storage.read_head()
    assert before_head is not None
    before_root = storage.read_root(before_head)

    committed = workflows.commit_review_round(
        review_ready,
        review_round.ref,
        expected_workflow_revision=review_ready.revision,
        expected_head_revision=before_head.revision,
        expected_latest_round=None,
    )

    after_head = storage.read_head()
    assert after_head is not None
    after_root = storage.read_root(after_head)
    assert committed == review_ready
    assert workflows.read_current() == review_ready
    assert after_head.revision == before_head.revision + 1
    assert after_root.parent_root_hash == before_head.root_hash
    assert dict(after_root.records) == {
        **dict(before_root.records),
        "review:latest": review_round.ref,
    }
    assert (
        after_root.records["workflow:current"]
        == before_root.records["workflow:current"]
    )


def test_same_context_changes_request_cannot_be_committed_as_pass(
    tmp_path: Path,
) -> None:
    storage = _repository(tmp_path)
    workflows, review_ready, refs = _review_ready(storage)
    _, first_round = _store_round(
        storage,
        refs,
        outcome="changes_requested",
        finding_id="issue.same-context",
    )
    workflows.commit_review_round(
        review_ready,
        first_round.ref,
        expected_workflow_revision=review_ready.revision,
        expected_head_revision=workflows.head_revision(),
        expected_latest_round=None,
    )
    passing_verdict, passing_round = _store_round(
        storage,
        refs,
        outcome="pass",
        previous_round=first_round,
        resolutions=(
            ReviewResolution("issue.same-context", "fixed"),
        ),
    )
    desired = _passing_workflow(review_ready, passing_verdict)
    before_head = storage.read_head()
    assert before_head is not None
    before_root = storage.read_root(before_head)

    with pytest.raises(
        CorruptObject,
        match="invalid review round transition",
    ):
        workflows.commit_review_round(
            desired,
            passing_round.ref,
            expected_workflow_revision=review_ready.revision,
            expected_head_revision=before_head.revision,
            expected_latest_round=first_round.ref,
        )

    assert storage.read_head() == before_head
    assert storage.read_root() == before_root
    assert workflows.read_latest_review_round_ref() == first_round.ref
    assert workflows.read_current() == review_ready


def test_pass_atomically_publishes_succeeded_workflow_and_latest_round(
    tmp_path: Path,
) -> None:
    storage = _repository(tmp_path)
    workflows, review_ready, refs = _review_ready(storage)
    verdict, review_round = _store_round(storage, refs, outcome="pass")
    succeeded = _passing_workflow(review_ready, verdict)
    assert succeeded.revision == review_ready.revision + 2
    assert succeeded.current_stage == "package"
    before_head = storage.read_head()
    assert before_head is not None
    before_root = storage.read_root(before_head)

    committed = workflows.commit_review_round(
        succeeded,
        review_round.ref,
        expected_workflow_revision=review_ready.revision,
        expected_head_revision=before_head.revision,
        expected_latest_round=None,
    )

    after_head = storage.read_head()
    assert after_head is not None
    after_root = storage.read_root(after_head)
    expected_workflow_ref = storage.objects.put_bytes(
        succeeded.canonical_bytes()
    )
    assert committed == succeeded
    assert workflows.read_current() == succeeded
    assert after_head.revision == before_head.revision + 1
    assert after_root.parent_root_hash == before_head.root_hash
    assert dict(after_root.records) == {
        **dict(before_root.records),
        "workflow:current": expected_workflow_ref,
        "review:latest": review_round.ref,
    }


@pytest.mark.parametrize(
    "stale_dimension",
    ["latest_round", "head_revision", "workflow_revision"],
)
def test_review_commit_rejects_each_stale_precondition_without_partial_publish(
    tmp_path: Path,
    stale_dimension: str,
) -> None:
    storage = _repository(tmp_path)
    workflows, review_ready, refs = _review_ready(storage)
    _, first_round = _store_round(
        storage,
        refs,
        outcome="changes_requested",
        finding_id="issue.first",
    )
    workflows.commit_review_round(
        review_ready,
        first_round.ref,
        expected_workflow_revision=review_ready.revision,
        expected_head_revision=workflows.head_revision(),
        expected_latest_round=None,
    )
    _, next_round = _store_round(
        storage,
        refs,
        outcome="block",
        previous_round=first_round,
        resolutions=(ReviewResolution("issue.first", "fixed"),),
    )
    before_head = storage.read_head()
    assert before_head is not None
    before_root = storage.read_root(before_head)
    expected_latest: BlobRef | None = first_round.ref
    expected_head = before_head.revision
    expected_workflow = review_ready.revision
    if stale_dimension == "latest_round":
        expected_latest = None
    elif stale_dimension == "head_revision":
        expected_head -= 1
    else:
        expected_workflow -= 1

    with pytest.raises(CasConflict):
        workflows.commit_review_round(
            review_ready,
            next_round.ref,
            expected_workflow_revision=expected_workflow,
            expected_head_revision=expected_head,
            expected_latest_round=expected_latest,
        )

    assert storage.read_head() == before_head
    assert storage.read_root() == before_root
    assert workflows.read_current() == review_ready


@pytest.mark.parametrize("outcome", ["pass", "changes_requested"])
def test_identical_lost_response_retry_is_idempotent(
    tmp_path: Path,
    outcome: Literal["pass", "changes_requested"],
) -> None:
    storage = _repository(tmp_path)
    workflows, review_ready, refs = _review_ready(storage)
    verdict, review_round = _store_round(
        storage,
        refs,
        outcome=outcome,
        finding_id=(
            "issue.retry" if outcome == "changes_requested" else None
        ),
    )
    desired = (
        _passing_workflow(review_ready, verdict)
        if outcome == "pass"
        else review_ready
    )
    expected_head = workflows.head_revision()

    first = workflows.commit_review_round(
        desired,
        review_round.ref,
        expected_workflow_revision=review_ready.revision,
        expected_head_revision=expected_head,
        expected_latest_round=None,
    )
    committed_head = storage.read_head()
    assert committed_head is not None
    retried = workflows.commit_review_round(
        desired,
        review_round.ref,
        expected_workflow_revision=review_ready.revision,
        expected_head_revision=expected_head,
        expected_latest_round=None,
    )

    assert first == desired
    assert retried == desired
    assert storage.read_head() == committed_head


def test_reopen_reads_the_exact_latest_review_round(tmp_path: Path) -> None:
    storage = _repository(tmp_path)
    workflows, review_ready, refs = _review_ready(storage)
    _, review_round = _store_round(
        storage,
        refs,
        outcome="changes_requested",
        finding_id="issue.reopen",
    )
    workflows.commit_review_round(
        review_ready,
        review_round.ref,
        expected_workflow_revision=review_ready.revision,
        expected_head_revision=workflows.head_revision(),
        expected_latest_round=None,
    )

    reopened_storage = _repository(tmp_path)
    reopened_workflows = WorkflowRepository(reopened_storage)
    latest_ref = reopened_storage.read_root().records["review:latest"]
    reopened_round = ReviewRound.from_canonical_bytes(
        reopened_workflows.read_blob(latest_ref)
    )

    assert latest_ref == review_round.ref
    assert reopened_round == review_round
    assert reopened_workflows.read_current() == review_ready


def test_non_pass_rejects_a_round_for_a_noncurrent_final_artifact(
    tmp_path: Path,
) -> None:
    storage = _repository(tmp_path)
    workflows, review_ready, refs = _review_ready(storage)
    wrong_refs = dict(refs)
    wrong_refs["final_artifact"] = storage.objects.put_bytes(
        b"existing but noncurrent final artifact"
    )
    _, review_round = _store_round(
        storage,
        wrong_refs,
        outcome="changes_requested",
        finding_id="issue.stale-artifact",
    )
    before_head = storage.read_head()
    assert before_head is not None
    before_root = storage.read_root(before_head)

    with pytest.raises(ValueError, match="exact current final artifact"):
        workflows.commit_review_round(
            review_ready,
            review_round.ref,
            expected_workflow_revision=review_ready.revision,
            expected_head_revision=before_head.revision,
            expected_latest_round=None,
        )

    assert storage.read_head() == before_head
    assert storage.read_root() == before_root
    assert workflows.read_latest_review_round_ref() is None
    assert workflows.read_current() == review_ready


def test_new_review_commit_is_rejected_after_workflow_left_review(
    tmp_path: Path,
) -> None:
    storage = _repository(tmp_path)
    workflows, review_ready, refs = _review_ready(storage)
    passing_verdict, _ = _store_round(storage, refs, outcome="pass")
    running_review = review_ready.start(
        "review",
        (
            NamedRef("artifact", passing_verdict.artifact),
            NamedRef("check_report", passing_verdict.check_report),
            NamedRef("constraints", passing_verdict.constraints),
        ),
        contract=f"{ReviewVerdict.DOMAIN}.v{ReviewVerdict.VERSION}",
    )
    _save_transition(workflows, review_ready, running_review)
    packaged_next = running_review.succeed(
        running_review.attempts[-1].operation_id,
        (NamedRef("verdict", passing_verdict.ref),),
    )
    _save_transition(workflows, running_review, packaged_next)
    assert packaged_next.current_stage == "package"
    assert workflows.read_latest_review_round_ref() is None

    _, new_round = _store_round(
        storage,
        refs,
        outcome="changes_requested",
        finding_id="issue.too-late",
    )
    before_head = storage.read_head()
    assert before_head is not None
    before_root = storage.read_root(before_head)

    with pytest.raises(ValueError, match="not waiting for review"):
        workflows.commit_review_round(
            packaged_next,
            new_round.ref,
            expected_workflow_revision=packaged_next.revision,
            expected_head_revision=before_head.revision,
            expected_latest_round=None,
        )

    assert storage.read_head() == before_head
    assert storage.read_root() == before_root
    assert workflows.read_latest_review_round_ref() is None
    assert workflows.read_current() == packaged_next


def test_exact_passing_round_can_be_reattached_after_invalidation(
    tmp_path: Path,
) -> None:
    storage = _repository(tmp_path)
    workflows, review_ready, refs = _review_ready(storage)
    verdict, review_round = _store_round(storage, refs, outcome="pass")
    first_passed = _passing_workflow(review_ready, verdict)
    workflows.commit_review_round(
        first_passed,
        review_round.ref,
        expected_workflow_revision=review_ready.revision,
        expected_head_revision=workflows.head_revision(),
        expected_latest_round=None,
    )

    changed_source = storage.objects.put_bytes(b"changed upstream source")
    invalidated = first_passed.start(
        "prepare",
        (NamedRef("source", changed_source),),
        contract="prepare.v2",
    )
    _save_transition(workflows, first_passed, invalidated)
    prepared_again = invalidated.succeed(
        invalidated.attempts[-1].operation_id,
        (
            NamedRef("timeline", refs["timeline"]),
            NamedRef("check_policy", refs["check_policy"]),
            NamedRef("check_report", refs["check_report"]),
                NamedRef("constraints", refs["constraints"]),
                NamedRef(
                    "publication_manifest", refs["publication_manifest"]
                ),
        ),
    )
    _save_transition(workflows, invalidated, prepared_again)
    drafting_again = prepared_again.start(
        "draft",
        (),
        contract="draft.v2",
    )
    _save_transition(workflows, prepared_again, drafting_again)
    drafted_again = drafting_again.succeed(
        drafting_again.attempts[-1].operation_id,
        (NamedRef("artifact", refs["draft_artifact"]),),
    )
    _save_transition(workflows, drafting_again, drafted_again)
    rendering_again = drafted_again.start(
        "final",
        (),
        contract="final.v2",
    )
    _save_transition(workflows, drafted_again, rendering_again)
    review_ready_again = rendering_again.succeed(
        rendering_again.attempts[-1].operation_id,
            (
                NamedRef("artifact", refs["final_artifact"]),
                NamedRef("artifact_report", refs["artifact_report"]),
                NamedRef("execution", refs["execution"]),
            NamedRef("render_options", refs["render_options"]),
        ),
    )
    _save_transition(workflows, rendering_again, review_ready_again)
    assert review_ready_again.current_stage == "review"
    assert workflows.read_latest_review_round_ref() == review_round.ref

    desired = _passing_workflow(review_ready_again, verdict)
    assert desired.revision == review_ready_again.revision + 2
    before_head = storage.read_head()
    assert before_head is not None
    before_root = storage.read_root(before_head)

    reattached = workflows.commit_review_round(
        desired,
        review_round.ref,
        expected_workflow_revision=review_ready_again.revision,
        expected_head_revision=before_head.revision,
        expected_latest_round=review_round.ref,
    )

    after_head = storage.read_head()
    assert after_head is not None
    after_root = storage.read_root(after_head)
    expected_workflow_ref = storage.objects.put_bytes(
        desired.canonical_bytes()
    )
    assert reattached == desired
    assert workflows.read_current() == desired
    assert after_head.revision == before_head.revision + 1
    assert after_root.parent_root_hash == before_head.root_hash
    assert after_root.records["review:latest"] == review_round.ref
    assert dict(after_root.records) == {
        **dict(before_root.records),
        "workflow:current": expected_workflow_ref,
    }

    retried = workflows.commit_review_round(
        desired,
        review_round.ref,
        expected_workflow_revision=review_ready_again.revision,
        expected_head_revision=before_head.revision,
        expected_latest_round=review_round.ref,
    )
    assert retried == desired
    assert storage.read_head() == after_head
    assert workflows.read_latest_review_round_ref() == review_round.ref
