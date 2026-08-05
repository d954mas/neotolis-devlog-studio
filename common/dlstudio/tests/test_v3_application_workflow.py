from __future__ import annotations

import subprocess
from pathlib import Path

import pytest
import dlstudio.application.api as application_api

from dlstudio.application.api import (
    get_status,
    start_workflow,
    submit_review,
)
from dlstudio.application.workflow import _advance
from dlstudio.foundation.api import BlobRef
from dlstudio.persistence import ProductionRepository, WorkflowRepository
from dlstudio.rendering.api import ArtifactReport
from dlstudio.release.api import PublicationManifest, PublicationManifestFile
from dlstudio.review.api import ReviewRound, ReviewVerdict
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


def _artifact_report(
    workflows: WorkflowRepository,
    artifact: BlobRef,
) -> BlobRef:
    report = ArtifactReport(
        artifact=artifact,
        width=1080,
        height=1920,
        fps_num=30,
        fps_den=1,
        duration_ns=1_000_000_000,
        audio_codec=None,
        audio_sample_rate=None,
        audio_channels=None,
        integrated_lufs_milli=None,
        true_peak_db_milli=None,
        active_audio_ratio_milli=None,
    )
    return _put(workflows, report.canonical_bytes())


def _publication(
    workflows: WorkflowRepository,
    roles: tuple[str, ...] = ("cover", "metadata"),
) -> BlobRef:
    cover_blob = _put(workflows, b"cover")
    cover_revision = _put(workflows, b"cover revision")
    metadata_blob = _put(workflows, b"metadata")
    metadata_revision = _put(workflows, b"metadata revision")
    return _put(
        workflows,
        PublicationManifest(
            "fixture.reel",
            tuple(item for item in (
                PublicationManifestFile(
                    "cover",
                    "cover.png",
                    "publish.cover.main",
                    cover_revision,
                    cover_blob,
                ),
                PublicationManifestFile(
                    "metadata",
                    "metadata.md",
                    "publish.metadata.main",
                    metadata_revision,
                    metadata_blob,
                ),
            ) if item.role in roles),
        ).canonical_bytes(),
    )


def test_reel_review_rejects_missing_cover_before_verdict(
    tmp_path: Path,
) -> None:
    workflows = _workflows(tmp_path)
    start_workflow(workflows, run_id="run.main", kind="reel")
    artifact = _put(workflows, b"final")
    artifact_report = _artifact_report(workflows, artifact)
    publication = _publication(workflows, ("metadata",))
    check_report = _put(workflows, b"checks")
    constraints = _put(workflows, b"constraints")
    _advance(
        workflows,
        inputs=(),
        contract="prepare.v1",
        run_stage=lambda *_: (
            NamedRef("timeline", _put(workflows, b"timeline")),
            NamedRef("check_policy", _put(workflows, b"policy")),
            NamedRef("check_report", check_report),
            NamedRef("constraints", constraints),
            NamedRef("publication_manifest", publication),
        ),
    )
    _advance(
        workflows,
        inputs=(),
        contract="draft.v1",
        run_stage=lambda *_: (NamedRef("artifact", _put(workflows, b"draft")),),
    )
    _advance(
        workflows,
        inputs=(),
        contract="final.v1",
        run_stage=lambda *_: (
            NamedRef("artifact", artifact),
            NamedRef("artifact_report", artifact_report),
            NamedRef("execution", _put(workflows, b"execution")),
            NamedRef("render_options", _put(workflows, b"options")),
        ),
    )

    with pytest.raises(ValueError, match="requires cover and metadata"):
        submit_review(
            workflows,
            ReviewVerdict(
                artifact=artifact,
                artifact_report=artifact_report,
                publication_manifest=publication,
                outcome="pass",
                check_report=check_report,
                constraints=constraints,
                scope=("audio", "constraints", "publication", "visual"),
                reviewer="video.reviewer",
                reviewed_at="2026-07-30T00:00:00Z",
            ),
        )


def test_status_is_a_direct_workflow_projection(tmp_path: Path) -> None:
    workflows = _workflows(tmp_path)
    created = start_workflow(workflows, run_id="run.main", kind="reel")
    assert get_status(workflows) == created
    assert start_workflow(workflows, run_id="run.main", kind="reel") == created


