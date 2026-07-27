from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from dlstudio.application.api import (
    advance,
    package_release,
    start_workflow,
    submit_review,
)
from dlstudio.application.release import freeze_release
from dlstudio.authoring.api import Edit, SolidLayer, _compile_resolved
from dlstudio.constraints.api import Constraint, ConstraintSet
from dlstudio.foundation.api import BlobRef, CanonicalEncodingError
from dlstudio.persistence import WorkflowRepository
from dlstudio.persistence.api import ProductionRepository
from dlstudio.release.api import DeliveryReceipt, PackageFile, ReleaseCandidate
from dlstudio.rendering.api import (
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
    assert len(candidate.reachable_blobs) == 12


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
    constraints = ConstraintSet(
        "fixture.reel",
        "test",
        (Constraint("safe.zone", "Keep text inside the safe zone."),),
    )
    policy = CheckPolicy(
        policy_id="studio_v3.release",
        platform="vertical",
        constraints=constraints.ref,
        require_approved_assets=True,
        require_redistributable_assets=True,
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
    verdict = ReviewVerdict(
        artifact=final,
        outcome="pass",
        check_report=report.ref,
        constraints=constraints.ref,
        scope=("audio", "visual", "constraints"),
        reviewer="video.reviewer",
        reviewed_at="2026-07-27T00:00:00Z",
    )
    return {
        "store": repository.objects,
        "production_id": repository.production_id,
        "timeline": timeline,
        "policy": policy,
        "report": report,
        "fingerprint": fingerprint,
        "options": options,
        "render": rendered,
        "constraints": constraints,
        "verdict": verdict,
        "package": (PackageFile("video.mp4", final),),
    }


def test_freeze_release_validates_and_publishes_exact_chain(
    tmp_path: Path,
) -> None:
    values = _release_inputs(tmp_path)
    candidate, candidate_ref = freeze_release(**values)  # type: ignore[arg-type]
    store = values["store"]
    assert candidate_ref == candidate.ref
    assert candidate.check_report == values["report"].ref  # type: ignore[union-attr]
    assert candidate.constraints == values["constraints"].ref  # type: ignore[union-attr]
    assert {item.path for item in candidate.package} == {
        "video.mp4",
        "licenses.json",
    }
    store.verify(candidate_ref)  # type: ignore[union-attr]


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
    constraints = values["constraints"]
    rendered = values["render"]
    verdict = values["verdict"]
    advance(
        workflows,
        inputs=(),
        contract="prepare.v1",
        run_stage=lambda *_: (
            NamedRef("timeline", timeline.ref),  # type: ignore[union-attr]
            NamedRef("check_policy", values["policy"].ref),  # type: ignore[union-attr]
            NamedRef("check_report", report.ref),  # type: ignore[union-attr]
            NamedRef("constraints", constraints.ref),  # type: ignore[union-attr]
        ),
    )
    advance(
        workflows,
        inputs=(),
        contract="draft.v1",
        run_stage=lambda *_: (
            NamedRef("artifact", repository.objects.put_bytes(b"draft")),
        ),
    )
    advance(
        workflows,
        inputs=(),
        contract="final.v1",
        run_stage=lambda *_: (
            NamedRef("artifact", rendered.artifact),  # type: ignore[union-attr]
            NamedRef("execution", values["fingerprint"].ref),  # type: ignore[union-attr]
            NamedRef("render_options", values["options"].ref),  # type: ignore[union-attr]
        ),
    )
    repository.objects.put_bytes(report.canonical_bytes())  # type: ignore[union-attr]
    repository.objects.put_bytes(constraints.canonical_bytes())  # type: ignore[union-attr]
    submit_review(workflows, verdict)  # type: ignore[arg-type]

    candidate, ready = package_release(
        workflows,
        store,  # type: ignore[arg-type]
        **values,
    )

    assert ready.eligible_candidate == candidate.ref
    assert ready.current_stage == "deliver"
    assert candidate.production_id == production_id


@pytest.mark.parametrize(
    ("field", "message"),
    (
        ("verdict_artifact", "exact final"),
        ("verdict_outcome", "passing review"),
        ("policy_constraints", "these constraints"),
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
