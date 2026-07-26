from __future__ import annotations

import os
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread

import pytest

from dlstudio.application.api import ProductionContext
from dlstudio.assets.api import (
    Approval,
    AssetIndexRevision,
    AssetRevision,
    BlobRef,
    License,
    MediaFacts,
    Provenance,
)
from dlstudio.capture.api import CaptureReceipt, CaptureRequest
from dlstudio.foundation.api import CasConflict
from dlstudio.persistence import ProductionRepository
from dlstudio.persistence import OperationTransaction
from dlstudio.persistence.assets import AssetRepository
from dlstudio.speech.api import SpeechTakeReceipt


def _repositories(root: Path) -> tuple[ProductionRepository, AssetRepository]:
    context = ProductionContext.create(
        workspace_root=root,
        project_root=root,
        production_id="fixture.assets",
        production_root=root / "fixture.assets",
    )
    paths = context.paths
    repository = ProductionRepository(
        object_root=paths.object_root,
        state_root=paths.state_root,
        staging_root=paths.staging_root,
        lock_root=paths.lock_root,
        production_id="fixture.assets",
    )
    return repository, AssetRepository(repository)


def _media() -> MediaFacts:
    return MediaFacts(
        kind="audio",
        format_name="wav",
        duration_ns=1_000_000_000,
        sample_rate=48_000,
        channels=1,
        codec="pcm_s16le",
    )


def _provenance() -> Provenance:
    return Provenance(
        origin="provided",
        capture_method="file",
        logical_source="data/audio/take.wav",
    )


def _license() -> License:
    return License("owned", False)


def test_asset_revision_is_canonical_owner_of_trust() -> None:
    revision = AssetRevision(
        asset_id="voice.main",
        blob=BlobRef("1" * 64, 10),
        media=_media(),
        provenance=_provenance(),
        approval=Approval("validated", ("2" * 64,)),
        license=_license(),
    )
    assert AssetRevision.from_canonical_bytes(revision.canonical_bytes()) == revision
    assert revision.ref.revision_hash == revision.revision_hash
    assert revision.revision_hash == (
        "3f14b3fb3a5196f8802c8c704fc01d8115b53ad02893c001123ed525c6ba06cf"
    )


def test_asset_index_defensively_snapshots_entries() -> None:
    revision = AssetRevision(
        "voice.main",
        BlobRef("1" * 64, 10),
        _media(),
        _provenance(),
        Approval("pending"),
        _license(),
    )
    entries = {"voice.main": revision.ref}
    index = AssetIndexRevision(entries)
    entries.clear()
    assert index.entries == {"voice.main": revision.ref}
    with pytest.raises(TypeError):
        index.entries["voice.other"] = revision.ref  # type: ignore[index]


def test_ingest_is_source_preserving_idempotent_and_rebuildable(
    tmp_path: Path,
) -> None:
    repository, assets = _repositories(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"immutable source bytes")
    before = (source.read_bytes(), source.stat().st_mtime_ns)
    inspector = lambda _path: _media()

    first = assets.ingest(
        source,
        asset_id="voice.main",
        media=_media(),
        provenance=_provenance(),
        approval=Approval("validated", ("5" * 64,)),
        license=_license(),
        expected_revision=0,
        inspect_media=inspector,
    )
    assert first.created
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert assets.read_revision(first.revision.ref) == first.revision
    assert assets.rebuild_index() == assets.read_index()

    repeated = assets.ingest(
        source,
        asset_id="voice.main",
        media=_media(),
        provenance=_provenance(),
        approval=Approval("validated", ("5" * 64,)),
        license=_license(),
        expected_revision=0,
        inspect_media=inspector,
    )
    assert not repeated.created
    assert repeated.state_root_hash == first.state_root_hash
    assert repeated.state_revision == first.state_revision
    head = repository.read_head()
    assert head is not None
    assert head.root_hash == first.state_root_hash
    assert head.revision == first.state_revision

    repository.update_records(
        {"unrelated": repository.objects.put_bytes(b"unrelated")},
        expected_revision=1,
    )
    with pytest.raises(CasConflict, match="retry expected revision"):
        assets.ingest(
            source,
            asset_id="voice.main",
            media=_media(),
            provenance=_provenance(),
            approval=Approval("validated", ("5" * 64,)),
            license=_license(),
            expected_revision=2,
            inspect_media=inspector,
        )

    second = assets.ingest(
        source,
        asset_id="voice.main",
        media=_media(),
        provenance=_provenance(),
        approval=Approval("approved", ("6" * 64,)),
        license=_license(),
        expected_revision=2,
        inspect_media=inspector,
    )
    assert second.created
    assert second.revision.provenance.parent_revision_hash == (
        first.revision.revision_hash
    )
    assets.verify_index_projection()


def test_stale_ingest_leaves_only_collectable_orphans(tmp_path: Path) -> None:
    repository, assets = _repositories(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"orphan candidate")
    with pytest.raises(CasConflict):
        assets.ingest(
            source,
            asset_id="voice.main",
            media=_media(),
            provenance=_provenance(),
            approval=Approval("validated", ("5" * 64,)),
            license=_license(),
            expected_revision=1,
            inspect_media=lambda _path: _media(),
        )
    assert repository.read_head() is None
    report = assets.collect_garbage()
    assert report.reachable == 0
    assert report.candidates
    removed = assets.collect_garbage(apply=True)
    assert removed.removed == removed.candidates
    assert source.read_bytes() == b"orphan candidate"


