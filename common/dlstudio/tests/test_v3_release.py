from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from dlstudio.application.api import (
    start_workflow,
    submit_review,
)
from dlstudio.application.workflow import _advance, _package_release
from dlstudio.application.release import build_release_gate, freeze_release
from dlstudio.assets.api import (
    Approval,
    AssetRevision,
    License,
    MediaFacts,
    Provenance,
)
from dlstudio.authoring.api import Edit, SolidLayer, _compile_resolved
from dlstudio.constraints.api import Constraint, ConstraintSet
from dlstudio.foundation.api import BlobRef, CanonicalEncodingError
from dlstudio.persistence import WorkflowRepository
from dlstudio.persistence.api import ProductionRepository
from dlstudio.release.api import (
    DeliveryReceipt,
    PackageFile,
    PublicationManifest,
    PublicationManifestFile,
    ReleaseCandidate,
)
from dlstudio.rendering.api import (
    ArtifactReport,
    ExecutionFingerprint,
    RenderOptions,
    RenderResult,
    execution_key,
)
from dlstudio.review.api import ReviewVerdict
from dlstudio.timeline.api import CheckPolicy, check_timeline
from dlstudio.workflow.api import NamedRef


def _blob(value: str, size: int = 10) -> BlobRef:
    return BlobRef(value * 64, size)


def _candidate() -> ReleaseCandidate:
    final = _blob("3", 100)
    return ReleaseCandidate(
        production_id="fixture.reel",
        timeline=_blob("1"),
        check_policy=_blob("b"),
        execution=_blob("2"),
        render_options=_blob("c"),
        execution_key="d" * 64,
        final_output=final,
        artifact_report=_blob("e"),
        publication_manifest=_blob("f"),
        check_report=_blob("4"),
        review_verdict=_blob("5"),
        constraints=_blob("6"),
        asset_revisions=(_blob("7"), _blob("8")),
        license_bundle=_blob("9"),
        package=(
            PackageFile("video.mp4", final),
            PackageFile("licenses.json", _blob("9")),
            PackageFile("youtube/metadata.md", _blob("a")),
        ),
    )


def test_release_candidate_freezes_complete_exact_closure() -> None:
    candidate = _candidate()
    assert ReleaseCandidate.from_canonical_bytes(
        candidate.canonical_bytes()
    ) == candidate
    assert candidate.ref.sha256 == candidate.candidate_id
    assert candidate.final_output in candidate.reachable_blobs
    assert len(candidate.reachable_blobs) == 14


def test_package_rejects_paths_and_arbitrary_final_output() -> None:
    with pytest.raises(CanonicalEncodingError, match="unsafe logical path"):
        PackageFile("../outside.mp4", _blob("1"))
    candidate = _candidate()
    with pytest.raises(ValueError, match="exact final"):
        ReleaseCandidate(
            production_id=candidate.production_id,
            timeline=candidate.timeline,
            check_policy=candidate.check_policy,
            execution=candidate.execution,
            render_options=candidate.render_options,
            execution_key=candidate.execution_key,
            final_output=_blob("f"),
            artifact_report=candidate.artifact_report,
            publication_manifest=candidate.publication_manifest,
            check_report=candidate.check_report,
            review_verdict=candidate.review_verdict,
            constraints=candidate.constraints,
            asset_revisions=candidate.asset_revisions,
            license_bundle=candidate.license_bundle,
            package=candidate.package,
        )


def test_receipt_names_exact_candidate_and_copied_manifest() -> None:
    candidate = _candidate()
    receipt = DeliveryReceipt(
        candidate.candidate_id,
        "local.archive",
        "2026-07-27T00:00:00Z",
        candidate.package,
    )
    assert len(receipt.receipt_id) == 64
    assert receipt.manifest == candidate.package


