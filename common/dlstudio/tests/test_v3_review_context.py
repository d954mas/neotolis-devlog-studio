from __future__ import annotations

from dlstudio.application.review import query_review_context
from dlstudio.foundation.api import BlobRef
from dlstudio.rendering.api import ArtifactReport
from dlstudio.release.api import PublicationManifest
from dlstudio.timeline.api import (
    CheckReport,
    TimelineIR,
    VideoFadeInstruction,
    VisualInstruction,
)
from dlstudio.workflow.api import NamedRef, WorkflowRun


class _Workflows:
    def __init__(self, workflow: WorkflowRun) -> None:
        self.workflow = workflow

    def read_current(self) -> WorkflowRun:
        return self.workflow

    def read_latest_review_round_ref(self) -> BlobRef | None:
        return None


class _Store:
    def __init__(
        self,
        timeline: TimelineIR,
        report: CheckReport,
        artifact_report: ArtifactReport,
        publication: PublicationManifest,
    ) -> None:
        self.timeline = timeline
        self.report = report
        self.artifact_report = artifact_report
        self.publication = publication

    def read(self, ref: BlobRef) -> bytes:
        if ref == self.timeline.ref:
            return self.timeline.canonical_bytes()
        if ref == self.artifact_report.ref:
            return self.artifact_report.canonical_bytes()
        if ref == self.publication.ref:
            return self.publication.canonical_bytes()
        assert ref == self.report.ref
        return self.report.canonical_bytes()


def _succeed(
    workflow: WorkflowRun,
    stage: str,
    inputs: tuple[NamedRef, ...],
    outputs: tuple[NamedRef, ...],
) -> WorkflowRun:
    running = workflow.start(stage, inputs, contract=f"fixture.{stage}.v1")
    return running.succeed(running.attempts[-1].operation_id, outputs)


def test_review_context_projects_exact_artifact_and_timeline_lanes() -> None:
    timeline = TimelineIR(
        production_id="fixture.reel",
        width=1080,
        height=1920,
        fps_num=30,
        fps_den=1,
        duration_ns=2_000_000_000,
        background="black",
        visuals=(
            VisualInstruction(
                "solid",
                0,
                2_000_000_000,
                0,
                0,
                0,
                1080,
                1920,
                color="black",
                fade_out_ns=100_000_000,
            ),
        ),
        video_fades=(VideoFadeInstruction("out", 1_800_000_000, 200_000_000),),
    )
    artifact = BlobRef("a" * 64, 123)
    execution = BlobRef("b" * 64, 10)
    options = BlobRef("c" * 64, 11)
    policy = BlobRef("d" * 64, 12)
    report = CheckReport(timeline.ref, policy, ())
    artifact_report = ArtifactReport(
        artifact,
        timeline.width,
        timeline.height,
        timeline.fps_num,
        timeline.fps_den,
        timeline.duration_ns,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    constraints = BlobRef("f" * 64, 14)
    publication = PublicationManifest("fixture.reel")
    workflow = WorkflowRun("run.main", "fixture.reel", "reel")
    workflow = _succeed(
        workflow,
        "prepare",
        (NamedRef("timeline", timeline.ref),),
        (
            NamedRef("timeline", timeline.ref),
            NamedRef("check_policy", policy),
            NamedRef("check_report", report.ref),
            NamedRef("constraints", constraints),
            NamedRef("publication_manifest", publication.ref),
        ),
    )
    workflow = _succeed(
        workflow,
        "draft",
        (NamedRef("timeline", timeline.ref),),
        (NamedRef("artifact", BlobRef("1" * 64, 100)),),
    )
    workflow = _succeed(
        workflow,
        "final",
        (NamedRef("timeline", timeline.ref),),
        (
            NamedRef("artifact", artifact),
            NamedRef("artifact_report", artifact_report.ref),
            NamedRef("execution", execution),
            NamedRef("render_options", options),
        ),
    )

    context = query_review_context(  # type: ignore[arg-type]
        _Workflows(workflow),
        _Store(timeline, report, artifact_report, publication),
    )

    assert context.artifact == artifact
    assert context.artifact_report == artifact_report.ref
    assert context.artifact_evidence == artifact_report
    assert context.timeline == timeline.ref
    assert context.check_report == report.ref
    assert context.constraints == constraints
    assert context.publication_manifest == publication.ref
    assert context.fps_num == 30
    assert [(item.item_id, item.lane) for item in context.items] == [
        ("visual.000", "layer.0"),
        ("transition.fade.000", "transitions"),
        ("transition.fadeout.000", "transitions"),
    ]
