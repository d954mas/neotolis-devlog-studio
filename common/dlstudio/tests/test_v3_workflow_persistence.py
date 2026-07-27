from __future__ import annotations

from pathlib import Path

import pytest

from dlstudio.foundation.api import CasConflict
from dlstudio.persistence import ProductionRepository, WorkflowRepository
from dlstudio.workflow.api import WorkflowRun


def _repository(tmp_path: Path) -> ProductionRepository:
    return ProductionRepository(
        object_root=tmp_path / "objects",
        state_root=tmp_path / "state",
        staging_root=tmp_path / "staging",
        lock_root=tmp_path / "locks",
        production_id="fixture.reel",
    )


def test_workflow_repository_keeps_one_current_snapshot(tmp_path: Path) -> None:
    storage = _repository(tmp_path)
    workflows = WorkflowRepository(storage)
    run = WorkflowRun("run.main", "fixture.reel", "reel")
    saved = workflows.save(
        run,
        expected_workflow_revision=-1,
        expected_head_revision=0,
    )

    assert saved.head.revision == 1
    assert workflows.read_current() == run
    assert storage.read_root().records == {"workflow:current": saved.workflow}


def test_workflow_repository_rejects_stale_writer(tmp_path: Path) -> None:
    storage = _repository(tmp_path)
    workflows = WorkflowRepository(storage)
    run = WorkflowRun("run.main", "fixture.reel", "reel")
    workflows.save(
        run,
        expected_workflow_revision=-1,
        expected_head_revision=0,
    )
    started = run.start("prepare", (), contract="prepare.v1")
    workflows.save(
        started,
        expected_workflow_revision=0,
        expected_head_revision=1,
    )

    with pytest.raises(CasConflict, match="workflow revision"):
        workflows.save(
            started,
            expected_workflow_revision=0,
            expected_head_revision=1,
        )
