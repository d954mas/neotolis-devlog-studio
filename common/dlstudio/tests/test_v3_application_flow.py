from __future__ import annotations

import math
import shutil
import struct
import subprocess
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
    submit_review,
)
from dlstudio.assets.api import Approval, License, MediaFacts, Provenance
from dlstudio.authoring.api import load_edit
from dlstudio.foundation.api import BlobRef
from dlstudio.persistence.api import ObjectStore, open_local_repositories
from dlstudio.persistence.assets import AssetRepository
from dlstudio.rendering.api import (
    ExecutionFingerprint,
    RenderResult,
    execution_key,
)
from dlstudio.review.api import ReviewVerdict
from dlstudio.workflow.api import StageId, WorkflowKind, WorkflowRun


def _outputs(workflow: WorkflowRun, stage: StageId) -> dict[str, BlobRef]:
    attempt = next(item for item in workflow.attempts if item.stage == stage)
    return {item.name: item.blob for item in attempt.outputs}


def test_explicit_authoring_loads_dataclasses_with_postponed_annotations(
    tmp_path: Path,
) -> None:
    source = tmp_path / "edit.py"
    source.write_text(
        "\n".join(
            (
                "from __future__ import annotations",
                "from dataclasses import dataclass",
                "from dlstudio.authoring.api import Edit, SolidLayer",
                "@dataclass",
                "class Note:",
                "    text: str",
                "NOTE = Note('valid')",
                "EDIT = Edit(",
                "    production_id='fixture.loader',",
                "    width=64, height=96, fps_num=30, fps_den=1,",
                "    duration_ns=200_000_000, background='black',",
                "    visuals=(SolidLayer(0, 200_000_000, 0, 0, 0, 64, 96, 'black'),),",
                "    standalone_story='A valid explicit authoring file.',",
                ")",
                "",
            )
        ),
        encoding="utf-8",
    )

    assert load_edit(source).production_id == "fixture.loader"


def test_blocking_checks_fail_prepare_before_render(tmp_path: Path) -> None:
    production = tmp_path / "production"
    production.mkdir()
    authoring = production / "edit.py"
    authoring.write_text(
        "\n".join(
            (
                "from dlstudio.authoring.api import Edit, SolidLayer",
                "EDIT = Edit(",
                "    production_id='fixture.wrong_orientation',",
                "    width=96, height=64, fps_num=30, fps_den=1,",
                "    duration_ns=200_000_000, background='black',",
                "    visuals=(SolidLayer(0, 200_000_000, 0, 0, 0, 96, 64, 'black'),),",
                "    standalone_story='A landscape file declared as a reel.',",
                "    kind='reel',",
                ")",
                "",
            )
        ),
        encoding="utf-8",
    )
    repository, assets, workflows = open_local_repositories(
        production, "fixture.wrong_orientation"
    )

    with pytest.raises(ValueError, match="pre-render checks failed"):
        advance_production(
            workflows,
            assets,
            repository.objects,
            authoring_path=authoring,
            output_root=production / "outputs",
        )

    current = workflows.read_current()
    assert current is not None
    assert current.current_stage == "prepare"
    assert current.attempts[0].state == "failed"
    assert not (production / "outputs").exists()


def test_voice_script_without_voice_clip_fails_prepare_before_render(
    tmp_path: Path,
) -> None:
    production = tmp_path / "production"
    production.mkdir()
    authoring = production / "edit.py"
    authoring.write_text(
        "\n".join(
            (
                "from dlstudio.authoring.api import Edit, SolidLayer",
                "EDIT = Edit(",
                "    production_id='fixture.voice_required',",
                "    width=64, height=96, fps_num=30, fps_den=1,",
                "    duration_ns=200_000_000, background='black',",
                "    visuals=(SolidLayer(0, 200_000_000, 0, 0, 0, 64, 96, 'black'),),",
                "    standalone_story='A narrated reel must name its voice layer.',",
                "    voice_script='This narration must be present in the timeline.',",
                "    kind='reel',",
                ")",
                "",
            )
        ),
        encoding="utf-8",
    )
    repository, assets, workflows = open_local_repositories(
        production, "fixture.voice_required"
    )

    with pytest.raises(ValueError, match="audio[.]voice[.]required"):
        advance_production(
            workflows,
            assets,
            repository.objects,
            authoring_path=authoring,
            output_root=production / "outputs",
        )

    current = workflows.read_current()
    assert current is not None
    assert current.current_stage == "prepare"
    assert current.attempts[0].state == "failed"
    assert not (production / "outputs").exists()


