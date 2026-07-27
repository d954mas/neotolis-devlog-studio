"""Persistence for the single current workflow snapshot."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dlstudio.foundation.api import BlobRef, CasConflict, CorruptObject
from dlstudio.persistence.api import HeadRef, ProductionRepository
from dlstudio.workflow.api import WorkflowRun


@dataclass(frozen=True, slots=True)
class SavedWorkflow:
    workflow: BlobRef
    head: HeadRef


class WorkflowRepository:
    RECORD_KEY = "workflow:current"

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

    def save(
        self,
        workflow: WorkflowRun,
        *,
        expected_workflow_revision: int,
        expected_head_revision: int,
    ) -> SavedWorkflow:
        return self._save(
            workflow,
            expected_workflow_revision=expected_workflow_revision,
            expected_head_revision=expected_head_revision,
            allow_pending_delivery=False,
        )

    def complete_delivery(
        self,
        workflow: WorkflowRun,
        *,
        expected_workflow_revision: int,
        expected_head_revision: int,
    ) -> SavedWorkflow:
        if not workflow.completed:
            raise ValueError("delivery workflow must be complete")
        if self.repository.read_pending_delivery() is None:
            raise ValueError("delivery completion requires its journal")
        return self._save(
            workflow,
            expected_workflow_revision=expected_workflow_revision,
            expected_head_revision=expected_head_revision,
            allow_pending_delivery=True,
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
    ) -> SavedWorkflow:
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

        ref = self.repository.objects.put_bytes(workflow.canonical_bytes())
        head = self.repository._update_records(
            {self.RECORD_KEY: ref},
            expected_revision=expected_head_revision,
            allowed_reserved_keys=frozenset({self.RECORD_KEY}),
            allow_pending_delivery=allow_pending_delivery,
        )
        return SavedWorkflow(ref, head)
