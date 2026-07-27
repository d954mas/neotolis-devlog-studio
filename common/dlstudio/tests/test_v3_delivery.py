from __future__ import annotations

from pathlib import Path

import pytest

from dlstudio.application.delivery import deliver_local, recover_local_delivery
from dlstudio.foundation.api import BlobRef, CasConflict
from dlstudio.persistence import (
    ProductionRepository,
    WorkflowRepository,
)
from dlstudio.release.api import PackageFile, ReleaseCandidate
from dlstudio.workflow.api import NamedRef, WorkflowRun


def _repository(tmp_path: Path) -> ProductionRepository:
    return ProductionRepository(
        object_root=tmp_path / "objects",
        state_root=tmp_path / "state",
        staging_root=tmp_path / "staging",
        lock_root=tmp_path / "locks",
        production_id="fixture.reel",
    )


def _put(repository: ProductionRepository, value: bytes) -> BlobRef:
    return repository.objects.put_bytes(value)


def _candidate(repository: ProductionRepository) -> tuple[ReleaseCandidate, BlobRef]:
    final = _put(repository, b"final video")
    metadata = _put(repository, b"title: Exact release")
    candidate = ReleaseCandidate(
        production_id=repository.production_id,
        timeline=_put(repository, b"timeline"),
        execution=_put(repository, b"execution"),
        final_output=final,
        check_report=_put(repository, b"checks"),
        review_verdict=_put(repository, b"review"),
        constraints=_put(repository, b"constraints"),
        asset_revisions=(_put(repository, b"asset revision"),),
        license_bundle=_put(repository, b"licenses"),
        package=(
            PackageFile("video.mp4", final),
            PackageFile("youtube/metadata.md", metadata),
        ),
    )
    ref = _put(repository, candidate.canonical_bytes())
    assert ref == candidate.ref
    return candidate, ref


def _save_next(
    repository: ProductionRepository,
    workflows: WorkflowRepository,
    previous: WorkflowRun | None,
    current: WorkflowRun,
) -> WorkflowRun:
    head = repository.read_head()
    workflows.save(
        current,
        expected_workflow_revision=(
            -1 if previous is None else previous.revision
        ),
        expected_head_revision=0 if head is None else head.revision,
    )
    return current


def _ready_workflow(
    repository: ProductionRepository,
    workflows: WorkflowRepository,
    candidate: BlobRef,
) -> WorkflowRun:
    run = _save_next(
        repository,
        workflows,
        None,
        WorkflowRun("run.main", repository.production_id, "reel"),
    )
    for stage in ("prepare", "draft", "review", "final", "package"):
        started = run.start(stage, (), contract=f"{stage}.v1")  # type: ignore[arg-type]
        _save_next(repository, workflows, run, started)
        outputs = (
            (NamedRef("candidate", candidate),)
            if stage == "package"
            else (NamedRef("output", _put(repository, stage.encode())),)
        )
        succeeded = started.succeed(
            started.attempts[-1].operation_id,
            outputs,
        )
        _save_next(repository, workflows, started, succeeded)
        run = succeeded
    allowed = run.allow_delivery()
    return _save_next(repository, workflows, run, allowed)


def test_local_delivery_copies_only_the_frozen_package_and_retries(
    tmp_path: Path,
) -> None:
    repository = _repository(tmp_path)
    workflows = WorkflowRepository(repository)
    candidate, candidate_ref = _candidate(repository)
    _ready_workflow(repository, workflows, candidate_ref)
    destination = tmp_path / "published"

    completed, receipt = deliver_local(
        workflows,
        destination,
        destination_id="local.archive",
        delivered_at="2026-07-27T00:00:00Z",
    )

    assert completed.completed
    assert receipt.candidate_id == candidate.candidate_id
    assert (destination / "video.mp4").read_bytes() == b"final video"
    assert (
        destination / "youtube" / "metadata.md"
    ).read_bytes() == b"title: Exact release"
    assert repository.read_pending_delivery() is None

    retried, same_receipt = deliver_local(
        workflows,
        destination,
        destination_id="local.archive",
    )
    assert retried == completed
    assert same_receipt == receipt


def test_differing_destination_is_never_overwritten(tmp_path: Path) -> None:
    repository = _repository(tmp_path)
    workflows = WorkflowRepository(repository)
    _, candidate_ref = _candidate(repository)
    ready = _ready_workflow(repository, workflows, candidate_ref)
    destination = tmp_path / "published"
    destination.mkdir()
    existing = destination / "keep.txt"
    existing.write_bytes(b"user data")

    with pytest.raises(FileExistsError, match="differs"):
        deliver_local(
            workflows,
            destination,
            destination_id="local.archive",
        )

    assert existing.read_bytes() == b"user data"
    assert repository.read_pending_delivery() is None
    assert workflows.read_current() == ready


def test_crash_after_promote_fails_closed_and_recovers_once(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repository = _repository(tmp_path)
    workflows = WorkflowRepository(repository)
    _, candidate_ref = _candidate(repository)
    _ready_workflow(repository, workflows, candidate_ref)
    destination = tmp_path / "published"
    original_complete = workflows.complete_delivery

    def crash(*_args: object, **_kwargs: object) -> None:
        raise RuntimeError("simulated process exit after promote")

    monkeypatch.setattr(workflows, "complete_delivery", crash)
    with pytest.raises(RuntimeError, match="simulated"):
        deliver_local(
            workflows,
            destination,
            destination_id="local.archive",
            delivered_at="2026-07-27T00:00:00Z",
        )

    assert (destination / "video.mp4").read_bytes() == b"final video"
    assert repository.read_pending_delivery() is not None
    unrelated = _put(repository, b"unrelated")
    with pytest.raises(CasConflict, match="pending delivery"):
        repository.update_records(
            {"unrelated": unrelated},
            expected_revision=repository.read_head().revision,  # type: ignore[union-attr]
        )

    monkeypatch.setattr(workflows, "complete_delivery", original_complete)
    completed, receipt = recover_local_delivery(workflows)
    assert completed.completed
    assert completed.delivery_receipt == receipt.ref
    assert repository.read_pending_delivery() is None

    retried, same_receipt = deliver_local(
        workflows,
        destination,
        destination_id="local.archive",
    )
    assert retried == completed
    assert same_receipt == receipt
