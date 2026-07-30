"""One helpful application path for starting and advancing a workflow."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any, Literal
from dlstudio.constraints.api import ConstraintSet
from dlstudio.foundation.api import BlobRef, CasConflict, canonical_bytes
from dlstudio.release.api import PackageFile, ReleaseCandidate
from dlstudio.rendering.api import (
    ExecutionFingerprint,
    RenderOptions,
    RenderResult,
)
from dlstudio.review.api import (
    ReviewFinding,
    ReviewLocator,
    ReviewResolution,
    ReviewRegion,
    ReviewRound,
    ReviewVerdict,
    validate_review_round_transition,
)
from dlstudio.timeline.api import (
    CheckPolicy,
    CheckReport,
    TimelineIR,
)
from dlstudio.workflow.api import (
    NamedRef,
    STAGES,
    StageId,
    WorkflowStore,
    WorkflowKind,
    WorkflowRun,
)

from .release import BlobStore, freeze_release
from .review import query_review_context


@dataclass(frozen=True, slots=True)
class WorkflowStatus:
    """Read-only application projection shared by every adapter."""

    production_id: str
    workflow: WorkflowRun | None
    stage_order: tuple[StageId, ...]
    current_stage: StageId | None
    completed: bool
    action: Literal["advance", "review", "deliver"] | None

    def as_payload(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "workflow": (
                None if self.workflow is None else self.workflow.as_payload()
            ),
            "stage_order": list(self.stage_order),
            "current_stage": self.current_stage,
            "completed": self.completed,
            "action": self.action,
        }


def project_status(workflow: WorkflowRun) -> WorkflowStatus:
    stage = workflow.current_stage
    action = (
        None
        if stage is None
        else stage
        if stage in {"review", "deliver"}
        else "advance"
    )
    return WorkflowStatus(
        workflow.production_id,
        workflow,
        STAGES,
        stage,
        workflow.completed,
        action,
    )


def query_status(workflows: WorkflowStore) -> WorkflowStatus:
    workflow = workflows.read_current()
    if workflow is None:
        return WorkflowStatus(
            workflows.production_id,
            None,
            STAGES,
            "prepare",
            False,
            "advance",
        )
    return project_status(workflow)


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


def _advance(
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
        raise ValueError("package stage is owned by advance_production")
    return _run_stage(
        workflows,
        current=current,
        stage=stage,
        inputs=inputs,
        contract=contract,
        run_stage=run_stage,
    )


def _run_stage(
    workflows: WorkflowStore,
    *,
    current: WorkflowRun,
    stage: StageId,
    inputs: tuple[NamedRef, ...],
    contract: str,
    run_stage: Callable[[StageId, str], tuple[NamedRef, ...]],
) -> WorkflowRun:
    """Run one selected stage; identical persisted attempts resume in place."""

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
    if succeeded is not running:
        _save_next(workflows, running, succeeded)
    return succeeded


def submit_review(
    workflows: WorkflowStore,
    verdict: ReviewVerdict,
    *,
    expected_latest_round: BlobRef | None = None,
    resolutions: tuple[ReviewResolution, ...] = (),
) -> WorkflowRun:
    """Attach a verdict only to the exact final artifact and its exact gates."""

    current = get_status(workflows)
    prepare = next(item for item in current.attempts if item.stage == "prepare")
    final = next(item for item in current.attempts if item.stage == "final")
    prepared = {item.name: item.blob for item in prepare.outputs}
    finalized = {item.name: item.blob for item in final.outputs}
    if set(prepared) != {
        "timeline",
        "check_policy",
        "check_report",
        "constraints",
    } or set(finalized) != {"artifact", "execution", "render_options"}:
        raise ValueError("prepare/final stage output contract is incomplete")
    if verdict.artifact != finalized["artifact"]:
        raise ValueError("review does not name the exact final artifact")
    if verdict.check_report != prepared["check_report"]:
        raise ValueError("review does not name the exact check report")
    if verdict.constraints != prepared["constraints"]:
        raise ValueError("review does not name the exact constraints")
    for ref in verdict.reachable_blobs:
        workflows.verify_blob(ref)

    previous_round = (
        None
        if expected_latest_round is None
        else ReviewRound.from_canonical_bytes(
            workflows.read_blob(expected_latest_round)
        )
    )
    previous_verdict = (
        None
        if previous_round is None
        else ReviewVerdict.from_canonical_bytes(
            workflows.read_blob(previous_round.verdict)
        )
    )
    reuse_existing_pass = (
        expected_latest_round is not None
        and previous_round is not None
        and previous_verdict is not None
        and previous_verdict.outcome == "pass"
        and verdict.outcome == "pass"
        and (
            verdict.artifact,
            verdict.check_report,
            verdict.constraints,
        )
        == (
            previous_verdict.artifact,
            previous_verdict.check_report,
            previous_verdict.constraints,
        )
    )
    if reuse_existing_pass:
        if resolutions:
            raise ValueError("reused passing review cannot resolve findings")
        selected_verdict = previous_verdict
        verdict_ref = previous_round.verdict
        round_ref = expected_latest_round
    else:
        selected_verdict = verdict
        verdict_ref = workflows.put_blob(verdict.canonical_bytes())
        review_round = ReviewRound(
            verdict_ref,
            expected_latest_round,
            resolutions,
        )
        validate_review_round_transition(
            review_round,
            verdict,
            previous_round=previous_round,
            previous_verdict=previous_verdict,
        )
        round_ref = workflows.put_blob(review_round.canonical_bytes())

    if current.current_stage != "review":
        latest = workflows.read_latest_review_round_ref()
        reviewed = next(
            (
                item
                for item in current.attempts
                if item.stage == "review" and item.state == "succeeded"
            ),
            None,
        )
        if (
            latest == round_ref
            and reviewed is not None
            and reviewed.outputs == (NamedRef("verdict", verdict_ref),)
        ):
            return current
        raise ValueError("workflow is not waiting for review")

    desired = current
    if selected_verdict.outcome == "pass":
        running = current.start(
            "review",
            (
                NamedRef("artifact", selected_verdict.artifact),
                NamedRef("check_report", selected_verdict.check_report),
                NamedRef("constraints", selected_verdict.constraints),
            ),
            contract=f"{ReviewVerdict.DOMAIN}.v{ReviewVerdict.VERSION}",
        )
        desired = running.succeed(
            running.attempts[-1].operation_id,
            (NamedRef("verdict", verdict_ref),),
        )
    return workflows.commit_review_round(
        desired,
        round_ref,
        expected_workflow_revision=current.revision,
        expected_head_revision=_head_revision(workflows),
        expected_latest_round=expected_latest_round,
    )


def submit_review_payload(
    workflows: WorkflowStore,
    payload: Mapping[str, Any],
    store: BlobStore,
    *,
    expected_artifact: BlobRef | None = None,
    expected_timeline: BlobRef | None = None,
    expected_check_report: BlobRef | None = None,
    expected_constraints: BlobRef | None = None,
) -> WorkflowRun:
    """Create the exact verdict from a small transport-neutral review payload."""

    required = {"outcome", "scope", "reviewer", "reviewed_at", "findings"}
    optional = {"expected_latest_round", "resolutions"}
    if not required.issubset(payload) or set(payload) - required - optional:
        raise ValueError("review payload fields mismatch")
    expected_latest_value = payload.get("expected_latest_round")
    expected_latest_round = (
        None
        if expected_latest_value is None
        else BlobRef.from_payload(expected_latest_value)
    )
    resolutions = tuple(
        ReviewResolution.from_payload(dict(item))
        for item in payload.get("resolutions", ())
    )
    expected = (
        expected_artifact,
        expected_timeline,
        expected_check_report,
        expected_constraints,
    )
    if any(item is not None for item in expected) and any(
        item is None for item in expected
    ):
        raise ValueError("expected review context must be complete")
    findings = tuple(
        ReviewFinding(
            finding_id=str(item["finding_id"]),
            text=str(item["text"]),
            requires_change=bool(item.get("requires_change", False)),
            locator=(
                None
                if item.get("locator") is None
                else ReviewLocator(
                    start_frame=int(item["locator"]["start_frame"]),
                    end_frame_exclusive=int(
                        item["locator"]["end_frame_exclusive"]
                    ),
                    region=(
                        None
                        if item["locator"].get("region") is None
                        else ReviewRegion(
                            x_milli=int(
                                item["locator"]["region"]["x_milli"]
                            ),
                            y_milli=int(
                                item["locator"]["region"]["y_milli"]
                            ),
                            width_milli=int(
                                item["locator"]["region"]["width_milli"]
                            ),
                            height_milli=int(
                                item["locator"]["region"]["height_milli"]
                            ),
                        )
                    ),
                    target_ids=tuple(
                        str(target)
                        for target in item["locator"].get("target_ids", ())
                    ),
                )
            ),
        )
        for item in payload["findings"]
    )
    context = query_review_context(workflows, store)
    if expected_artifact is not None and expected != (
        context.artifact,
        context.timeline,
        context.check_report,
        context.constraints,
    ):
        raise CasConflict("review context changed; reload the exact artifact")
    frame_count = (
        context.duration_ns * context.fps_num
        + 1_000_000_000 * context.fps_den
        - 1
    ) // (1_000_000_000 * context.fps_den)
    targets = {item.item_id: item for item in context.items}
    frame_denominator = 1_000_000_000 * context.fps_den
    for finding in findings:
        locator = finding.locator
        if locator is None:
            continue
        if locator.end_frame_exclusive > frame_count:
            raise ValueError("review locator exceeds the final artifact")
        unknown = set(locator.target_ids) - targets.keys()
        if unknown:
            raise ValueError(f"review locator has unknown targets: {sorted(unknown)}")
        inactive = {
            target_id
            for target_id in locator.target_ids
            if (
                (
                    targets[target_id].start_ns * context.fps_num
                    + frame_denominator
                    - 1
                )
                // frame_denominator
                >= locator.end_frame_exclusive
                or (
                    (
                        targets[target_id].start_ns
                        + targets[target_id].duration_ns
                    )
                    * context.fps_num
                    + frame_denominator
                    - 1
                )
                // frame_denominator
                <= locator.start_frame
            )
        }
        if inactive:
            raise ValueError(
                f"review locator has inactive targets: {sorted(inactive)}"
            )
    verdict = ReviewVerdict(
        artifact=context.artifact,
        outcome=payload["outcome"],
        check_report=context.check_report,
        constraints=context.constraints,
        scope=tuple(str(item) for item in payload["scope"]),
        reviewer=str(payload["reviewer"]),
        reviewed_at=str(payload["reviewed_at"]),
        findings=findings,
    )
    return submit_review(
        workflows,
        verdict,
        expected_latest_round=expected_latest_round,
        resolutions=resolutions,
    )


def _package_release(
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
    succeeded = workflows._complete_package(
        running,
        operation_id,
        candidate_ref,
        expected_workflow_revision=running.revision,
        expected_head_revision=_head_revision(workflows),
    )
    return candidate, succeeded


def _stage_outputs(workflow: WorkflowRun, stage: StageId) -> dict[str, BlobRef]:
    attempt = next(item for item in workflow.attempts if item.stage == stage)
    return {item.name: item.blob for item in attempt.outputs}


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
