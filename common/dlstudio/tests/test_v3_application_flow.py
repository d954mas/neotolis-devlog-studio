from __future__ import annotations

import math
import struct
import wave
from collections.abc import Callable
from pathlib import Path

import pytest

from dlstudio.adapters.providers import FfprobeMediaInspector
from dlstudio.application.api import (
    IngestAssetCommand,
    advance_production,
    deliver_local,
    ingest_asset,
    start_workflow,
    submit_review,
)
from dlstudio.assets.api import Approval, License, Provenance
from dlstudio.foundation.api import BlobRef
from dlstudio.persistence.api import ObjectStore, open_local_repositories
from dlstudio.persistence.assets import AssetRepository
from dlstudio.rendering.api import ExecutionFingerprint
from dlstudio.review.api import ReviewVerdict
from dlstudio.workflow.api import StageId, WorkflowKind, WorkflowRun


def _outputs(workflow: WorkflowRun, stage: StageId) -> dict[str, BlobRef]:
    attempt = next(item for item in workflow.attempts if item.stage == stage)
    return {item.name: item.blob for item in attempt.outputs}


def _release(
    production: Path,
    *,
    production_id: str,
    kind: WorkflowKind,
    authoring_source: str,
    seed: Callable[[ObjectStore, AssetRepository], None] | None = None,
) -> None:
    production.mkdir()
    authoring = production / "edit.py"
    authoring.write_text(authoring_source, encoding="utf-8")
    repository, assets, workflows = open_local_repositories(
        production, production_id
    )
    if seed is not None:
        seed(repository.objects, assets)
    start_workflow(workflows, run_id="run.main", kind=kind)
    arguments = {
        "authoring_path": authoring,
        "output_root": production / "data" / ".studio" / "outputs",
        "cache_root": production / "data" / ".studio" / "cache",
        "fingerprint": ExecutionFingerprint.detect(),
    }

    for expected in ("draft", "final", "review"):
        workflow = advance_production(
            workflows, assets, repository.objects, **arguments
        )
        assert workflow.current_stage == expected

    prepared = _outputs(workflow, "prepare")
    finalized = _outputs(workflow, "final")
    workflow = submit_review(
        workflows,
        ReviewVerdict(
            artifact=finalized["artifact"],
            outcome="pass",
            check_report=prepared["check_report"],
            constraints=prepared["constraints"],
            scope=("audio", "constraints", "visual"),
            reviewer="video.reviewer",
            reviewed_at="2026-07-27T00:00:00Z",
        ),
    )
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


@pytest.mark.parametrize(
    ("kind", "edit_kind", "width", "height"),
    (
        ("reel", "reel", 64, 96),
        ("longform", "devlog", 96, 64),
    ),
)
def test_representative_visual_release(
    tmp_path: Path,
    kind: WorkflowKind,
    edit_kind: str,
    width: int,
    height: int,
) -> None:
    _release(
        tmp_path / kind,
        production_id=f"fixture.{kind}",
        kind=kind,
        authoring_source="\n".join(
            (
                "from dlstudio.authoring.api import Edit, SolidLayer",
                "EDIT = Edit(",
                f"    production_id='fixture.{kind}',",
                f"    width={width}, height={height}, fps_num=30, fps_den=1,",
                "    duration_ns=200_000_000, background='black',",
                f"    visuals=(SolidLayer(0, 200_000_000, 0, 0, 0, {width}, {height}, 'black'),),",
                "    standalone_story='A complete synthetic release.',",
                f"    kind='{edit_kind}',",
                ")",
                "",
            )
        ),
    )


def test_representative_capture_vo_release(tmp_path: Path) -> None:
    production = tmp_path / "capture"
    audio_path = production / "voice.wav"

    def seed(store: ObjectStore, assets: AssetRepository) -> None:
        with wave.open(str(audio_path), "wb") as output:
            output.setnchannels(1)
            output.setsampwidth(2)
            output.setframerate(48_000)
            output.writeframes(
                b"".join(
                    struct.pack(
                        "<h",
                        round(2_000 * math.sin(2 * math.pi * 440 * index / 48_000)),
                    )
                    for index in range(9_600)
                )
            )
        script = store.put_bytes(b"exact capture VO script")
        receipt = store.put_bytes(b"verified recorder receipt")
        approval = store.put_bytes(b"machine capture audit passed")
        license_proof = store.put_bytes(b"creator owns this recording")
        ingest_asset(
            assets,
            IngestAssetCommand(
                source=audio_path,
                asset_id="voice.main",
                provenance=Provenance(
                    origin="recorded",
                    capture_method="voice_take",
                    state_id="take.main",
                    script_ref=script,
                    provider_receipt_ref=receipt,
                ),
                approval=Approval("approved", (approval,)),
                license=License(
                    "creator-owned",
                    False,
                    evidence_ref=license_proof,
                ),
                expected_revision=0,
            ),
            inspect_media=FfprobeMediaInspector(),
        )

    _release(
        production,
        production_id="fixture.capture",
        kind="capture_vo",
        seed=seed,
        authoring_source="\n".join(
            (
                "from dlstudio.authoring.api import AudioClip, Edit, SolidLayer",
                "EDIT = Edit(",
                "    production_id='fixture.capture',",
                "    width=96, height=64, fps_num=30, fps_den=1,",
                "    duration_ns=200_000_000, background='black',",
                "    visuals=(SolidLayer(0, 200_000_000, 0, 0, 0, 96, 64, 'black'),),",
                "    audio=(AudioClip('voice.main', 0, 200_000_000),),",
                "    standalone_story='A verified capture and voice release.',",
                "    kind='capture_vo',",
                ")",
                "",
            )
        ),
    )
