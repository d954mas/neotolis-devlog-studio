"""Persistence for the single current workflow snapshot."""

from __future__ import annotations

from pathlib import Path

from dlstudio.foundation.api import BlobRef, CasConflict, CorruptObject
from dlstudio.persistence.api import HeadRef, ProductionRepository
from dlstudio.review.api import (
    ReviewRound,
    ReviewVerdict,
    validate_review_round_transition,
)
from dlstudio.workflow.api import NamedRef, WorkflowRun


def _completed_outputs(
    workflow: WorkflowRun,
    stage: str,
) -> dict[str, BlobRef]:
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


class WorkflowRepository:
    RECORD_KEY = "workflow:current"
    REVIEW_LATEST_KEY = "review:latest"

    def __init__(self, repository: ProductionRepository) -> None:
        self.repository = repository

    @property
    def production_id(self) -> str:
        return self.repository.production_id

    def read_current(self) -> WorkflowRun | None:
        root = self.repository.read_root()
        ref = root.records.get(self.RECORD_KEY)
        if ref is None:
            return None
        try:
            return WorkflowRun.from_canonical_bytes(
                self.repository.objects.read(ref)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptObject("invalid current workflow") from exc

    def head_revision(self) -> int:
        head = self.repository.read_head()
        return 0 if head is None else head.revision

    def read_latest_review_round_ref(self) -> BlobRef | None:
        return self.repository.read_root().records.get(
            self.REVIEW_LATEST_KEY
        )

    def save(
        self,
        workflow: WorkflowRun,
        *,
        expected_workflow_revision: int,
        expected_head_revision: int,
    ) -> HeadRef:
        return self._save(
            workflow,
            expected_workflow_revision=expected_workflow_revision,
            expected_head_revision=expected_head_revision,
            allow_pending_delivery=False,
            allow_package=False,
        )

    def _complete_package(
        self,
        workflow: WorkflowRun,
        operation_id: str,
        candidate: BlobRef,
        *,
        expected_workflow_revision: int,
        expected_head_revision: int,
    ) -> WorkflowRun:
        self.repository.objects.verify(candidate)
        completed = workflow._succeed_package(operation_id, candidate)
        self._save(
            completed,
            expected_workflow_revision=expected_workflow_revision,
            expected_head_revision=expected_head_revision,
            allow_pending_delivery=False,
            allow_package=True,
        )
        return completed

    def commit_review_round(
        self,
        workflow: WorkflowRun,
        round_ref: BlobRef,
        *,
        expected_workflow_revision: int,
        expected_head_revision: int,
        expected_latest_round: BlobRef | None,
    ) -> WorkflowRun:
        """Publish one exact review round and its workflow effect in one CAS."""

        try:
            review_round = ReviewRound.from_canonical_bytes(
                self.repository.objects.read(round_ref)
            )
            verdict = ReviewVerdict.from_canonical_bytes(
                self.repository.objects.read(review_round.verdict)
            )
        except (KeyError, TypeError, ValueError) as exc:
            raise CorruptObject("invalid review round closure") from exc
        if review_round.ref != round_ref:
            raise CorruptObject("review round identity changed")
        reusing_existing_pass = round_ref == expected_latest_round
        if (
            not reusing_existing_pass
            and review_round.previous_round != expected_latest_round
        ):
            raise CasConflict("review round does not extend expected latest")
        if reusing_existing_pass:
            if verdict.outcome != "pass":
                raise ValueError("only an exact passing review can be reused")
        else:
            try:
                previous_round = (
                    None
                    if expected_latest_round is None
                    else ReviewRound.from_canonical_bytes(
                        self.repository.objects.read(expected_latest_round)
                    )
                )
                previous_verdict = (
                    None
                    if previous_round is None
                    else ReviewVerdict.from_canonical_bytes(
                        self.repository.objects.read(previous_round.verdict)
                    )
                )
                validate_review_round_transition(
                    review_round,
                    verdict,
                    previous_round=previous_round,
                    previous_verdict=previous_verdict,
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise CorruptObject("invalid review round transition") from exc

        current = self.read_current()
        if current is None:
            raise CasConflict("review commit requires a canonical workflow")
        actual_latest = self.read_latest_review_round_ref()

        if actual_latest == round_ref:
            if current == workflow:
                return current
            if not reusing_existing_pass:
                raise CasConflict(
                    "review round already committed with another workflow"
                )

        if current.current_stage != "review":
            raise ValueError("workflow is not waiting for review")
        prepared = _completed_outputs(current, "prepare")
        rendered = _completed_outputs(current, "final")
        if (
            verdict.artifact != rendered.get("artifact")
            or verdict.check_report != prepared.get("check_report")
            or verdict.constraints != prepared.get("constraints")
        ):
            raise ValueError(
                "review verdict does not name the exact current final artifact "
                "and context"
            )

        if current.revision != expected_workflow_revision:
            raise CasConflict(
                "expected workflow revision "
                f"{expected_workflow_revision}, got {current.revision}"
            )
        actual_head_revision = self.head_revision()
        if actual_head_revision != expected_head_revision:
            raise CasConflict(
                "expected head revision "
                f"{expected_head_revision}, got {actual_head_revision}"
            )
        if actual_latest != expected_latest_round:
            raise CasConflict("latest review round changed")

        records: dict[str, BlobRef] = (
            {}
            if reusing_existing_pass
            else {self.REVIEW_LATEST_KEY: round_ref}
        )
        allowed_reserved = (
            set()
            if reusing_existing_pass
            else {self.REVIEW_LATEST_KEY}
        )
        if verdict.outcome == "pass":
            running = current.start(
                "review",
                (
                    NamedRef("artifact", verdict.artifact),
                    NamedRef("check_report", verdict.check_report),
                    NamedRef("constraints", verdict.constraints),
                ),
                contract=(
                    f"{ReviewVerdict.DOMAIN}.v{ReviewVerdict.VERSION}"
                ),
            )
            expected = running.succeed(
                running.attempts[-1].operation_id,
                (NamedRef("verdict", verdict.ref),),
            )
            if workflow != expected:
                raise ValueError(
                    "passing review workflow transition is invalid"
                )
            records[self.RECORD_KEY] = self.repository.objects.put_bytes(
                workflow.canonical_bytes()
            )
            allowed_reserved.add(self.RECORD_KEY)
        elif workflow != current:
            raise ValueError("non-pass review cannot change the workflow")

        self.repository._update_records(
            records,
            expected_revision=expected_head_revision,
            allowed_reserved_keys=frozenset(allowed_reserved),
        )
        return workflow

    def complete_delivery(
        self,
        workflow: WorkflowRun,
        *,
        expected_workflow_revision: int,
        expected_head_revision: int,
    ) -> HeadRef:
        if not workflow.completed:
            raise ValueError("delivery workflow must be complete")
        if self.repository.read_pending_delivery() is None:
            raise ValueError("delivery completion requires its journal")
        return self._save(
            workflow,
            expected_workflow_revision=expected_workflow_revision,
            expected_head_revision=expected_head_revision,
            allow_pending_delivery=True,
            allow_package=False,
        )

    def snapshot(self) -> tuple[WorkflowRun, int]:
        workflow = self.read_current()
        head = self.repository.read_head()
        if workflow is None or head is None:
            raise ValueError("delivery requires a canonical workflow")
        return workflow, head.revision

    def read_blob(self, ref: BlobRef) -> bytes:
        return self.repository.objects.read(ref)

    def put_blob(self, data: bytes) -> BlobRef:
        return self.repository.objects.put_bytes(data)

    def verify_blob(self, ref: BlobRef) -> None:
        self.repository.objects.verify(ref)

    def blob_path(self, ref: BlobRef) -> Path:
        self.repository.objects.verify(ref)
        return self.repository.objects.path_for(ref)

    def read_pending(self) -> bytes | None:
        return self.repository.read_pending_delivery()

    def begin_pending(self, journal: bytes, *, expected_head: int) -> None:
        self.repository._begin_delivery(
            journal, expected_revision=expected_head
        )

    def save_completed(
        self,
        workflow: WorkflowRun,
        *,
        expected_workflow: int,
        expected_head: int,
    ) -> None:
        self.complete_delivery(
            workflow,
            expected_workflow_revision=expected_workflow,
            expected_head_revision=expected_head,
        )

    def clear_pending(self, journal: bytes) -> None:
        self.repository._finish_delivery(journal)

    def _save(
        self,
        workflow: WorkflowRun,
        *,
        expected_workflow_revision: int,
        expected_head_revision: int,
        allow_pending_delivery: bool,
        allow_package: bool,
    ) -> HeadRef:
        if workflow.production_id != self.repository.production_id:
            raise ValueError("workflow belongs to another production")
        current = self.read_current()
        actual_revision = -1 if current is None else current.revision
        if actual_revision != expected_workflow_revision:
            raise CasConflict(
                "expected workflow revision "
                f"{expected_workflow_revision}, got {actual_revision}"
            )
        if workflow.revision != expected_workflow_revision + 1:
            raise ValueError("workflow revision must advance exactly once")
        if current is not None and workflow.run_id != current.run_id:
            raise ValueError("cannot replace the current workflow run")
        previous_candidate = (
            None if current is None else current.eligible_candidate
        )
        if (
            workflow.eligible_candidate is not None
            and workflow.eligible_candidate != previous_candidate
            and not allow_package
        ):
            raise ValueError(
                "delivery eligibility is written only by the package use case"
            )

        ref = self.repository.objects.put_bytes(workflow.canonical_bytes())
        head = self.repository._update_records(
            {self.RECORD_KEY: ref},
            expected_revision=expected_head_revision,
            allowed_reserved_keys=frozenset({self.RECORD_KEY}),
            allow_pending_delivery=allow_pending_delivery,
        )
        return head