def test_ingest_excludes_gc_before_first_blob_publication(
    tmp_path: Path,
) -> None:
    repository, assets = _repositories(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"protected during ingest")
    gc_attempted = Event()
    gc_finished = Event()

    def inspect(_path: Path) -> MediaFacts:
        def collect() -> None:
            gc_attempted.set()
            assets.collect_garbage(apply=True)
            gc_finished.set()

        worker = Thread(target=collect)
        worker.start()
        assert gc_attempted.wait(timeout=2)
        worker.join(timeout=0.1)
        assert worker.is_alive()
        return _media()

    result = assets.ingest(
        source,
        asset_id="voice.main",
        media=_media(),
        provenance=_provenance(),
        approval=Approval("validated", ("5" * 64,)),
        license=_license(),
        expected_revision=0,
        inspect_media=inspect,
    )
    assert result.created
    assert gc_finished.wait(timeout=5)
    repository.objects.verify(result.revision.blob)


def test_gc_retains_nested_asset_blob_and_removes_only_orphan(
    tmp_path: Path,
) -> None:
    repository, assets = _repositories(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"reachable")
    result = assets.ingest(
        source,
        asset_id="voice.main",
        media=_media(),
        provenance=_provenance(),
        approval=Approval("validated", ("5" * 64,)),
        license=_license(),
        expected_revision=0,
        inspect_media=lambda _path: _media(),
    )
    orphan = repository.objects.put_bytes(b"orphan")
    report = assets.collect_garbage()
    assert orphan in report.candidates
    assert result.revision.blob not in report.candidates
    assets.collect_garbage(apply=True)
    repository.objects.verify(result.revision.blob)
    assert not repository.objects.path_for(orphan).exists()


def test_gc_fails_closed_on_dangling_canonical_asset_blob(
    tmp_path: Path,
) -> None:
    repository, assets = _repositories(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"reachable")
    result = assets.ingest(
        source,
        asset_id="voice.main",
        media=_media(),
        provenance=_provenance(),
        approval=Approval("validated", ("5" * 64,)),
        license=_license(),
        expected_revision=0,
        inspect_media=lambda _path: _media(),
    )
    repository.objects.path_for(result.revision.blob).unlink()
    with pytest.raises(Exception, match="missing or wrong-sized"):
        assets.collect_garbage()


def test_gc_barrier_drains_active_operations_without_serializing_them(
    tmp_path: Path,
) -> None:
    repository, assets = _repositories(tmp_path)
    transaction = OperationTransaction(
        repository, operation_id="7" * 64, inputs={}
    )
    transaction.prepare()
    started = Event()
    completed = Event()

    def collect() -> None:
        started.set()
        assets.collect_garbage()
        completed.set()

    worker = Thread(target=collect)
    worker.start()
    assert started.wait(timeout=2)
    worker.join(timeout=0.1)
    assert worker.is_alive()
    transaction.close()
    worker.join(timeout=5)
    assert completed.is_set()


def test_rebuild_rejects_missing_asset_lineage_parent(tmp_path: Path) -> None:
    repository, assets = _repositories(tmp_path)
    blob = repository.objects.put_bytes(b"revision")
    broken = AssetRevision(
        "voice.main",
        blob,
        _media(),
        replace(_provenance(), parent_revision_hash="9" * 64),
        Approval("pending"),
        _license(),
    )
    revision_object = repository.objects.put_bytes(broken.canonical_bytes())
    index_object = repository.objects.put_bytes(
        AssetIndexRevision({}).canonical_bytes()
    )
    records = {
        "assets:index": index_object,
        f"asset_revision:{broken.revision_hash}": revision_object,
    }
    repository._update_records(
        records,
        expected_revision=0,
        allowed_reserved_keys=frozenset(records),
    )
    with pytest.raises(Exception, match="parent is missing"):
        assets.rebuild_index()


def test_materialize_uses_isolated_verified_copy(
    tmp_path: Path,
) -> None:
    repository, assets = _repositories(tmp_path)
    blob = repository.objects.put_bytes(b"materialize me")
    target = tmp_path / "export" / "asset.bin"
    result = assets.materialize(blob, target)
    assert target.read_bytes() == b"materialize me"
    assert result.method == "verified-copy"
    assert os.stat(target).st_ino != os.stat(
        repository.objects.path_for(blob)
    ).st_ino
    target.write_bytes(b"mutable export")
    repository.objects.verify(blob)
    with pytest.raises(ValueError, match="canonical storage"):
        assets.materialize(blob, repository.object_root / ("0" * 64))


def test_capture_receipt_binds_method_state_build_geometry_and_handles() -> None:
    request = CaptureRequest(
        production_id="fixture.reel",
        asset_id="gameplay.main",
        editorial_role="gameplay",
        capture_method="realtime_window",
        state_id="state-1",
        build_id="build-1",
        width=1080,
        height=1920,
        minimum_head_ns=5_000_000_000,
        minimum_tail_ns=5_000_000_000,
    )
    receipt = CaptureReceipt(
        request_id=request.request_id,
        capture_method="realtime_window",
        state_id="state-1",
        build_id="build-1",
        width=1080,
        height=1920,
        head_ns=5_000_000_000,
        tail_ns=6_000_000_000,
        audit_sha256="3" * 64,
    )
    provenance = receipt.provenance_for(request)
    assert provenance.state_id == "state-1"
    assert provenance.provider_receipt_sha256 == "3" * 64

    with pytest.raises(ValueError, match="handles"):
        replace(receipt, head_ns=1).provenance_for(request)


def test_speech_take_provenance_is_script_hash_bound() -> None:
    receipt = SpeechTakeReceipt(
        script_text="Exact final words",
        take_id="take-01",
        recorder_receipt_sha256="4" * 64,
    )
    provenance = receipt.provenance()
    changed = SpeechTakeReceipt(
        script_text="Changed final words",
        take_id="take-01",
        recorder_receipt_sha256="4" * 64,
    )
    assert provenance.capture_method == "voice_take"
    assert provenance.script_sha256 != changed.script_sha256
