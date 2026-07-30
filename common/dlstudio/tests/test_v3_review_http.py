from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from dlstudio.application.api import start_workflow
from dlstudio.foundation.api import BlobRef
from dlstudio.persistence.api import open_local_repositories
from dlstudio.timeline.api import CheckReport, TimelineIR, VisualInstruction
from dlstudio.workflow.api import NamedRef, WorkflowStore


def _save_stage(
    workflows: WorkflowStore,
    stage: str,
    outputs: tuple[NamedRef, ...],
) -> None:
    current = workflows.read_current()
    assert current is not None
    running = current.start(  # type: ignore[arg-type]
        stage,
        (),
        contract=f"fixture.{stage}.v1",
    )
    workflows.save(
        running,
        expected_workflow_revision=current.revision,
        expected_head_revision=workflows.head_revision(),
    )
    completed = running.succeed(running.attempts[-1].operation_id, outputs)
    workflows.save(
        completed,
        expected_workflow_revision=running.revision,
        expected_head_revision=workflows.head_revision(),
    )


def _review_ready_production(root: Path) -> tuple[Path, BlobRef]:
    root.mkdir()
    (root / "edit.py").write_text("EDIT = None\n", encoding="utf-8")
    manifest = root / "production.toml"
    manifest.write_text(
        "\n".join(
            (
                'schema = "dlstudio.production"',
                "version = 3",
                'id = "fixture.reel"',
                'authoring = "edit.py"',
                'delivery_root = "delivery"',
                "",
            )
        ),
        encoding="utf-8",
    )
    repository, _, workflows = open_local_repositories(
        root,
        "fixture.reel",
    )
    store = repository.objects
    timeline = TimelineIR(
        production_id="fixture.reel",
        width=64,
        height=96,
        fps_num=30,
        fps_den=1,
        duration_ns=200_000_000,
        background="black",
        visuals=(
            VisualInstruction(
                "solid",
                0,
                200_000_000,
                0,
                0,
                0,
                64,
                96,
                color="black",
            ),
        ),
    )
    timeline_ref = store.put_bytes(timeline.canonical_bytes())
    policy_ref = store.put_bytes(b"policy")
    report = CheckReport(timeline_ref, policy_ref, ())
    report_ref = store.put_bytes(report.canonical_bytes())
    constraints_ref = store.put_bytes(b"constraints")
    artifact_ref = store.put_bytes(bytes(range(128)))

    start_workflow(workflows, run_id="run.main", kind="reel")
    _save_stage(
        workflows,
        "prepare",
        (
            NamedRef("timeline", timeline_ref),
            NamedRef("check_policy", policy_ref),
            NamedRef("check_report", report_ref),
            NamedRef("constraints", constraints_ref),
        ),
    )
    _save_stage(
        workflows,
        "draft",
        (NamedRef("artifact", store.put_bytes(b"draft")),),
    )
    _save_stage(
        workflows,
        "final",
        (
            NamedRef("artifact", artifact_ref),
            NamedRef("execution", store.put_bytes(b"execution")),
            NamedRef("render_options", store.put_bytes(b"options")),
        ),
    )
    return manifest, artifact_ref


def _changes_payload(
    *,
    context: dict[str, object],
    end_frame_exclusive: int,
    target_ids: list[str],
) -> dict[str, object]:
    return {
        "expected_artifact": context["artifact"],
        "expected_timeline": context["timeline"],
        "expected_check_report": context["check_report"],
        "expected_constraints": context["constraints"],
        "outcome": "changes_requested",
        "scope": ["visual", "audio", "constraints"],
        "reviewer": "author",
        "reviewed_at": "2026-07-30T00:00:00Z",
        "findings": [
            {
                "finding_id": "studio.ui.001",
                "text": "Move this element.",
                "requires_change": True,
                "locator": {
                    "start_frame": 5,
                    "end_frame_exclusive": end_frame_exclusive,
                    "region": {
                        "x_milli": 100,
                        "y_milli": 200,
                        "width_milli": 300,
                        "height_milli": 150,
                    },
                    "target_ids": target_ids,
                },
            }
        ],
    }


def test_review_http_validates_exact_frames_targets_and_survives_submission(
    tmp_path: Path,
) -> None:
    from dlstudio.adapters.http import create_app

    manifest, _ = _review_ready_production(tmp_path / "production")
    client = TestClient(create_app(manifest))

    context = client.get("/api/v3/review/context")
    assert context.status_code == 200
    context_payload = context.json()
    assert context_payload["items"][0]["item_id"] == "visual.000"

    beyond_end = client.post(
        "/api/v3/review",
        json=_changes_payload(
            context=context_payload,
            end_frame_exclusive=7,
            target_ids=["visual.000"],
        ),
    )
    assert beyond_end.status_code == 409

    unknown_target = client.post(
        "/api/v3/review",
        json=_changes_payload(
            context=context_payload,
            end_frame_exclusive=6,
            target_ids=["visual.999"],
        ),
    )
    assert unknown_target.status_code == 409

    stale_payload = _changes_payload(
        context=context_payload,
        end_frame_exclusive=6,
        target_ids=["visual.000"],
    )
    stale_payload["expected_artifact"] = {
        "sha256": "f" * 64,
        "size": context_payload["artifact"]["size"],
    }
    stale = client.post("/api/v3/review", json=stale_payload)
    assert stale.status_code == 409
    assert "review context changed" in stale.json()["detail"]

    accepted = client.post(
        "/api/v3/review",
        json=_changes_payload(
            context=context_payload,
            end_frame_exclusive=6,
            target_ids=["visual.000"],
        ),
    )
    assert accepted.status_code == 200
    assert accepted.json()["current_stage"] == "package"

    current = client.get("/api/v3/review/current")
    assert current.status_code == 200
    locator = current.json()["findings"][0]["locator"]
    assert locator["start_frame"] == 5
    assert locator["end_frame_exclusive"] == 6
    assert client.get("/api/v3/review/context").status_code == 200


def test_review_artifact_supports_range_and_rejects_stale_identity(
    tmp_path: Path,
) -> None:
    from dlstudio.adapters.http import create_app

    manifest, artifact = _review_ready_production(tmp_path / "production")
    client = TestClient(create_app(manifest))
    url = (
        f"/api/v3/review/artifacts/{artifact.sha256}"
        f"?size={artifact.size}"
    )

    partial = client.get(url, headers={"Range": "bytes=2-5"})
    assert partial.status_code == 206
    assert partial.headers["content-range"] == "bytes 2-5/128"
    assert partial.headers["content-type"].startswith("video/mp4")
    assert partial.content == bytes(range(2, 6))

    stale = client.get(
        f"/api/v3/review/artifacts/{'f' * 64}?size={artifact.size}"
    )
    assert stale.status_code == 409
