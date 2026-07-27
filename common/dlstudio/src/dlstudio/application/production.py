"""The real compile/check/render/package path behind every adapter."""

from __future__ import annotations

from pathlib import Path

from dlstudio.assets.api import AssetReadPort
from dlstudio.authoring.api import load_edit
from dlstudio.constraints.api import ConstraintSet
from dlstudio.foundation.api import BlobRef
from dlstudio.release.api import PackageFile
from dlstudio.rendering.api import (
    ExecutionFingerprint,
    RenderOptions,
    RenderResult,
    execution_key,
    render as render_timeline,
)
from dlstudio.review.api import ReviewVerdict
from dlstudio.timeline.api import (
    CheckPolicy,
    CheckReport,
    TimelineIR,
    check_timeline,
)
from dlstudio.workflow.api import NamedRef, StageId, WorkflowRun, WorkflowStore

from .authoring import compile_production
from .release import BlobStore
from .workflow import (
    _save_next,
    advance,
    get_status,
    package_release,
    start_workflow,
)


def advance_production(
    workflows: WorkflowStore,
    assets: AssetReadPort,
    store: BlobStore,
    *,
    authoring_path: Path,
    output_root: Path,
    cache_root: Path | None = None,
    fingerprint: ExecutionFingerprint | None = None,
) -> WorkflowRun:
    """Start when needed, then advance one user-visible production step."""

    edit = load_edit(authoring_path)
    workflow_kind = "longform" if edit.kind == "devlog" else edit.kind
    current = workflows.read_current()
    if current is None:
        current = start_workflow(
            workflows,
            run_id="run.main",
            kind=workflow_kind,
        )
    elif current.kind != workflow_kind:
        raise ValueError("authoring kind does not match the current workflow")
    timeline = compile_production(edit, assets)
    timeline_ref = store.put_bytes(timeline.canonical_bytes())
    constraints = ConstraintSet(
        workflows.production_id,
        "studio.v3.defaults",
        (),
    )
    policy = CheckPolicy(
        policy_id="studio_v3.release",
        platform=(
            "vertical" if timeline.height > timeline.width else "landscape"
        ),
        constraints=constraints.ref,
        require_approved_assets=True,
        require_redistributable_assets=True,
    )
    report = check_timeline(timeline, policy)
    for raw in (
        constraints.canonical_bytes(),
        policy.canonical_bytes(),
        report.canonical_bytes(),
    ):
        store.put_bytes(raw)

    prepare_inputs = (
        NamedRef("authoring", store.put_bytes(authoring_path.read_bytes())),
        NamedRef("check_policy", policy.ref),
        NamedRef("constraints", constraints.ref),
        NamedRef("timeline", timeline_ref),
    )
    prepare_outputs = (
        NamedRef("check_policy", policy.ref),
        NamedRef("check_report", report.ref),
        NamedRef("constraints", constraints.ref),
        NamedRef("timeline", timeline_ref),
    )
    previous_prepare = next(
        (item for item in current.attempts if item.stage == "prepare"),
        None,
    )
    if previous_prepare is not None and (
        previous_prepare.inputs != prepare_inputs
        or previous_prepare.outputs != prepare_outputs
    ):
        running = current.start(
            "prepare", prepare_inputs, contract="studio.v3.prepare.v1"
        )
        _save_next(workflows, current, running)
        succeeded = running.succeed(
            running.attempts[-1].operation_id, prepare_outputs
        )
        _save_next(workflows, running, succeeded)
        return succeeded

    stage = current.current_stage
    if stage == "prepare":
        return advance(
            workflows,
            inputs=prepare_inputs,
            contract="studio.v3.prepare.v1",
            run_stage=lambda *_: prepare_outputs,
        )
    if stage in {"draft", "final"}:
        execution = fingerprint or ExecutionFingerprint.detect()
        options = RenderOptions(crf=28) if stage == "draft" else RenderOptions()
        store.put_bytes(execution.canonical_bytes())
        store.put_bytes(options.canonical_bytes())
        output = output_root / f"{stage}.mp4"

        def run_render(*_unused: object) -> tuple[NamedRef, ...]:
            result = render_timeline(
                timeline,
                execution,
                options,
                store,
                output=output,
                cache_root=cache_root,
            )
            artifact = store.ingest_file(result.path)
            if artifact != result.artifact:
                raise ValueError("render artifact changed before object ingest")
            if stage == "draft":
                return (NamedRef("artifact", artifact),)
            return (
                NamedRef("artifact", artifact),
                NamedRef("execution", execution.ref),
                NamedRef("render_options", options.ref),
            )

        return advance(
            workflows,
            inputs=(
                NamedRef("execution", execution.ref),
                NamedRef("render_options", options.ref),
                NamedRef("timeline", timeline_ref),
            ),
            contract=f"studio.v3.{stage}.v1",
            run_stage=run_render,  # type: ignore[arg-type]
        )
    if stage == "review":
        raise ValueError("workflow is waiting for exact final review")
    if stage == "package":
        prepared = _stage_outputs(current, "prepare")
        finalized = _stage_outputs(current, "final")
        reviewed = _stage_outputs(current, "review")
        loaded_timeline = TimelineIR.from_canonical_bytes(
            store.read(prepared["timeline"])
        )
        loaded_policy = CheckPolicy.from_canonical_bytes(
            store.read(prepared["check_policy"])
        )
        loaded_report = CheckReport.from_canonical_bytes(
            store.read(prepared["check_report"])
        )
        loaded_constraints = ConstraintSet.from_canonical_bytes(
            store.read(prepared["constraints"])
        )
        loaded_execution = ExecutionFingerprint.from_canonical_bytes(
            store.read(finalized["execution"])
        )
        loaded_options = RenderOptions.from_canonical_bytes(
            store.read(finalized["render_options"])
        )
        loaded_verdict = ReviewVerdict.from_canonical_bytes(
            store.read(reviewed["verdict"])
        )
        rendered = RenderResult(
            finalized["artifact"],
            store.path_for(finalized["artifact"]),
            execution_key(loaded_timeline, loaded_execution, loaded_options),
            False,
            (),
        )
        _, ready = package_release(
            workflows,
            store,
            timeline=loaded_timeline,
            policy=loaded_policy,
            report=loaded_report,
            fingerprint=loaded_execution,
            options=loaded_options,
            render=rendered,
            constraints=loaded_constraints,
            verdict=loaded_verdict,
            package=(PackageFile("video.mp4", rendered.artifact),),
        )
        return ready
    if stage == "deliver":
        raise ValueError("use deliver for the delivery stage")
    return current


def _stage_outputs(workflow: WorkflowRun, stage: StageId) -> dict[str, BlobRef]:
    attempt = next(item for item in workflow.attempts if item.stage == stage)
    return {item.name: item.blob for item in attempt.outputs}
