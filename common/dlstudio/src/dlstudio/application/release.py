"""Freeze one fully validated release closure."""

from __future__ import annotations

from pathlib import Path
from typing import Literal, Protocol

from dlstudio.assets.api import AssetRevision
from dlstudio.constraints.api import Constraint, ConstraintSet
from dlstudio.foundation.api import BlobRef, canonical_bytes
from dlstudio.release.api import (
    PackageFile,
    PublicationManifest,
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
from dlstudio.timeline.api import (
    CheckPolicy,
    CheckReport,
    TimelineIR,
    check_timeline,
)


class BlobStore(Protocol):
    def put_bytes(self, data: bytes) -> BlobRef: ...

    def ingest_file(self, source: Path) -> BlobRef: ...

    def read(self, ref: BlobRef) -> bytes: ...

    def path_for(self, ref: BlobRef) -> Path: ...

    def verify(self, ref: BlobRef) -> None: ...


def build_release_gate(
    production_id: str,
    platform: Literal["vertical", "landscape"],
    *,
    require_voice: bool,
    kind: Literal["reel", "longform", "capture_vo"],
) -> tuple[ConstraintSet, CheckPolicy]:
    """Build the one executable release gate and its human-readable contract."""

    if platform not in {"vertical", "landscape"}:
        raise ValueError("release platform must be vertical or landscape")
    if kind not in {"reel", "longform", "capture_vo"}:
        raise ValueError("unsupported release kind")
    executable_constraints = [
        Constraint(
            f"platform.{platform}",
            f"Output must be {platform}.",
            "blocker",
        ),
        Constraint(
            "assets.approved",
            "Every referenced asset revision must be approved.",
            "blocker",
        ),
        Constraint(
            "assets.redistributable",
            "Every referenced asset must permit release redistribution.",
            "blocker",
        ),
    ]
    if require_voice:
        executable_constraints.append(
            Constraint(
                "audio.voice.required",
                "Timeline must include an explicit voice audio instruction.",
                "blocker",
            )
        )
    if kind == "reel":
        executable_constraints.extend(
            (
                Constraint(
                    "package.cover.required",
                    "Release package must include an approved cover.",
                    "blocker",
                ),
                Constraint(
                    "package.metadata.required",
                    "Release package must include approved metadata.",
                    "blocker",
                ),
            )
        )
    constraints = ConstraintSet(
        production_id,
        "studio.v3.defaults",
        tuple(executable_constraints),
    )
    return constraints, CheckPolicy(
        policy_id="studio_v3.release",
        platform=platform,
        constraints=constraints.ref,
        require_approved_assets=True,
        require_redistributable_assets=True,
        require_voice=require_voice,
    )


def freeze_release(
    store: BlobStore,
    *,
    production_id: str,
    kind: Literal["reel", "longform", "capture_vo"],
    timeline: TimelineIR,
    policy: CheckPolicy,
    report: CheckReport,
    artifact_report: ArtifactReport,
    publication: PublicationManifest,
    fingerprint: ExecutionFingerprint,
    options: RenderOptions,
    render: RenderResult,
    constraints: ConstraintSet,
    verdict: ReviewVerdict,
    package: tuple[PackageFile, ...],
) -> tuple[ReleaseCandidate, BlobRef]:
    """Validate exact relations once; delivery only copies the frozen package."""

    if timeline.production_id != production_id:
        raise ValueError("timeline belongs to another production")
    if constraints.production_id != production_id:
        raise ValueError("constraints belong to another production")
    platform = "vertical" if timeline.height > timeline.width else "landscape"
    expected_constraints, expected_policy = build_release_gate(
        production_id,
        platform,
        require_voice=policy.require_voice,
        kind=kind,
    )
    if constraints != expected_constraints or policy != expected_policy:
        raise ValueError("release gate does not match the executable contract")
    if policy.constraints != constraints.ref:
        raise ValueError("check policy does not use these constraints")
    if not policy.require_approved_assets:
        raise ValueError("release policy must require approved assets")
    if not policy.require_redistributable_assets:
        raise ValueError("release policy must require redistributable assets")
    expected_report = check_timeline(timeline, policy)
    if report != expected_report or report.blocking:
        raise ValueError("release check report is stale or blocking")
    expected_key = execution_key(timeline, fingerprint, options)
    if render.cache_key != expected_key:
        raise ValueError("render execution identity does not match")
    if artifact_report.blocking:
        raise ValueError("release artifact report is blocking")
    if artifact_report.artifact != render.artifact:
        raise ValueError("artifact report does not name the exact final artifact")
    if verdict.outcome != "pass":
        raise ValueError("release requires a passing review")
    if verdict.artifact != render.artifact:
        raise ValueError("review does not name the exact final artifact")
    if verdict.artifact_report != artifact_report.ref:
        raise ValueError("review does not name the exact artifact report")
    if publication.production_id != production_id:
        raise ValueError("publication manifest belongs to another production")
    if verdict.publication_manifest != publication.ref:
        raise ValueError("review does not name the exact publication manifest")
    if verdict.check_report != report.ref:
        raise ValueError("review does not name the exact check report")
    if verdict.constraints != constraints.ref:
        raise ValueError("review does not name the exact constraints")
    if not {"audio", "visual", "constraints"}.issubset(verdict.scope):
        raise ValueError("final review scope is incomplete")

    objects = store
    timeline_ref = objects.put_bytes(timeline.canonical_bytes())
    policy_ref = objects.put_bytes(policy.canonical_bytes())
    report_ref = objects.put_bytes(report.canonical_bytes())
    artifact_report_ref = objects.put_bytes(artifact_report.canonical_bytes())
    execution_ref = objects.put_bytes(fingerprint.canonical_bytes())
    options_ref = objects.put_bytes(options.canonical_bytes())
    constraints_ref = objects.put_bytes(constraints.canonical_bytes())
    publication_ref = objects.put_bytes(publication.canonical_bytes())
    verdict_ref = objects.put_bytes(verdict.canonical_bytes())
    if (
        timeline_ref != timeline.ref
        or policy_ref != policy.ref
        or report_ref != report.ref
        or artifact_report_ref != artifact_report.ref
        or execution_ref != fingerprint.ref
        or options_ref != options.ref
        or constraints_ref != constraints.ref
        or publication_ref != publication.ref
        or verdict_ref != verdict.ref
    ):
        raise ValueError("release input identity mismatch")

    revision_refs: list[BlobRef] = []
    licenses: list[dict[str, object]] = []
    for snapshot in timeline.assets:
        revision = snapshot.revision
        if revision.approval.status != "approved":
            raise ValueError(f"asset is not approved: {revision.asset_id}")
        if not revision.license.redistribution_allowed:
            raise ValueError(f"asset is not redistributable: {revision.asset_id}")
        revision_ref = objects.put_bytes(revision.canonical_bytes())
        if revision_ref != revision.ref.object:
            raise ValueError("asset revision identity mismatch")
        revision_refs.append(revision_ref)
        for reachable in revision.reachable_blobs:
            objects.verify(reachable)
        licenses.append(
            {
                "asset_id": revision.asset_id,
                "revision": revision_ref.as_payload(),
                "license": revision.license.as_payload(),
            }
        )

    publication_files: list[PackageFile] = []
    publication_roles = {item.role for item in publication.files}
    if kind == "reel" and not {"cover", "metadata"}.issubset(
        publication_roles
    ):
        raise ValueError("reel package requires cover and metadata")
    for item in publication.files:
        revision = AssetRevision.from_canonical_bytes(objects.read(item.revision))
        if revision.ref.object != item.revision:
            raise ValueError("publication revision identity mismatch")
        if revision.asset_id != item.asset_id or revision.blob != item.blob:
            raise ValueError("publication manifest revision link mismatch")
        if revision.approval.status != "approved":
            raise ValueError(f"publication asset is not approved: {item.asset_id}")
        if not revision.license.redistribution_allowed:
            raise ValueError(
                f"publication asset is not redistributable: {item.asset_id}"
            )
        expected_kind = "image" if item.role == "cover" else "data"
        if revision.media.kind != expected_kind:
            raise ValueError(
                f"publication {item.role} must use a {expected_kind} asset"
            )
        for reachable in revision.reachable_blobs:
            objects.verify(reachable)
        revision_refs.append(item.revision)
        licenses.append(
            {
                "asset_id": revision.asset_id,
                "revision": item.revision.as_payload(),
                "license": revision.license.as_payload(),
            }
        )
        publication_files.append(PackageFile(item.path, item.blob))

    license_raw = canonical_bytes(
        {"assets": licenses},
        domain="dlstudio.release_license_bundle",
        version=1,
    )
    license_ref = objects.put_bytes(license_raw)
    reserved = {"licenses.json", *(item.path for item in package)}
    if "licenses.json" in {item.path for item in package}:
        raise ValueError("licenses.json is generated by freeze_release")
    if any(item.path in reserved for item in publication_files):
        raise ValueError("publication path collides with a generated package file")
    frozen_package = (
        *package,
        *publication_files,
        PackageFile("licenses.json", license_ref),
    )
    for item in frozen_package:
        objects.verify(item.blob)
    objects.verify(render.artifact)

    candidate = ReleaseCandidate(
        production_id=production_id,
        timeline=timeline_ref,
        check_policy=policy_ref,
        execution=execution_ref,
        render_options=options_ref,
        execution_key=expected_key,
        final_output=render.artifact,
        artifact_report=artifact_report_ref,
        publication_manifest=publication_ref,
        check_report=report_ref,
        review_verdict=verdict_ref,
        constraints=constraints_ref,
        asset_revisions=tuple(revision_refs),
        license_bundle=license_ref,
        package=frozen_package,
    )
    candidate_ref = objects.put_bytes(candidate.canonical_bytes())
    if candidate_ref != candidate.ref:
        raise ValueError("release candidate identity mismatch")
    return candidate, candidate_ref