def _release_inputs(
    tmp_path: Path,
    repository: ProductionRepository | None = None,
) -> dict[str, object]:
    repository = repository or ProductionRepository(
            object_root=tmp_path / "objects",
            state_root=tmp_path / "state",
            staging_root=tmp_path / "staging",
            lock_root=tmp_path / "locks",
            production_id="fixture.reel",
        )
    timeline = _compile_resolved(
        Edit(
            production_id="fixture.reel",
            width=1080,
            height=1920,
            fps_num=30,
            fps_den=1,
            duration_ns=1_000_000_000,
            background="black",
            visuals=(
                SolidLayer(
                    0, 1_000_000_000, 0, 0, 0, 1080, 1920, "black"
                ),
            ),
            standalone_story="A complete standalone fixture.",
        )
    )
    constraints, policy = build_release_gate(
        "fixture.reel",
        "vertical",
        require_voice=False,
        kind="reel",
    )
    report = check_timeline(timeline, policy)
    fingerprint = ExecutionFingerprint(
        "ffmpeg",
        "fixture",
        "1" * 64,
        "2" * 64,
        "3" * 64,
        "CPython-fixture",
    )
    options = RenderOptions()
    final = repository.objects.put_bytes(b"final video")
    rendered = RenderResult(
        final,
        tmp_path / "final.mp4",
        execution_key(timeline, fingerprint, options),
        False,
        (),
    )
    artifact_report = ArtifactReport(
        artifact=final,
        width=timeline.width,
        height=timeline.height,
        fps_num=timeline.fps_num,
        fps_den=timeline.fps_den,
        duration_ns=timeline.duration_ns,
        audio_codec=None,
        audio_sample_rate=None,
        audio_channels=None,
        integrated_lufs_milli=None,
        true_peak_db_milli=None,
        active_audio_ratio_milli=None,
    )
    cover_blob = repository.objects.put_bytes(b"cover")
    cover = AssetRevision(
        "publish.cover.main",
        cover_blob,
        MediaFacts("image", "png", width=1080, height=1920),
        Provenance("provided", "release_fixture"),
        Approval(
            "approved",
            (repository.objects.put_bytes(b"cover approval"),),
        ),
        License("owned", False),
    )
    metadata_blob = repository.objects.put_bytes(b"metadata")
    metadata = AssetRevision(
        "publish.metadata.main",
        metadata_blob,
        MediaFacts("data", "markdown"),
        Provenance("provided", "release_fixture"),
        Approval(
            "approved",
            (repository.objects.put_bytes(b"metadata approval"),),
        ),
        License("owned", False),
    )
    for revision in (cover, metadata):
        assert repository.objects.put_bytes(
            revision.canonical_bytes()
        ) == revision.ref.object
    publication = PublicationManifest(
        "fixture.reel",
        (
            PublicationManifestFile(
                "cover",
                "cover.png",
                cover.asset_id,
                cover.ref.object,
                cover.blob,
            ),
            PublicationManifestFile(
                "metadata",
                "metadata.md",
                metadata.asset_id,
                metadata.ref.object,
                metadata.blob,
            ),
        ),
    )
    repository.objects.put_bytes(publication.canonical_bytes())
    verdict = ReviewVerdict(
        artifact=final,
        artifact_report=artifact_report.ref,
        publication_manifest=publication.ref,
        outcome="pass",
        check_report=report.ref,
        constraints=constraints.ref,
        scope=("audio", "visual", "constraints", "publication"),
        reviewer="video.reviewer",
        reviewed_at="2026-07-27T00:00:00Z",
    )
    return {
        "store": repository.objects,
        "production_id": repository.production_id,
        "kind": "reel",
        "timeline": timeline,
        "policy": policy,
        "report": report,
        "artifact_report": artifact_report,
        "publication": publication,
        "fingerprint": fingerprint,
        "options": options,
        "render": rendered,
        "constraints": constraints,
        "verdict": verdict,
        "package": (PackageFile("video.mp4", final),),
    }


def test_release_gate_binds_voice_requirement_to_policy_and_constraints() -> None:
    constraints, policy = build_release_gate(
        "fixture.reel",
        "vertical",
        require_voice=True,
        kind="reel",
    )

    assert policy.require_voice
    assert policy.constraints == constraints.ref
    assert "audio.voice.required" in {
        item.constraint_id for item in constraints.constraints
    }


def test_reel_release_gate_requires_cover_and_metadata() -> None:
    constraints, _ = build_release_gate(
        "fixture.reel",
        "vertical",
        require_voice=False,
        kind="reel",
    )

    assert {"package.cover.required", "package.metadata.required"}.issubset(
        {item.constraint_id for item in constraints.constraints}
    )


def test_release_gate_requires_an_explicit_voice_choice() -> None:
    with pytest.raises(TypeError, match="require_voice"):
        build_release_gate("fixture.reel", "vertical")


