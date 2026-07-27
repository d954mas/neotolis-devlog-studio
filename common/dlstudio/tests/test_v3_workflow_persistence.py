from __future__ import annotations

from pathlib import Path

import pytest

from dlstudio.foundation.api import BlobRef, CasConflict
from dlstudio.persistence import ProductionRepository, WorkflowRepository
from dlstudio.workflow.api import NamedRef, WorkflowRun


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

    assert saved.revision == 1
    assert workflows.read_current() == run
    assert storage.read_root().records == {
        "workflow:current": storage.objects.put_bytes(run.canonical_bytes())
    }


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


def test_changed_upstream_input_persists_and_clears_eligibility(
    tmp_path: Path,
) -> None:
    storage = _repository(tmp_path)
    workflows = WorkflowRepository(storage)
    run = WorkflowRun("run.main", "fixture.reel", "reel")
    workflows.save(
        run,
        expected_workflow_revision=-1,
        expected_head_revision=0,
    )
    for stage in ("prepare", "draft", "final", "review"):
        running = run.start(stage, (), contract=f"{stage}.v1")  # type: ignore[arg-type]
        head = storage.read_head()
        assert head is not None
        workflows.save(
            running,
            expected_workflow_revision=run.revision,
            expected_head_revision=head.revision,
        )
        completed = running.succeed(
            running.attempts[-1].operation_id,
            (NamedRef("output", storage.objects.put_bytes(stage.encode())),),
        )
        head = storage.read_head()
        assert head is not None
        workflows.save(
            completed,
            expected_workflow_revision=running.revision,
            expected_head_revision=head.revision,
        )
        run = completed
    running = run.start("package", (), contract="package.v1")
    head = storage.read_head()
    assert head is not None
    workflows.save(
        running,
        expected_workflow_revision=run.revision,
        expected_head_revision=head.revision,
    )
    candidate = storage.objects.put_bytes(b"frozen candidate")
    head = storage.read_head()
    assert head is not None
    ready = workflows._complete_package(
        running,
        running.attempts[-1].operation_id,
        candidate,
        expected_workflow_revision=running.revision,
        expected_head_revision=head.revision,
    )

    changed = ready.start(
        "draft",
        (NamedRef("script", BlobRef("f" * 64, 1)),),
        contract="draft.v2",
    )
    head = storage.read_head()
    assert head is not None
    workflows.save(
        changed,
        expected_workflow_revision=ready.revision,
        expected_head_revision=head.revision,
    )

    assert workflows.read_current() == changed
    assert changed.eligible_candidate is None
