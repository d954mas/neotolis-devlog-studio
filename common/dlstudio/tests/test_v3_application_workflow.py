from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from dlstudio.application.api import (
    advance,
    get_status,
    start_workflow,
    submit_review,
)
from dlstudio.foundation.api import BlobRef
from dlstudio.persistence import ProductionRepository, WorkflowRepository
from dlstudio.review.api import ReviewVerdict
from dlstudio.workflow.api import NamedRef


def _workflows(tmp_path: Path) -> WorkflowRepository:
    repository = ProductionRepository(
        object_root=tmp_path / "objects",
        state_root=tmp_path / "state",
        staging_root=tmp_path / "staging",
        lock_root=tmp_path / "locks",
        production_id="fixture.reel",
    )
    return WorkflowRepository(repository)


def _put(workflows: WorkflowRepository, value: bytes) -> BlobRef:
    return workflows.put_blob(value)


def test_status_is_a_direct_workflow_projection(tmp_path: Path) -> None:
    workflows = _workflows(tmp_path)
    created = start_workflow(workflows, run_id="run.main", kind="reel")
    assert get_status(workflows) == created
    assert start_workflow(workflows, run_id="run.main", kind="reel") == created


@pytest.mark.performance_smoke
def test_status_no_compile_scan_subprocess(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workflows = _workflows(tmp_path)
    expected = start_workflow(workflows, run_id="run.main", kind="reel")

    def forbidden(*_args: object, **_kwargs: object) -> None:
        raise AssertionError("status performed forbidden work")

    monkeypatch.setattr(Path, "rglob", forbidden)
    monkeypatch.setattr(subprocess, "run", forbidden)
    monkeypatch.setattr(
        "dlstudio.application.authoring.compile_production", forbidden
    )
    assert get_status(workflows) == expected


def test_advance_hides_attempt_bookkeeping_and_resumes_running_stage(
    tmp_path: Path,
) -> None:
    workflows = _workflows(tmp_path)
    start_workflow(workflows, run_id="run.main", kind="reel")
    calls: list[str] = []

    def run_stage(_stage: str, operation_id: str) -> tuple[NamedRef, ...]:
        calls.append(operation_id)
        return (NamedRef("manifest", _put(workflows, b"manifest")),)

    completed = advance(
        workflows,
        inputs=(),
        contract="prepare.v1",
        run_stage=run_stage,  # type: ignore[arg-type]
    )
    assert completed.current_stage == "draft"
    assert len(calls) == 1


def test_advance_persists_failure_and_retry_uses_same_operation_id(
    tmp_path: Path,
) -> None:
    workflows = _workflows(tmp_path)
    start_workflow(workflows, run_id="run.main", kind="reel")
    calls: list[str] = []

    def fail(_stage: str, operation_id: str) -> tuple[NamedRef, ...]:
        calls.append(operation_id)
        raise RuntimeError("provider stopped")

    with pytest.raises(RuntimeError, match="provider stopped"):
        advance(
            workflows,
            inputs=(),
            contract="prepare.v1",
            run_stage=fail,  # type: ignore[arg-type]
        )
    assert get_status(workflows).attempts[-1].state == "failed"

    advance(
        workflows,
        inputs=(),
        contract="prepare.v1",
        run_stage=lambda _stage, operation_id: (
            calls.append(operation_id),
            (NamedRef("manifest", _put(workflows, b"manifest")),),
        )[1],
    )
    assert calls[0] == calls[1]


def test_review_must_name_exact_final_outputs(tmp_path: Path) -> None:
    workflows = _workflows(tmp_path)
    start_workflow(workflows, run_id="run.main", kind="reel")
    artifact = _put(workflows, b"final")
    report = _put(workflows, b"report")
    constraints = _put(workflows, b"constraints")

    advance(
        workflows,
        inputs=(),
        contract="prepare.v1",
        run_stage=lambda *_: (
            NamedRef("timeline", _put(workflows, b"timeline")),
            NamedRef("check_policy", _put(workflows, b"policy")),
            NamedRef("check_report", report),
            NamedRef("constraints", constraints),
        ),
    )
    advance(
        workflows,
        inputs=(),
        contract="draft.v1",
        run_stage=lambda *_: (NamedRef("artifact", _put(workflows, b"draft")),),
    )
    advance(
        workflows,
        inputs=(),
        contract="final.v1",
        run_stage=lambda *_: (
            NamedRef("artifact", artifact),
            NamedRef("execution", _put(workflows, b"execution")),
            NamedRef("render_options", _put(workflows, b"options")),
        ),
    )
    verdict = ReviewVerdict(
        artifact=artifact,
        outcome="pass",
        check_report=report,
        constraints=constraints,
        scope=("audio", "visual", "constraints"),
        reviewer="video.reviewer",
        reviewed_at="2026-07-27T00:00:00Z",
    )
    reviewed = submit_review(workflows, verdict)
    assert reviewed.current_stage == "package"
    assert reviewed.attempts[-1].outputs == (
        NamedRef("verdict", verdict.ref),
    )

    with pytest.raises(ValueError, match="waiting for review"):
        submit_review(workflows, verdict)


def test_generic_advance_cannot_publish_an_arbitrary_candidate(
    tmp_path: Path,
) -> None:
    workflows = _workflows(tmp_path)
    run = start_workflow(workflows, run_id="run.main", kind="reel")
    for stage in ("prepare", "draft", "final", "review"):
        running = run.start(stage, (), contract=f"{stage}.v1")  # type: ignore[arg-type]
        workflows.save(
            running,
            expected_workflow_revision=run.revision,
            expected_head_revision=workflows.head_revision(),
        )
        outputs = (
            (NamedRef("verdict", _put(workflows, b"verdict")),)
            if stage == "review"
            else (NamedRef("output", _put(workflows, stage.encode())),)
        )
        run = running.succeed(running.attempts[-1].operation_id, outputs)
        workflows.save(
            run,
            expected_workflow_revision=running.revision,
            expected_head_revision=workflows.head_revision(),
        )
    with pytest.raises(ValueError, match="package_release"):
        advance(
            workflows,
            inputs=(),
            contract="package.v1",
            run_stage=lambda *_: (
                NamedRef("candidate", _put(workflows, b"arbitrary")),
            ),
        )