def test_freeze_release_validates_and_publishes_exact_chain(
    tmp_path: Path,
) -> None:
    values = _release_inputs(tmp_path)
    candidate, candidate_ref = freeze_release(**values)  # type: ignore[arg-type]
    store = values["store"]
    assert candidate_ref == candidate.ref
    assert candidate.check_report == values["report"].ref  # type: ignore[union-attr]
    assert candidate.artifact_report == values["artifact_report"].ref  # type: ignore[union-attr]
    assert candidate.publication_manifest == values["publication"].ref  # type: ignore[union-attr]
    assert candidate.constraints == values["constraints"].ref  # type: ignore[union-attr]
    assert {item.path for item in candidate.package} == {
        "video.mp4",
        "cover.png",
        "metadata.md",
        "licenses.json",
    }
    publication = values["publication"]
    assert isinstance(publication, PublicationManifest)
    package = {item.path: item.blob for item in candidate.package}
    assert all(package[item.path] == item.blob for item in publication.files)
    assert {item.revision for item in publication.files}.issubset(
        candidate.asset_revisions
    )
    store.verify(candidate_ref)  # type: ignore[union-attr]


def test_freeze_release_rejects_report_from_another_artifact(
    tmp_path: Path,
) -> None:
    values = _release_inputs(tmp_path)
    report = values["artifact_report"]
    assert isinstance(report, ArtifactReport)
    values["artifact_report"] = replace(
        report,
        artifact=values["store"].put_bytes(b"another final"),  # type: ignore[union-attr]
    )

    with pytest.raises(ValueError, match="exact final artifact"):
        freeze_release(**values)  # type: ignore[arg-type]


def test_freeze_release_rejects_missing_required_publication_role(
    tmp_path: Path,
) -> None:
    values = _release_inputs(tmp_path)
    publication = values["publication"]
    verdict = values["verdict"]
    assert isinstance(publication, PublicationManifest)
    assert isinstance(verdict, ReviewVerdict)
    incomplete = PublicationManifest(
        publication.production_id,
        tuple(item for item in publication.files if item.role != "cover"),
    )
    values["publication"] = incomplete
    values["verdict"] = replace(
        verdict,
        publication_manifest=incomplete.ref,
    )

    with pytest.raises(ValueError, match="requires cover and metadata"):
        freeze_release(**values)  # type: ignore[arg-type]


@pytest.mark.parametrize(
    ("change", "message"),
    (
        ("pending", "not approved"),
        ("non_redistributable", "not redistributable"),
    ),
)
def test_freeze_release_rejects_untrusted_publication_revision(
    tmp_path: Path,
    change: str,
    message: str,
) -> None:
    values = _release_inputs(tmp_path)
    publication = values["publication"]
    verdict = values["verdict"]
    store = values["store"]
    assert isinstance(publication, PublicationManifest)
    assert isinstance(verdict, ReviewVerdict)
    metadata_file = next(
        item for item in publication.files if item.role == "metadata"
    )
    revision = AssetRevision.from_canonical_bytes(
        store.read(metadata_file.revision)  # type: ignore[union-attr]
    )
    changed = (
        replace(revision, approval=Approval("pending"))
        if change == "pending"
        else replace(
            revision,
            license=replace(
                revision.license,
                redistribution_allowed=False,
            ),
        )
    )
    changed_ref = store.put_bytes(  # type: ignore[union-attr]
        changed.canonical_bytes()
    )
    changed_file = replace(metadata_file, revision=changed_ref)
    changed_manifest = PublicationManifest(
        publication.production_id,
        tuple(
            changed_file if item.role == "metadata" else item
            for item in publication.files
        ),
    )
    values["publication"] = changed_manifest
    values["verdict"] = replace(
        verdict,
        publication_manifest=changed_manifest.ref,
    )

    with pytest.raises(ValueError, match=message):
        freeze_release(**values)  # type: ignore[arg-type]


def test_freeze_release_rejects_a_constraint_without_executable_policy(
    tmp_path: Path,
) -> None:
    values = _release_inputs(tmp_path)
    constraints = values["constraints"]
    assert isinstance(constraints, ConstraintSet)
    undocumented = ConstraintSet(
        constraints.production_id,
        constraints.source,
        (*constraints.constraints, Constraint("manual.only", "Looks plausible.")),
    )
    values["constraints"] = undocumented
    values["policy"] = replace(values["policy"], constraints=undocumented.ref)
    values["report"] = check_timeline(
        values["timeline"],  # type: ignore[arg-type]
        values["policy"],  # type: ignore[arg-type]
    )
    values["verdict"] = replace(
        values["verdict"],  # type: ignore[arg-type]
        check_report=values["report"].ref,  # type: ignore[union-attr]
        constraints=undocumented.ref,
    )

    with pytest.raises(ValueError, match="executable contract"):
        freeze_release(**values)  # type: ignore[arg-type]


