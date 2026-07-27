"""Persistence for the single current workflow snapshot."""

from __future__ import annotations

from dataclasses import dataclass

from dlstudio.assets.api import BlobRef
from dlstudio.foundation.api import CasConflict, CorruptObject
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
        )
        return SavedWorkflow(ref, head)
