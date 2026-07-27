from __future__ import annotations

from pathlib import Path

from dlstudio.application.api import (
    advance_production,
    deliver_local,
    start_workflow,
    submit_review,
)
from dlstudio.foundation.api import BlobRef
from dlstudio.persistence.api import open_local_repositories
from dlstudio.rendering.api import ExecutionFingerprint
from dlstudio.review.api import ReviewVerdict
from dlstudio.workflow.api import StageId, WorkflowRun


def _outputs(workflow: WorkflowRun, stage: StageId) -> dict[str, BlobRef]:
    attempt = next(item for item in workflow.attempts if item.stage == stage)
    return {item.name: item.blob for item in attempt.outputs}


def test_real_application_flow_reaches_exact_delivery(tmp_path: Path) -> None:
    production = tmp_path / "production"
    production.mkdir()
    authoring = production / "edit.py"
    authoring.write_text(
        "\n".join(
            (
                "from dlstudio.authoring.api import Edit, SolidLayer",
                "EDIT = Edit(",
                "    production_id='fixture.reel',",
                "    width=64, height=96, fps_num=30, fps_den=1,",
                "    duration_ns=200_000_000, background='black',",
                "    visuals=(SolidLayer(0, 200_000_000, 0, 0, 0, 64, 96, 'black'),),",
                "    standalone_story='A complete synthetic release.',",
                ")",
                "",
            )
        ),
        encoding="utf-8",
    )
    repository, assets, workflows = open_local_repositories(
        production, "fixture.reel"
    )
    start_workflow(workflows, run_id="run.main", kind="reel")
    fingerprint = ExecutionFingerprint.detect()
    arguments = {
        "authoring_path": authoring,
        "output_root": production / "data" / ".studio" / "outputs",
        "cache_root": production / "data" / ".studio" / "cache",
        "fingerprint": fingerprint,
    }

    for expected in ("draft", "final", "review"):
        workflow = advance_production(
            workflows, assets, repository.objects, **arguments
        )
        assert workflow.current_stage == expected

    prepared = _outputs(workflow, "prepare")
    finalized = _outputs(workflow, "final")
    verdict = ReviewVerdict(
        artifact=finalized["artifact"],  # type: ignore[arg-type]
        outcome="pass",
        check_report=prepared["check_report"],  # type: ignore[arg-type]
        constraints=prepared["constraints"],  # type: ignore[arg-type]
        scope=("audio", "constraints", "visual"),
        reviewer="video.reviewer",
        reviewed_at="2026-07-27T00:00:00Z",
    )
    workflow = submit_review(workflows, verdict)
    assert workflow.current_stage == "package"
    workflow = advance_production(
        workflows, assets, repository.objects, **arguments
    )
    assert workflow.current_stage == "deliver"

    destination = production / "delivery"
    completed, receipt = deliver_local(
        workflows,
        destination,
        destination_id="local.delivery",
        delivered_at="2026-07-27T00:00:01Z",
    )
    assert completed.completed
    assert receipt.candidate_id == workflow.eligible_candidate.sha256  # type: ignore[union-attr]
    assert (destination / "video.mp4").stat().st_size > 0
    assert (destination / "licenses.json").is_file()
