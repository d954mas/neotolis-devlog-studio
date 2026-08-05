from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

from dlstudio.application.api import start_workflow, submit_review
from dlstudio.foundation.api import BlobRef
from dlstudio.persistence.api import open_local_repositories
from dlstudio.rendering.api import ArtifactReport
from dlstudio.release.api import PublicationManifest, PublicationManifestFile
from dlstudio.review.api import (
    ReviewFinding,
    ReviewLocator,
    ReviewRegion,
    ReviewVerdict,
)
from dlstudio.timeline.api import CheckReport, TimelineIR, VisualInstruction
from dlstudio.workflow.api import NamedRef, WorkflowStore


SCENARIOS = (
    "exact",
    "compare",
    "stale",
    "mismatch",
    "legacy",
    "same",
    "responsive",
)


def _run_ffmpeg(
    target: Path,
    *,
    duration_seconds: float,
    fps: int,
    color: str,
    frequency: int,
) -> None:
    command = [
        "ffmpeg",
        "-hide_banner",
        "-loglevel",
        "error",
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={color}:s=180x320:r={fps}:d={duration_seconds}",
        "-f",
        "lavfi",
        "-i",
        f"sine=frequency={frequency}:sample_rate=48000:duration={duration_seconds}",
        "-shortest",
        "-c:v",
        "libx264",
        "-preset",
        "ultrafast",
        "-pix_fmt",
        "yuv420p",
        "-c:a",
        "aac",
        "-movflags",
        "+faststart",
        str(target),
    ]
    completed = subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
    )
    if completed.returncode:
        raise RuntimeError(
            f"ffmpeg fixture generation failed ({completed.returncode}): "
            f"{completed.stderr.strip()}"
        )


def _manifest(root: Path, production_id: str) -> Path:
    root.mkdir(parents=True)
    (root / "edit.py").write_text("EDIT = None\n", encoding="utf-8")
    manifest = root / "production.toml"
    manifest.write_text(
        "\n".join(
            (
                'schema = "dlstudio.production"',
                "version = 3",
                f'id = "{production_id}"',
                'authoring = "edit.py"',
                'delivery_root = "delivery"',
                "",
            )
        ),
        encoding="utf-8",
    )
    return manifest


def _timeline(
    *,
    production_id: str,
    fps: int,
    duration_ns: int,
    color: str,
    revision: str,
) -> TimelineIR:
    return TimelineIR(
        production_id=production_id,
        width=180,
        height=320,
        fps_num=fps,
        fps_den=1,
        duration_ns=duration_ns,
        background=color,
        visuals=(
            VisualInstruction(
                "solid",
                0,
                duration_ns,
                0,
                0,
                0,
                180,
                320,
                color=color,
            ),
        ),
        metadata={"fixture_revision": revision},
    )


def _prepare_outputs(
    store: object,
    timeline: TimelineIR,
    constraints: BlobRef,
) -> tuple[NamedRef, ...]:
    timeline_ref = store.put_bytes(timeline.canonical_bytes())  # type: ignore[attr-defined]
    policy_ref = store.put_bytes(b"e2e.check-policy.v1")  # type: ignore[attr-defined]
    report = CheckReport(timeline_ref, policy_ref, ())
    report_ref = store.put_bytes(report.canonical_bytes())  # type: ignore[attr-defined]
    cover_blob = store.put_bytes(b"e2e cover")  # type: ignore[attr-defined]
    cover_revision = store.put_bytes(b"e2e cover revision")  # type: ignore[attr-defined]
    metadata_blob = store.put_bytes(b"e2e metadata")  # type: ignore[attr-defined]
    metadata_revision = store.put_bytes(b"e2e metadata revision")  # type: ignore[attr-defined]
    publication_ref = store.put_bytes(  # type: ignore[attr-defined]
        PublicationManifest(
            timeline.production_id,
            (
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
            ),
        ).canonical_bytes()
    )
    return (
        NamedRef("timeline", timeline_ref),
        NamedRef("check_policy", policy_ref),
        NamedRef("check_report", report_ref),
        NamedRef("constraints", constraints),
        NamedRef("publication_manifest", publication_ref),
    )


def _save_stage(
    workflows: WorkflowStore,
    stage: str,
    outputs: tuple[NamedRef, ...],
    *,
    contract: str,
    inputs: tuple[NamedRef, ...] = (),
) -> None:
    current = workflows.read_current()
    if current is None:
        raise RuntimeError("fixture workflow was not started")
    running = current.start(stage, inputs, contract=contract)  # type: ignore[arg-type]
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


def _output_ref(outputs: tuple[NamedRef, ...], name: str) -> BlobRef:
    return next(item.blob for item in outputs if item.name == name)


def _previous_findings(*, same_media: bool) -> tuple[ReviewFinding, ...]:
    if same_media:
        return (
            ReviewFinding(
                "review.previous.same",
                "The same render still needs comparison.",
                True,
                ReviewLocator(
                    12,
                    16,
                    ReviewRegion(120, 180, 430, 260),
                    ("visual.000",),
                ),
            ),
        )
    return (
        ReviewFinding(
            "review.previous.edge",
            "The ending remains visible too long.",
            True,
            ReviewLocator(44, 48, None, ("visual.000",)),
        ),
        ReviewFinding(
            "review.previous.region",
            "Move the highlighted element away from the title.",
            True,
            ReviewLocator(
                4,
                8,
                ReviewRegion(100, 160, 360, 240),
                ("visual.000",),
            ),
        ),
    )