def test_application_packages_only_the_accepted_exact_release(
    tmp_path: Path,
) -> None:
    repository = ProductionRepository(
        object_root=tmp_path / "objects",
        state_root=tmp_path / "state",
        staging_root=tmp_path / "staging",
        lock_root=tmp_path / "locks",
        production_id="fixture.reel",
    )
    values = _release_inputs(tmp_path, repository)
    store = values.pop("store")
    production_id = values.pop("production_id")
    workflows = WorkflowRepository(repository)
    start_workflow(workflows, run_id="run.main", kind="reel")

    timeline = values["timeline"]
    report = values["report"]
    artifact_report = values["artifact_report"]
    publication = values["publication"]
    constraints = values["constraints"]
    rendered = values["render"]
    verdict = values["verdict"]
    _advance(
        workflows,
        inputs=(),
        contract="prepare.v1",
        run_stage=lambda *_: (
            NamedRef("timeline", timeline.ref),  # type: ignore[union-attr]
            NamedRef("check_policy", values["policy"].ref),  # type: ignore[union-attr]
            NamedRef("check_report", report.ref),  # type: ignore[union-attr]
            NamedRef("constraints", constraints.ref),  # type: ignore[union-attr]
            NamedRef(
                "publication_manifest",
                repository.objects.put_bytes(
                    publication.canonical_bytes()  # type: ignore[union-attr]
                ),
            ),
        ),
    )
    _advance(
        workflows,
        inputs=(),
        contract="draft.v1",
        run_stage=lambda *_: (
            NamedRef("artifact", repository.objects.put_bytes(b"draft")),
        ),
    )
    _advance(
        workflows,
        inputs=(),
        contract="final.v1",
        run_stage=lambda *_: (
            NamedRef("artifact", rendered.artifact),  # type: ignore[union-attr]
            NamedRef("execution", values["fingerprint"].ref),  # type: ignore[union-attr]
            NamedRef("render_options", values["options"].ref),  # type: ignore[union-attr]
            NamedRef(
                "artifact_report",
                repository.objects.put_bytes(  # type: ignore[union-attr]
                    artifact_report.canonical_bytes()
                ),
            ),
        ),
    )
    repository.objects.put_bytes(report.canonical_bytes())  # type: ignore[union-attr]
    repository.objects.put_bytes(constraints.canonical_bytes())  # type: ignore[union-attr]
    submit_review(workflows, verdict)  # type: ignore[arg-type]
    before_package = workflows.read_current()
    assert before_package is not None

    candidate, ready = _package_release(
        workflows,
        store,  # type: ignore[arg-type]
        **values,
    )

    assert ready.eligible_candidate == candidate.ref
    assert ready.current_stage == "deliver"
    assert ready.revision == before_package.revision + 2
    assert candidate.production_id == production_id


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("verdict_artifact", "exact final"),
        ("verdict_outcome", "passing review"),
        ("policy_constraints", "executable contract"),
        ("render_key", "execution identity"),
    ),
)
def test_freeze_release_rejects_broken_exact_links(
    tmp_path: Path,
    field: str,
    message: str,
) -> None:
    values = _release_inputs(tmp_path)
    verdict = values["verdict"]
    policy = values["policy"]
    rendered = values["render"]
    assert isinstance(verdict, ReviewVerdict)
    assert isinstance(policy, CheckPolicy)
    assert isinstance(rendered, RenderResult)
    if field == "verdict_artifact":
        values["verdict"] = replace(
            verdict, artifact=BlobRef("f" * 64, 10)
        )
    elif field == "verdict_outcome":
        values["verdict"] = replace(verdict, outcome="block")
    elif field == "policy_constraints":
        values["policy"] = replace(
            policy, constraints=BlobRef("e" * 64, 10)
        )
    else:
        values["render"] = replace(rendered, cache_key="0" * 64)
    with pytest.raises(ValueError, match=message):
        freeze_release(**values)  # type: ignore[arg-type]