def test_voice_script_with_voice_clip_passes_prepare(tmp_path: Path) -> None:
    production = tmp_path / "production"
    production.mkdir()
    authoring = production / "edit.py"
    authoring.write_text(
        "\n".join(
            (
                "from dlstudio.authoring.api import AudioClip, Edit, SolidLayer",
                "EDIT = Edit(",
                "    production_id='fixture.voice_present',",
                "    width=64, height=96, fps_num=30, fps_den=1,",
                "    duration_ns=200_000_000, background='black',",
                "    visuals=(SolidLayer(0, 200_000_000, 0, 0, 0, 64, 96, 'black'),),",
                "    audio=(AudioClip('voice.main', 0, 200_000_000, role='voice'),),",
                "    standalone_story='A narrated reel names its exact voice layer.',",
                "    voice_script='This narration is present in the timeline.',",
                "    kind='reel',",
                ")",
                "",
            )
        ),
        encoding="utf-8",
    )
    repository, assets, workflows = open_local_repositories(
        production, "fixture.voice_present"
    )
    voice = production / "voice.bin"
    voice.write_bytes(b"fixture voice bytes")
    approval_evidence = repository.objects.put_bytes(b"voice approved")
    license_evidence = repository.objects.put_bytes(b"creator owns voice")
    ingest_asset(
        assets,
        IngestAssetCommand(
            source=voice,
            asset_id="voice.main",
            provenance=Provenance("provided", "test_fixture"),
            approval=Approval("approved", (approval_evidence,)),
            license=License(
                "creator-owned",
                False,
                evidence_ref=license_evidence,
            ),
            expected_revision=0,
        ),
        inspect_media=lambda _path: MediaFacts(
            kind="audio",
            format_name="fixture",
            duration_ns=200_000_000,
            sample_rate=48_000,
            channels=1,
        ),
    )

    current = advance_production(
        workflows,
        assets,
        repository.objects,
        authoring_path=authoring,
        output_root=production / "outputs",
    )

    assert current.current_stage == "draft"
    assert current.attempts[0].state == "succeeded"
    assert not (production / "outputs").exists()


def test_voice_required_silent_final_fails_before_review(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    production = tmp_path / "production"
    production.mkdir()
    authoring = production / "edit.py"
    authoring.write_text(
        "\n".join(
            (
                "from dlstudio.authoring.api import AudioClip, Edit, SolidLayer",
                "EDIT = Edit(",
                "    production_id='fixture.silent_final',",
                "    width=64, height=96, fps_num=30, fps_den=1,",
                "    duration_ns=200_000_000, background='black',",
                "    visuals=(SolidLayer(0, 200_000_000, 0, 0, 0, 64, 96, 'black'),),",
                "    audio=(AudioClip('voice.silent', 0, 200_000_000, role='voice'),),",
                "    standalone_story='A silent final must never reach review.',",
                "    voice_script='This expected narration is digitally silent.',",
                "    kind='reel',",
                ")",
                "",
            )
        ),
        encoding="utf-8",
    )
    repository, assets, workflows = open_local_repositories(
        production, "fixture.silent_final"
    )
    voice = production / "silent.wav"
    with wave.open(str(voice), "wb") as handle:
        handle.setnchannels(1)
        handle.setsampwidth(2)
        handle.setframerate(48_000)
        handle.writeframes(b"\x00\x00" * 9_600)
    approval_evidence = repository.objects.put_bytes(b"silent take approved")
    license_evidence = repository.objects.put_bytes(b"creator owns silent take")
    ingest_asset(
        assets,
        IngestAssetCommand(
            source=voice,
            asset_id="voice.silent",
            provenance=Provenance("provided", "test_fixture"),
            approval=Approval("approved", (approval_evidence,)),
            license=License(
                "creator-owned",
                False,
                evidence_ref=license_evidence,
            ),
            expected_revision=0,
        ),
        inspect_media=FfprobeMediaInspector(),
    )
    silent_final = production / "silent-final.mp4"
    subprocess.run(
        [
            "ffmpeg",
            "-v",
            "error",
            "-f",
            "lavfi",
            "-i",
            "color=c=black:s=64x96:r=30:d=0.2",
            "-f",
            "lavfi",
            "-i",
            "anullsrc=r=48000:cl=stereo:d=0.2",
            "-shortest",
            "-c:v",
            "libx264",
            "-pix_fmt",
            "yuv420p",
            "-c:a",
            "aac",
            "-y",
            str(silent_final),
        ],
        check=True,
    )
    silent_ref = repository.objects.ingest_file(silent_final)

    def render_silent(
        timeline,
        fingerprint,
        options,
        _resolver,
        *,
        output: Path,
        cache_root: Path | None = None,
    ) -> RenderResult:
        del cache_root
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(silent_final, output)
        return RenderResult(
            silent_ref,
            output,
            execution_key(timeline, fingerprint, options),
            False,
            (),
        )

    from dlstudio.application import production as production_module

    monkeypatch.setattr(production_module, "render_timeline", render_silent)
    arguments = {
        "authoring_path": authoring,
        "output_root": production / "outputs",
        "cache_root": production / "cache",
        "fingerprint": ExecutionFingerprint.detect(),
    }
    assert advance_production(
        workflows, assets, repository.objects, **arguments
    ).current_stage == "draft"
    assert advance_production(
        workflows, assets, repository.objects, **arguments
    ).current_stage == "final"

    with pytest.raises(ValueError, match="audio[.]voice[.]silent"):
        advance_production(
            workflows,
            assets,
            repository.objects,
            **arguments,
        )

    current = workflows.read_current()
    assert current is not None
    assert current.current_stage == "final"
    assert current.attempts[-1].state == "failed"


def test_edit_without_voice_script_can_prepare_without_voice_clip(
    tmp_path: Path,
) -> None:
    production = tmp_path / "production"
    production.mkdir()
    authoring = production / "edit.py"
    authoring.write_text(
        "\n".join(
            (
                "from dlstudio.authoring.api import Edit, SolidLayer",
                "EDIT = Edit(",
                "    production_id='fixture.intentional_silence',",
                "    width=64, height=96, fps_num=30, fps_den=1,",
                "    duration_ns=200_000_000, background='black',",
                "    visuals=(SolidLayer(0, 200_000_000, 0, 0, 0, 64, 96, 'black'),),",
                "    standalone_story='This reel is intentionally silent.',",
                "    kind='reel',",
                ")",
                "",
            )
        ),
        encoding="utf-8",
    )
    repository, assets, workflows = open_local_repositories(
        production, "fixture.intentional_silence"
    )

    current = advance_production(
        workflows,
        assets,
        repository.objects,
        authoring_path=authoring,
        output_root=production / "outputs",
    )

    assert current.current_stage == "draft"
    assert current.attempts[0].state == "succeeded"
    assert not (production / "outputs").exists()


def test_authoring_identity_mismatch_leaves_production_untouched(
    tmp_path: Path,
) -> None:
    production = tmp_path / "production"
    production.mkdir()
    authoring = production / "edit.py"
    authoring.write_text(
        "\n".join(
            (
                "from dlstudio.authoring.api import Edit",
                "EDIT = Edit(",
                "    production_id='fixture.other',",
                "    width=64, height=96, fps_num=30, fps_den=1,",
                "    duration_ns=200_000_000, background='black',",
                "    standalone_story='This belongs elsewhere.',",
                ")",
                "",
            )
        ),
        encoding="utf-8",
    )
    repository, assets, workflows = open_local_repositories(
        production, "fixture.expected"
    )

    with pytest.raises(ValueError, match="another production"):
        advance_production(
            workflows,
            assets,
            repository.objects,
            authoring_path=authoring,
            output_root=production / "outputs",
        )

    assert workflows.read_current() is None
    assert not (production / "outputs").exists()


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
            artifact_report=finalized["artifact_report"],
            publication_manifest=prepared["publication_manifest"],
            outcome="pass",
            check_report=prepared["check_report"],
            constraints=prepared["constraints"],
            scope=("audio", "constraints", "visual", "publication"),
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
        expected_candidate=workflow.eligible_candidate,  # type: ignore[arg-type]
        delivered_at="2026-07-27T00:00:01Z",
    )
    assert completed.completed
    assert receipt.candidate_id == workflow.eligible_candidate.sha256  # type: ignore[union-attr]
    assert (destination / "video.mp4").stat().st_size > 0
    assert (destination / "licenses.json").is_file()