def _build_production(
    root: Path,
    *,
    scenario: str,
    old_media: Path,
    current_media: Path,
    same_media: bool,
) -> Path:
    production_id = f"fixture.{scenario}"
    manifest = _manifest(root, production_id)
    repository, _, workflows = open_local_repositories(root, production_id)
    store = repository.objects
    constraints = store.put_bytes(b"e2e.constraints.v1")
    old_artifact = store.ingest_file(old_media)
    selected_current_media = old_media if same_media else current_media
    current_artifact = store.ingest_file(selected_current_media)

    old_fps = 30 if same_media else 24
    old_duration_ns = 1_500_000_000 if same_media else 2_000_000_000
    current_fps = 30
    current_duration_ns = 1_500_000_000 if same_media else 1_000_000_000
    old_timeline = _timeline(
        production_id=production_id,
        fps=old_fps,
        duration_ns=old_duration_ns,
        color="#182b45",
        revision="old",
    )
    current_timeline = _timeline(
        production_id=production_id,
        fps=current_fps,
        duration_ns=current_duration_ns,
        color="#263b1d" if not same_media else "#182b45",
        revision="current",
    )
    old_prepare = _prepare_outputs(store, old_timeline, constraints)
    old_artifact_report = ArtifactReport(
        old_artifact,
        old_timeline.width,
        old_timeline.height,
        old_timeline.fps_num,
        old_timeline.fps_den,
        old_timeline.duration_ns,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    old_artifact_report_ref = store.put_bytes(
        old_artifact_report.canonical_bytes()
    )

    start_workflow(workflows, run_id="run.main", kind="reel")
    _save_stage(
        workflows,
        "prepare",
        old_prepare,
        contract="fixture.prepare.old.v1",
    )
    _save_stage(
        workflows,
        "draft",
        (NamedRef("artifact", store.put_bytes(b"draft.old")),),
        contract="fixture.draft.old.v1",
    )
    _save_stage(
        workflows,
        "final",
        (
            NamedRef("artifact", old_artifact),
            NamedRef("execution", store.put_bytes(b"execution.old")),
            NamedRef("render_options", store.put_bytes(b"options.old")),
            NamedRef("artifact_report", old_artifact_report_ref),
        ),
        contract="fixture.final.old.v1",
    )
    previous = ReviewVerdict(
        artifact=old_artifact,
        artifact_report=old_artifact_report_ref,
        publication_manifest=_output_ref(
            old_prepare, "publication_manifest"
        ),
        outcome="changes_requested",
        check_report=_output_ref(old_prepare, "check_report"),
        constraints=constraints,
        scope=("audio", "constraints", "visual", "publication"),
        reviewer="fixture.reviewer",
        reviewed_at="2026-07-30T00:00:00Z",
        findings=_previous_findings(same_media=same_media),
    )
    submit_review(workflows, previous)

    changed_source = store.put_bytes(f"source.{scenario}.current".encode())
    current_prepare = _prepare_outputs(store, current_timeline, constraints)
    current_artifact_report = ArtifactReport(
        current_artifact,
        current_timeline.width,
        current_timeline.height,
        current_timeline.fps_num,
        current_timeline.fps_den,
        current_timeline.duration_ns,
        None,
        None,
        None,
        None,
        None,
        None,
    )
    current_artifact_report_ref = store.put_bytes(
        current_artifact_report.canonical_bytes()
    )
    _save_stage(
        workflows,
        "prepare",
        current_prepare,
        contract="fixture.prepare.current.v1",
        inputs=(NamedRef("source", changed_source),),
    )
    _save_stage(
        workflows,
        "draft",
        (NamedRef("artifact", store.put_bytes(b"draft.current")),),
        contract="fixture.draft.current.v1",
    )
    _save_stage(
        workflows,
        "final",
        (
            NamedRef("artifact", current_artifact),
            NamedRef("execution", store.put_bytes(b"execution.current")),
            NamedRef("render_options", store.put_bytes(b"options.current")),
            NamedRef(
                "artifact_report",
                current_artifact_report_ref,
            ),
        ),
        contract="fixture.final.current.v1",
    )
    return manifest


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    args = parser.parse_args()
    root = args.root.resolve()
    root.mkdir(parents=True, exist_ok=False)
    media_root = root / "media"
    media_root.mkdir()
    old_media = media_root / "old.mp4"
    current_media = media_root / "current.mp4"
    same_media = media_root / "same.mp4"
    _run_ffmpeg(
        old_media,
        duration_seconds=2,
        fps=24,
        color="0x182b45",
        frequency=440,
    )
    _run_ffmpeg(
        current_media,
        duration_seconds=1,
        fps=30,
        color="0x263b1d",
        frequency=660,
    )
    _run_ffmpeg(
        same_media,
        duration_seconds=1.5,
        fps=30,
        color="0x182b45",
        frequency=550,
    )

    manifests: dict[str, str] = {}
    for scenario in SCENARIOS:
        manifest = _build_production(
            root / scenario,
            scenario=scenario,
            old_media=same_media if scenario == "same" else old_media,
            current_media=current_media,
            same_media=scenario == "same",
        )
        manifests[scenario] = str(manifest)
    print(json.dumps(manifests, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
