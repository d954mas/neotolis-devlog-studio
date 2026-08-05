from __future__ import annotations

import hashlib
from dataclasses import replace
from pathlib import Path

import pytest

from dlstudio.application.api import advance_production
from dlstudio.application.authoring import resolve_publication
from dlstudio.assets.api import (
    Approval,
    AssetRevision,
    License,
    MediaFacts,
    Provenance,
)
from dlstudio.authoring.api import Edit, PublicationFile
from dlstudio.foundation.api import BlobRef, CanonicalEncodingError
from dlstudio.persistence import WorkflowRepository
from dlstudio.persistence.api import ProductionRepository
from dlstudio.release.api import PublicationManifest, PublicationManifestFile


def _ref(raw: bytes) -> BlobRef:
    return BlobRef(hashlib.sha256(raw).hexdigest(), len(raw))


def _revision(asset_id: str, raw: bytes, kind: str) -> AssetRevision:
    evidence = _ref(f"approval:{asset_id}".encode())
    media = (
        MediaFacts("image", "png", width=1080, height=1920)
        if kind == "image"
        else MediaFacts("data", "markdown")
    )
    return AssetRevision(
        asset_id,
        _ref(raw),
        media,
        Provenance("provided", "publication_fixture"),
        Approval("approved", (evidence,)),
        License("owned", False),
    )


class _Assets:
    def __init__(self, revisions: tuple[AssetRevision, ...]) -> None:
        self.revisions = {item.asset_id: item for item in revisions}

    def current(self, asset_id: str) -> AssetRevision:
        return self.revisions[asset_id]


def _install(
    repository: ProductionRepository,
    revision: AssetRevision,
    raw: bytes,
) -> None:
    assert repository.objects.put_bytes(raw) == revision.blob
    evidence = f"approval:{revision.asset_id}".encode()
    assert repository.objects.put_bytes(evidence) in revision.approval.evidence_refs


def _edit(*files: PublicationFile) -> Edit:
    return Edit(
        production_id="fixture.reel",
        width=1080,
        height=1920,
        fps_num=30,
        fps_den=1,
        duration_ns=1_000_000_000,
        background="black",
        standalone_story="Publication intent fixture.",
        publication=files,
    )


def test_publication_manifest_resolves_exact_current_revisions() -> None:
    cover = _revision("publish.cover.main", b"cover", "image")
    metadata = _revision("publish.metadata.main", b"# title", "data")
    edit = _edit(
        PublicationFile("cover", "cover.png", cover.asset_id),
        PublicationFile("metadata", "youtube/metadata.md", metadata.asset_id),
    )

    manifest, revisions = resolve_publication(
        edit,
        _Assets((cover, metadata)),  # type: ignore[arg-type]
    )

    assert PublicationManifest.from_canonical_bytes(
        manifest.canonical_bytes()
    ) == manifest
    assert revisions == (cover, metadata)
    assert tuple(item.path for item in manifest.files) == (
        "cover.png",
        "youtube/metadata.md",
    )
    assert manifest.reachable_blobs == (
        cover.blob,
        cover.ref.object,
        metadata.blob,
        metadata.ref.object,
    )

    changed = replace(metadata, blob=_ref(b"# changed title"))
    changed_manifest, _ = resolve_publication(
        edit,
        _Assets((cover, changed)),  # type: ignore[arg-type]
    )
    assert changed_manifest.ref != manifest.ref


def test_publication_manifest_rejects_duplicate_logical_paths() -> None:
    with pytest.raises(ValueError, match="duplicate publication path"):
        PublicationManifest(
            "fixture.reel",
            (
                PublicationManifestFile(
                    "cover",
                    "same.bin",
                    "publish.cover.main",
                    _ref(b"cover revision"),
                    _ref(b"cover"),
                ),
                PublicationManifestFile(
                    "metadata",
                    "same.bin",
                    "publish.metadata.main",
                    _ref(b"metadata revision"),
                    _ref(b"metadata"),
                ),
            ),
        )


@pytest.mark.parametrize(
    ("cover_path", "metadata_path"),
    (("Video.mp4", "video.mp4"), ("package", "package/metadata.md")),
)
def test_publication_manifest_rejects_nonportable_namespace_collisions(
    cover_path: str,
    metadata_path: str,
) -> None:
    with pytest.raises(CanonicalEncodingError, match="collide"):
        PublicationManifest(
            "fixture.reel",
            (
                PublicationManifestFile(
                    "cover",
                    cover_path,
                    "publish.cover.main",
                    _ref(b"cover revision"),
                    _ref(b"cover"),
                ),
                PublicationManifestFile(
                    "metadata",
                    metadata_path,
                    "publish.metadata.main",
                    _ref(b"metadata revision"),
                    _ref(b"metadata"),
                ),
            ),
        )


def test_publication_revision_change_invalidates_prepare_lineage(
    tmp_path: Path,
) -> None:
    repository = ProductionRepository(
        object_root=tmp_path / "objects",
        state_root=tmp_path / "state",
        staging_root=tmp_path / "staging",
        lock_root=tmp_path / "locks",
        production_id="fixture.reel",
    )
    workflows = WorkflowRepository(repository)
    cover = _revision("publish.cover.main", b"cover", "image")
    metadata = _revision("publish.metadata.main", b"# title", "data")
    assets = _Assets((cover, metadata))
    _install(repository, cover, b"cover")
    _install(repository, metadata, b"# title")
    authoring = tmp_path / "edit.py"
    authoring.write_text(
        "\n".join(
            (
                "from dlstudio.authoring.api import Edit, PublicationFile",
                "EDIT = Edit(",
                "    production_id='fixture.reel',",
                "    width=1080, height=1920, fps_num=30, fps_den=1,",
                "    duration_ns=1_000_000_000, background='black',",
                "    standalone_story='Publication lineage fixture.',",
                "    publication=(",
                "        PublicationFile('cover', 'cover.png', 'publish.cover.main'),",
                "        PublicationFile('metadata', 'metadata.md', 'publish.metadata.main'),",
                "    ),",
                ")",
                "",
            )
        ),
        encoding="utf-8",
    )
    arguments = {
        "authoring_path": authoring,
        "output_root": tmp_path / "outputs",
    }

    first = advance_production(  # type: ignore[arg-type]
        workflows,
        assets,
        repository.objects,
        **arguments,
    )
    first_prepare = next(item for item in first.attempts if item.stage == "prepare")
    first_publication = next(
        item.blob
        for item in first_prepare.outputs
        if item.name == "publication_manifest"
    )

    changed_metadata = replace(metadata, blob=_ref(b"# changed title"))
    _install(repository, changed_metadata, b"# changed title")
    assets.revisions[changed_metadata.asset_id] = changed_metadata
    second = advance_production(  # type: ignore[arg-type]
        workflows,
        assets,
        repository.objects,
        **arguments,
    )
    second_prepare = next(item for item in second.attempts if item.stage == "prepare")
    second_publication = next(
        item.blob
        for item in second_prepare.outputs
        if item.name == "publication_manifest"
    )

    assert second.current_stage == "draft"
    assert second_publication != first_publication
    assert len(second.attempts) == 1