def _seed_publication_assets(
    root: Path,
    store: ObjectStore,
    assets: AssetRepository,
) -> None:
    for expected_revision, (asset_id, filename, raw, media) in enumerate((
        (
            "publish.cover.main",
            "cover.png",
            b"fixture cover",
            MediaFacts("image", "png", width=64, height=96),
        ),
        (
            "publish.metadata.main",
            "metadata.md",
            b"# Fixture metadata",
            MediaFacts("data", "markdown"),
        ),
    )):
        source = root / filename
        source.write_bytes(raw)
        ingest_asset(
            assets,
            IngestAssetCommand(
                source=source,
                asset_id=asset_id,
                provenance=Provenance("provided", "release_fixture"),
                approval=Approval(
                    "approved",
                    (store.put_bytes(f"approved:{asset_id}".encode()),),
                ),
                license=License("owned", False),
                expected_revision=expected_revision,
            ),
            inspect_media=lambda _path, value=media: value,
        )


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
                (
                    "from dlstudio.authoring.api import "
                    "Edit, PublicationFile, SolidLayer"
                ),
                "EDIT = Edit(",
                f"    production_id='fixture.{kind}',",
                f"    width={width}, height={height}, fps_num=30, fps_den=1,",
                "    duration_ns=200_000_000, background='black',",
                f"    visuals=(SolidLayer(0, 200_000_000, 0, 0, 0, {width}, {height}, 'black'),),",
                "    standalone_story='A complete synthetic release.',",
                "    publication=(",
                "        PublicationFile('cover', 'cover.png', 'publish.cover.main'),",
                "        PublicationFile('metadata', 'metadata.md', 'publish.metadata.main'),",
                "    ),",
                f"    kind='{edit_kind}',",
                ")",
                "",
            )
        ),
        seed=lambda store, assets: _seed_publication_assets(
            tmp_path / kind,
            store,
            assets,
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