def test_public_api_has_no_generic_stage_or_package_bypass() -> None:
    assert not hasattr(application_api, "advance")
    assert not hasattr(application_api, "package_release")


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

    completed = _advance(
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
        _advance(
            workflows,
            inputs=(),
            contract="prepare.v1",
            run_stage=fail,  # type: ignore[arg-type]
        )
    assert get_status(workflows).attempts[-1].state == "failed"

    _advance(
        workflows,
        inputs=(),
        contract="prepare.v1",
        run_stage=lambda _stage, operation_id: (
            calls.append(operation_id),
            (NamedRef("manifest", _put(workflows, b"manifest")),),
        )[1],
    )
    assert calls[0] == calls[1]


def test_review_must_name_exact_final_outputs_and_resume_running_attempt(
    tmp_path: Path,
) -> None:
    workflows = _workflows(tmp_path)
    start_workflow(workflows, run_id="run.main", kind="reel")
    artifact = _put(workflows, b"final")
    report = _put(workflows, b"report")
    artifact_report = _artifact_report(workflows, artifact)
    constraints = _put(workflows, b"constraints")

    _advance(
        workflows,
        inputs=(),
        contract="prepare.v1",
        run_stage=lambda *_: (
            NamedRef("timeline", _put(workflows, b"timeline")),
            NamedRef("check_policy", _put(workflows, b"policy")),
            NamedRef("check_report", report),
            NamedRef("constraints", constraints),
            NamedRef("publication_manifest", _publication(workflows)),
        ),
    )
    _advance(
        workflows,
        inputs=(),
        contract="draft.v1",
        run_stage=lambda *_: (NamedRef("artifact", _put(workflows, b"draft")),),
    )
    _advance(
        workflows,
        inputs=(),
        contract="final.v1",
        run_stage=lambda *_: (
            NamedRef("artifact", artifact),
            NamedRef("artifact_report", artifact_report),
            NamedRef("execution", _put(workflows, b"execution")),
            NamedRef("render_options", _put(workflows, b"options")),
        ),
    )
    verdict = ReviewVerdict(
        artifact=artifact,
        artifact_report=artifact_report,
        publication_manifest=_publication(workflows),
        outcome="pass",
        check_report=report,
        constraints=constraints,
        scope=("audio", "visual", "constraints", "publication"),
        reviewer="video.reviewer",
        reviewed_at="2026-07-27T00:00:00Z",
    )
    with pytest.raises(ValueError, match="exact artifact report"):
        submit_review(
            workflows,
            ReviewVerdict(
                artifact=artifact,
                artifact_report=_artifact_report(
                    workflows,
                    _put(workflows, b"stale final"),
                ),
                publication_manifest=_publication(workflows),
                outcome="pass",
                check_report=report,
                constraints=constraints,
                scope=("audio", "visual", "constraints", "publication"),
                reviewer="video.reviewer",
                reviewed_at="2026-07-27T00:00:00Z",
            ),
        )
    current = get_status(workflows)
    running = current.start(
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
    workflows.save(
        running,
        expected_workflow_revision=current.revision,
        expected_head_revision=workflows.head_revision(),
    )

    reviewed = submit_review(workflows, verdict)
    assert reviewed.current_stage == "package"
    assert reviewed.attempts[-1].outputs == (
        NamedRef("verdict", verdict.ref),
    )

    # A lost response can be retried with the identical exact verdict.
    assert submit_review(workflows, verdict) == reviewed


def test_pass_then_upstream_invalidation_accepts_a_new_review_round(
    tmp_path: Path,
) -> None:
    workflows = _workflows(tmp_path)
    start_workflow(workflows, run_id="run.main", kind="reel")
    first_artifact = _put(workflows, b"first final")
    first_artifact_report = _artifact_report(workflows, first_artifact)
    first_report = _put(workflows, b"first report")
    first_constraints = _put(workflows, b"first constraints")

    _advance(
        workflows,
        inputs=(),
        contract="prepare.v1",
        run_stage=lambda *_: (
            NamedRef("timeline", _put(workflows, b"first timeline")),
            NamedRef("check_policy", _put(workflows, b"first policy")),
            NamedRef("check_report", first_report),
            NamedRef("constraints", first_constraints),
            NamedRef("publication_manifest", _publication(workflows)),
        ),
    )
    _advance(
        workflows,
        inputs=(),
        contract="draft.v1",
        run_stage=lambda *_: (
            NamedRef("artifact", _put(workflows, b"first draft")),
        ),
    )
    _advance(
        workflows,
        inputs=(),
        contract="final.v1",
        run_stage=lambda *_: (
            NamedRef("artifact", first_artifact),
            NamedRef(
                "artifact_report",
                first_artifact_report,
            ),
            NamedRef("execution", _put(workflows, b"first execution")),
            NamedRef("render_options", _put(workflows, b"first options")),
        ),
    )
    first_verdict = ReviewVerdict(
        artifact=first_artifact,
        artifact_report=first_artifact_report,
        publication_manifest=_publication(workflows),
        outcome="pass",
        check_report=first_report,
        constraints=first_constraints,
        scope=("audio", "visual", "constraints", "publication"),
        reviewer="video.reviewer",
        reviewed_at="2026-07-27T00:00:00Z",
    )
    first_reviewed = submit_review(workflows, first_verdict)
    first_latest = workflows.read_latest_review_round_ref()
    assert first_reviewed.current_stage == "package"
    assert first_latest is not None

    changed_source = _put(workflows, b"changed upstream source")
    prepare_inputs = (NamedRef("source", changed_source),)
    invalidated = first_reviewed.start(
        "prepare",
        prepare_inputs,
        contract="prepare.v2",
    )
    workflows.save(
        invalidated,
        expected_workflow_revision=first_reviewed.revision,
        expected_head_revision=workflows.head_revision(),
    )

    second_report = _put(workflows, b"second report")
    second_constraints = _put(workflows, b"second constraints")
    _advance(
        workflows,
        inputs=prepare_inputs,
        contract="prepare.v2",
        run_stage=lambda *_: (
            NamedRef("timeline", _put(workflows, b"second timeline")),
            NamedRef("check_policy", _put(workflows, b"second policy")),
            NamedRef("check_report", second_report),
            NamedRef("constraints", second_constraints),
            NamedRef("publication_manifest", _publication(workflows)),
        ),
    )
    _advance(
        workflows,
        inputs=(),
        contract="draft.v2",
        run_stage=lambda *_: (
            NamedRef("artifact", _put(workflows, b"second draft")),
        ),
    )
    second_artifact = _put(workflows, b"second final")
    second_artifact_report = _artifact_report(workflows, second_artifact)
    _advance(
        workflows,
        inputs=(),
        contract="final.v2",
        run_stage=lambda *_: (
            NamedRef("artifact", second_artifact),
            NamedRef(
                "artifact_report",
                second_artifact_report,
            ),
            NamedRef("execution", _put(workflows, b"second execution")),
            NamedRef("render_options", _put(workflows, b"second options")),
        ),
    )
    assert get_status(workflows).current_stage == "review"
    assert workflows.read_latest_review_round_ref() == first_latest

    second_verdict = ReviewVerdict(
        artifact=second_artifact,
        artifact_report=second_artifact_report,
        publication_manifest=_publication(workflows),
        outcome="pass",
        check_report=second_report,
        constraints=second_constraints,
        scope=("audio", "visual", "constraints", "publication"),
        reviewer="video.reviewer",
        reviewed_at="2026-07-30T00:00:00Z",
    )
    second_reviewed = submit_review(
        workflows,
        second_verdict,
        expected_latest_round=first_latest,
    )

    second_latest = workflows.read_latest_review_round_ref()
    assert second_reviewed.current_stage == "package"
    assert second_latest is not None
    assert second_latest != first_latest
    persisted_round = ReviewRound.from_canonical_bytes(
        workflows.read_blob(second_latest)
    )
    assert persisted_round.previous_round == first_latest
    assert persisted_round.verdict == second_verdict.ref


def test_pass_reuses_exact_latest_round_after_upstream_invalidation(
    tmp_path: Path,
) -> None:
    workflows = _workflows(tmp_path)
    start_workflow(workflows, run_id="run.main", kind="reel")
    timeline = _put(workflows, b"stable timeline")
    policy = _put(workflows, b"stable policy")
    report = _put(workflows, b"stable report")
    constraints = _put(workflows, b"stable constraints")
    draft_artifact = _put(workflows, b"stable draft")
    final_artifact = _put(workflows, b"stable final")
    artifact_report = _artifact_report(workflows, final_artifact)
    execution = _put(workflows, b"stable execution")
    render_options = _put(workflows, b"stable options")

    _advance(
        workflows,
        inputs=(),
        contract="prepare.v1",
        run_stage=lambda *_: (
            NamedRef("timeline", timeline),
            NamedRef("check_policy", policy),
            NamedRef("check_report", report),
            NamedRef("constraints", constraints),
            NamedRef("publication_manifest", _publication(workflows)),
        ),
    )
    _advance(
        workflows,
        inputs=(),
        contract="draft.v1",
        run_stage=lambda *_: (
            NamedRef("artifact", draft_artifact),
        ),
    )
    _advance(
        workflows,
        inputs=(),
        contract="final.v1",
        run_stage=lambda *_: (
            NamedRef("artifact", final_artifact),
            NamedRef("artifact_report", artifact_report),
            NamedRef("execution", execution),
            NamedRef("render_options", render_options),
        ),
    )
    verdict = ReviewVerdict(
        artifact=final_artifact,
        artifact_report=artifact_report,
        publication_manifest=_publication(workflows),
        outcome="pass",
        check_report=report,
        constraints=constraints,
        scope=("audio", "visual", "constraints", "publication"),
        reviewer="video.reviewer",
        reviewed_at="2026-07-30T00:00:00Z",
    )
    first_passed = submit_review(workflows, verdict)
    latest = workflows.read_latest_review_round_ref()
    assert first_passed.current_stage == "package"
    assert latest is not None

    changed_source = _put(workflows, b"changed source, identical result")
    prepare_inputs = (NamedRef("source", changed_source),)
    invalidated = first_passed.start(
        "prepare",
        prepare_inputs,
        contract="prepare.v2",
    )
    workflows.save(
        invalidated,
        expected_workflow_revision=first_passed.revision,
        expected_head_revision=workflows.head_revision(),
    )
    _advance(
        workflows,
        inputs=prepare_inputs,
        contract="prepare.v2",
        run_stage=lambda *_: (
            NamedRef("timeline", timeline),
            NamedRef("check_policy", policy),
            NamedRef("check_report", report),
            NamedRef("constraints", constraints),
            NamedRef("publication_manifest", _publication(workflows)),
        ),
    )
    _advance(
        workflows,
        inputs=(),
        contract="draft.v2",
        run_stage=lambda *_: (
            NamedRef("artifact", draft_artifact),
        ),
    )
    _advance(
        workflows,
        inputs=(),
        contract="final.v2",
        run_stage=lambda *_: (
            NamedRef("artifact", final_artifact),
            NamedRef("artifact_report", artifact_report),
            NamedRef("execution", execution),
            NamedRef("render_options", render_options),
        ),
    )
    review_ready_again = get_status(workflows)
    assert review_ready_again.current_stage == "review"
    assert workflows.read_latest_review_round_ref() == latest
    head_before_reattach = workflows.head_revision()

    reattached = submit_review(
        workflows,
        verdict,
        expected_latest_round=latest,
    )

    assert reattached.current_stage == "package"
    assert reattached.revision == review_ready_again.revision + 2
    assert workflows.head_revision() == head_before_reattach + 1
    assert workflows.read_latest_review_round_ref() == latest
    assert reattached.attempts[-1].outputs == (
        NamedRef("verdict", verdict.ref),
    )

    committed_head = workflows.head_revision()
    assert (
        submit_review(
            workflows,
            verdict,
            expected_latest_round=latest,
        )
        == reattached
    )
    assert workflows.head_revision() == committed_head
    assert workflows.read_latest_review_round_ref() == latest


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
    with pytest.raises(ValueError, match="package stage"):
        _advance(
            workflows,
            inputs=(),
            contract="package.v1",
            run_stage=lambda *_: (
                NamedRef("candidate", _put(workflows, b"arbitrary")),
            ),
        )
