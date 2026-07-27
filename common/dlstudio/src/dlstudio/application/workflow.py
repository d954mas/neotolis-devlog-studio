"""One helpful application path for starting and advancing a workflow."""

from __future__ import annotations

from collections.abc import Callable

from dlstudio.constraints.api import ConstraintSet
from dlstudio.foundation.api import BlobRef, canonical_bytes
from dlstudio.release.api import PackageFile, ReleaseCandidate
from dlstudio.rendering.api import (
    ExecutionFingerprint,
    RenderOptions,
    RenderResult,
)
from dlstudio.review.api import ReviewVerdict
from dlstudio.timeline.api import CheckPolicy, CheckReport, TimelineIR
from dlstudio.workflow.api import (
    NamedRef,
    StageId,
    WorkflowStore,
    WorkflowKind,
    WorkflowRun,
)

from .release import BlobStore, freeze_release


def get_status(workflows: WorkflowStore) -> WorkflowRun:
    """Read the canonical status without compiling or scanning the project."""

    current = workflows.read_current()
    if current is None:
        raise ValueError("production has no workflow")
    return current


def start_workflow(
    workflows: WorkflowStore,
    *,
    run_id: str,
    kind: WorkflowKind,
) -> WorkflowRun:
    """Create the production's single workflow; identical retries are harmless."""

    current = workflows.read_current()
    if current is not None:
        if current.run_id != run_id or current.kind != kind:
            raise ValueError("production already has another workflow")
        return current
    created = WorkflowRun(run_id, workflows.production_id, kind)
    workflows.save(
        created,
        expected_workflow_revision=-1,
        expected_head_revision=_head_revision(workflows),
    )
    return created


def advance(
    workflows: WorkflowStore,
    *,
    inputs: tuple[NamedRef, ...],
    contract: str,
    run_stage: Callable[[StageId, str], tuple[NamedRef, ...]],
) -> WorkflowRun:
    """Run the next automatic stage with crash-safe, idempotent bookkeeping."""

    current = get_status(workflows)
    stage = current.current_stage
    if stage is None:
        return current
    if stage == "deliver":
        raise ValueError("use deliver for the delivery stage")
    if stage == "review":
        raise ValueError("use submit_review for the review stage")
    if stage == "package":
        raise ValueError("use package_release for the package stage")

    running = current.start(stage, inputs, contract=contract)
    if running is not current:
        _save_next(workflows, current, running)
    operation_id = next(
        item.operation_id
        for item in running.attempts
        if item.stage == stage
    )
    try:
        outputs = run_stage(stage, operation_id)
    except Exception as exc:
        failed = running.fail(operation_id, str(exc))
        _save_next(workflows, running, failed)
        raise
    succeeded = running.succeed(operation_id, outputs)
    _save_next(workflows, running, succeeded)
    return succeeded


def submit_review(
    workflows: WorkflowStore,
    verdict: ReviewVerdict,
) -> WorkflowRun:
    """Attach a verdict only to the exact final artifact and its exact gates."""

    current = get_status(workflows)
    if current.current_stage != "review":
        raise ValueError("workflow is not waiting for review")
    final = next(item for item in current.attempts if item.stage == "final")
    expected = {item.name: item.blob for item in final.outputs}
    required = {"artifact", "check_report", "constraints"}
    if set(expected) != required:
        raise ValueError("final stage output contract is incomplete")
    if verdict.artifact != expected["artifact"]:
        raise ValueError("review does not name the exact final artifact")
    if verdict.check_report != expected["check_report"]:
        raise ValueError("review does not name the exact check report")
    if verdict.constraints != expected["constraints"]:
        raise ValueError("review does not name the exact constraints")
    for ref in verdict.reachable_blobs:
        workflows.verify_blob(ref)
    verdict_ref = workflows.put_blob(verdict.canonical_bytes())

    running = current.start(
        "review",
        (
            NamedRef("artifact", verdict.artifact),
            NamedRef("check_report", verdict.check_report),
            NamedRef("constraints", verdict.constraints),
        ),
        contract=f"{ReviewVerdict.DOMAIN}.v{ReviewVerdict.VERSION}",
    )
    _save_next(workflows, current, running)
    succeeded = running.succeed(
        running.attempts[-1].operation_id,
        (NamedRef("verdict", verdict_ref),),
    )
    _save_next(workflows, running, succeeded)
    return succeeded


def package_release(
    workflows: WorkflowStore,
    store: BlobStore,
    *,
    timeline: TimelineIR,
    policy: CheckPolicy,
    report: CheckReport,
    fingerprint: ExecutionFingerprint,
    options: RenderOptions,
    render: RenderResult,
    constraints: ConstraintSet,
    verdict: ReviewVerdict,
    package: tuple[PackageFile, ...],
) -> tuple[ReleaseCandidate, WorkflowRun]:
    """Freeze the exact release and make only that candidate deliverable."""

    current = get_status(workflows)
    if current.current_stage != "package":
        raise ValueError("workflow is not ready to package")
    review = next(item for item in current.attempts if item.stage == "review")
    if review.outputs != (NamedRef("verdict", verdict.ref),):
        raise ValueError("package does not use the accepted review verdict")
    package_manifest = workflows.put_blob(
        canonical_bytes(
            {"files": [item.as_payload() for item in package]},
            domain="dlstudio.release_package_input",
            version=1,
        )
    )
    inputs = (
        NamedRef("check_policy", policy.ref),
        NamedRef("check_report", report.ref),
        NamedRef("constraints", constraints.ref),
        NamedRef("execution", fingerprint.ref),
        NamedRef("package_manifest", package_manifest),
        NamedRef("render_options", options.ref),
        NamedRef("review_verdict", verdict.ref),
        NamedRef("timeline", timeline.ref),
    )
    running = current.start(
        "package",
        inputs,
        contract=f"{ReleaseCandidate.DOMAIN}.v{ReleaseCandidate.VERSION}",
    )
    if running is not current:
        _save_next(workflows, current, running)
    operation_id = next(
        item.operation_id
        for item in running.attempts
        if item.stage == "package"
    )
    try:
        candidate, candidate_ref = freeze_release(
            store,
            production_id=workflows.production_id,
            timeline=timeline,
            policy=policy,
            report=report,
            fingerprint=fingerprint,
            options=options,
            render=render,
            constraints=constraints,
            verdict=verdict,
            package=package,
        )
    except Exception as exc:
        failed = running.fail(operation_id, str(exc))
        _save_next(workflows, running, failed)
        raise
    succeeded = running.succeed(
        operation_id, (NamedRef("candidate", candidate_ref),)
    )
    _save_next(workflows, running, succeeded)
    eligible = succeeded.allow_delivery()
    _save_next(workflows, succeeded, eligible)
    return candidate, eligible


def _head_revision(workflows: WorkflowStore) -> int:
    return workflows.head_revision()


def _save_next(
    workflows: WorkflowStore,
    previous: WorkflowRun,
    current: WorkflowRun,
) -> None:
    workflows.save(
        current,
        expected_workflow_revision=previous.revision,
        expected_head_revision=_head_revision(workflows),
    )
