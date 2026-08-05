"""The real compile/check/render/package path behind every adapter."""

from __future__ import annotations

from pathlib import Path

from dlstudio.assets.api import AssetReadPort
from dlstudio.authoring.api import load_edit
from dlstudio.constraints.api import ConstraintSet
from dlstudio.foundation.api import BlobRef
from dlstudio.release.api import PackageFile, PublicationManifest
from dlstudio.rendering.api import (
    ArtifactReport,
    analyze_voice_signal,
    ExecutionFingerprint,
    RenderOptions,
    RenderResult,
    execution_key,
    paired_ffprobe,
    render as render_timeline,
    verify_rendered_artifact,
)
from dlstudio.review.api import ReviewVerdict
from dlstudio.timeline.api import (
    CheckPolicy,
    CheckReport,
    TimelineIR,
    check_timeline,
)
from dlstudio.workflow.api import NamedRef, StageId, WorkflowRun, WorkflowStore

from .authoring import compile_production, resolve_publication
from .release import BlobStore, build_release_gate
from .workflow import (
    _advance,
    _package_release,
    _run_stage,
    get_status,
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
    if edit.production_id != workflows.production_id:
        raise ValueError("authoring belongs to another production")
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
    publication, publication_revisions = resolve_publication(edit, assets)
    for revision in publication_revisions:
        if store.put_bytes(revision.canonical_bytes()) != revision.ref.object:
            raise ValueError("publication revision identity mismatch")
        for reachable in revision.reachable_blobs:
            store.verify(reachable)
    publication_ref = store.put_bytes(publication.canonical_bytes())
    expected_platform = {
        "reel": "vertical",
        "longform": "landscape",
        "capture_vo": "landscape",
    }[current.kind]
    constraints, policy = build_release_gate(
        workflows.production_id,
        expected_platform,
        require_voice=bool(edit.voice_script and edit.voice_script.strip()),
        kind=current.kind,
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
        NamedRef("publication_manifest", publication_ref),
        NamedRef("timeline", timeline_ref),
    )
    prepare_outputs = (
        NamedRef("check_policy", policy.ref),
        NamedRef("check_report", report.ref),
        NamedRef("constraints", constraints.ref),
        NamedRef("publication_manifest", publication_ref),
        NamedRef("timeline", timeline_ref),
    )

    def prepare(*_unused: object) -> tuple[NamedRef, ...]:
        if report.blocking:
            finding_ids = ", ".join(
                item.rule for item in report.findings
                if item.severity == "error"
            )
            raise ValueError(f"pre-render checks failed: {finding_ids}")
        return prepare_outputs

    previous_prepare = next(
        (item for item in current.attempts if item.stage == "prepare"),
        None,
    )
    if previous_prepare is not None and (
        previous_prepare.inputs != prepare_inputs
        or previous_prepare.outputs != prepare_outputs
    ):
        return _run_stage(
            workflows,
            current=current,
            stage="prepare",
            inputs=prepare_inputs,
            contract="studio.v3.prepare.v1",
            run_stage=prepare,
        )

    stage = current.current_stage
    if stage == "prepare":
        return _advance(
            workflows,
            inputs=prepare_inputs,
            contract="studio.v3.prepare.v1",
            run_stage=prepare,
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
            artifact_report = verify_rendered_artifact(
                artifact,
                store.path_for(artifact),
                timeline,
                require_voice=policy.require_voice,
                voice_signal=(
                    analyze_voice_signal(
                        artifact,
                        store.path_for(artifact),
                        timeline,
                        store,
                        ffmpeg=execution.ffmpeg,
                    )
                    if policy.require_voice
                    else None
                ),
                ffmpeg=execution.ffmpeg,
                ffprobe=paired_ffprobe(execution.ffmpeg),
            )
            artifact_report_ref = store.put_bytes(
                artifact_report.canonical_bytes()
            )
            if artifact_report.blocking:
                finding_ids = ", ".join(
                    item.rule
                    for item in artifact_report.findings
                    if item.severity == "error"
                )
                raise ValueError(
                    f"rendered artifact checks failed: {finding_ids}"
                )
            return (
                NamedRef("artifact", artifact),
                NamedRef("artifact_report", artifact_report_ref),
                NamedRef("execution", execution.ref),
                NamedRef("render_options", options.ref),
            )

        return _advance(
            workflows,
            inputs=(
                NamedRef("execution", execution.ref),
                NamedRef("render_options", options.ref),
                NamedRef("timeline", timeline_ref),
            ),
            contract=(
                "studio.v3.draft.v1"
                if stage == "draft"
                else "studio.v3.final.v2"
            ),
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
        loaded_artifact_report = ArtifactReport.from_canonical_bytes(
            store.read(finalized["artifact_report"])
        )
        loaded_constraints = ConstraintSet.from_canonical_bytes(
            store.read(prepared["constraints"])
        )
        loaded_publication = PublicationManifest.from_canonical_bytes(
            store.read(prepared["publication_manifest"])
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
        _, ready = _package_release(
            workflows,
            store,
            timeline=loaded_timeline,
            kind=current.kind,
            policy=loaded_policy,
            report=loaded_report,
            artifact_report=loaded_artifact_report,
            publication=loaded_publication,
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
