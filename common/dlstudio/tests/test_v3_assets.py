from __future__ import annotations

import hashlib
import os
from dataclasses import replace
from pathlib import Path
from threading import Event, Thread

import pytest

from dlstudio.assets.api import (
    Approval,
    AssetIndexRevision,
    AssetRevision,
    AssetRevisionRef,
    License,
    MediaFacts,
    Provenance,
)
from dlstudio.capture.api import CaptureReceipt, CaptureRequest
from dlstudio.foundation.api import BlobRef, CasConflict, canonical_bytes
from dlstudio.persistence import ProductionRepository
from dlstudio.persistence.assets import AssetRepository
from dlstudio.speech.api import SpeechTakeReceipt


def _repositories(root: Path) -> tuple[ProductionRepository, AssetRepository]:
    studio = root / "fixture.assets" / "data" / ".studio"
    repository = ProductionRepository(
        object_root=studio / "objects",
        state_root=studio / "state",
        staging_root=studio / "staging",
        lock_root=studio / "locks",
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


def _ref(data: bytes) -> BlobRef:
    return BlobRef(hashlib.sha256(data).hexdigest(), len(data))


def _approval(
    repository: ProductionRepository,
    status: str = "validated",
    *,
    evidence: bytes = b"asset approval evidence",
) -> Approval:
    return Approval(status, (repository.objects.put_bytes(evidence),))


def test_asset_revision_is_canonical_owner_of_trust() -> None:
    revision = AssetRevision(
        asset_id="voice.main",
        blob=BlobRef("1" * 64, 10),
        media=_media(),
        provenance=_provenance(),
        approval=Approval("validated", (_ref(b"validation evidence"),)),
        license=_license(),
    )
    assert AssetRevision.from_canonical_bytes(revision.canonical_bytes()) == revision
    assert revision.ref.revision_hash == revision.revision_hash
    assert len(revision.revision_hash) == 64


def test_media_facts_reject_cross_kind_fields() -> None:
    with pytest.raises(ValueError, match="audio.*geometry"):
        MediaFacts(
            kind="audio",
            format_name="wav",
            duration_ns=1,
            width=10,
            height=10,
            sample_rate=48_000,
            channels=1,
        )
    with pytest.raises(ValueError, match="image.*audio"):
        MediaFacts(
            kind="image",
            format_name="png",
            width=10,
            height=10,
            sample_rate=48_000,
            channels=1,
        )


def test_recorded_provenance_requires_supported_method_and_exact_refs() -> None:
    with pytest.raises(ValueError, match="recorded provenance"):
        Provenance(origin="recorded", capture_method="file")
    with pytest.raises(ValueError, match="script evidence"):
        Provenance(
            origin="recorded",
            capture_method="voice_take",
            state_id="take-01",
            provider_receipt_ref=_ref(b"recorder receipt"),
        )


def test_trust_evidence_refs_must_be_non_empty() -> None:
    empty = BlobRef(hashlib.sha256(b"").hexdigest(), 0)
    with pytest.raises(ValueError, match="approval evidence.*non-empty"):
        Approval("approved", (empty,))
    with pytest.raises(ValueError, match="provider receipt.*non-empty"):
        Provenance(
            origin="generated",
            capture_method="generator",
            provider_receipt_ref=empty,
        )


def test_ingest_rejects_unreachable_approval_evidence(tmp_path: Path) -> None:
    repository, assets = _repositories(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"asset bytes")
    imaginary = BlobRef("f" * 64, 123)
    with pytest.raises(Exception, match="missing or wrong-sized"):
        assets.ingest(
            source,
            asset_id="voice.main",
            media=_media(),
            provenance=_provenance(),
            approval=Approval("approved", (imaginary,)),
            license=_license(),
            expected_revision=0,
            inspect_media=lambda _path: _media(),
        )
    assert repository.read_head() is None


def test_ingest_rejects_unreachable_provider_evidence(tmp_path: Path) -> None:
    repository, assets = _repositories(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"generated asset bytes")
    provenance = Provenance(
        origin="generated",
        capture_method="generator",
        provider_receipt_ref=BlobRef("e" * 64, 321),
    )
    with pytest.raises(Exception, match="missing or wrong-sized"):
        assets.ingest(
            source,
            asset_id="voice.generated",
            media=_media(),
            provenance=provenance,
            approval=Approval("pending"),
            license=_license(),
            expected_revision=0,
            inspect_media=lambda _path: _media(),
        )
    assert repository.read_head() is None


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
        approval=_approval(repository),
        license=_license(),
        expected_revision=0,
        inspect_media=inspector,
    )
    assert first.created
    assert (source.read_bytes(), source.stat().st_mtime_ns) == before
    assert assets.read_revision(first.revision.ref) == first.revision
    assert assets.read_index().entries["voice.main"] == first.revision.ref

    repeated = assets.ingest(
        source,
        asset_id="voice.main",
        media=_media(),
        provenance=_provenance(),
        approval=_approval(repository),
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
    after_unrelated = assets.ingest(
        source,
        asset_id="voice.main",
        media=_media(),
        provenance=_provenance(),
        approval=_approval(repository),
        license=_license(),
        expected_revision=0,
        inspect_media=inspector,
    )
    assert not after_unrelated.created
    assert after_unrelated.state_revision == 2

    second = assets.ingest(
        source,
        asset_id="voice.main",
        media=_media(),
        provenance=_provenance(),
        approval=_approval(repository, "approved", evidence=b"approval evidence"),
        license=_license(),
        expected_revision=2,
        inspect_media=inspector,
    )
    assert second.created
    assert assets.read_revision(first.revision.ref) == first.revision
    assert set(repository.read_root().records) == {
        "assets:index",
        "unrelated",
    }
    assets.collect_garbage(apply=True)
    repository.objects.verify(first.revision.ref.object)


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
            approval=_approval(repository),
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
        approval=_approval(repository),
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
        approval=_approval(repository),
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
        approval=_approval(repository),
        license=_license(),
        expected_revision=0,
        inspect_media=lambda _path: _media(),
    )
    repository.objects.path_for(result.revision.blob).unlink()
    with pytest.raises(Exception, match="missing or wrong-sized"):
        assets.collect_garbage()


def test_read_revision_fails_closed_on_missing_approval_evidence(
    tmp_path: Path,
) -> None:
    repository, assets = _repositories(tmp_path)
    source = tmp_path / "source.wav"
    source.write_bytes(b"reachable")
    evidence = repository.objects.put_bytes(b"approval evidence")
    result = assets.ingest(
        source,
        asset_id="voice.main",
        media=_media(),
        provenance=_provenance(),
        approval=Approval("approved", (evidence,)),
        license=_license(),
        expected_revision=0,
        inspect_media=lambda _path: _media(),
    )
    repository.objects.path_for(evidence).unlink()
    with pytest.raises(Exception, match="missing or wrong-sized"):
        assets.read_revision(result.revision.ref)


def test_read_revision_requires_its_exact_object(tmp_path: Path) -> None:
    repository, assets = _repositories(tmp_path)
    missing = AssetRevisionRef(
        "voice.main", BlobRef("9" * 64, 123)
    )
    with pytest.raises(Exception, match="missing or wrong-sized"):
        assets.read_revision(missing)


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
        audit_ref=_ref(b"capture audit"),
    )
    provenance = receipt.provenance_for(request)
    assert provenance.state_id == "state-1"
    assert provenance.provider_receipt_ref == _ref(b"capture audit")

    with pytest.raises(ValueError, match="handles"):
        replace(receipt, head_ns=1).provenance_for(request)


def test_speech_take_provenance_is_script_hash_bound() -> None:
    script_bytes = canonical_bytes(
        {"text": "Exact final words"}, domain="dlstudio.voice_script"
    )
    receipt = SpeechTakeReceipt(
        script_text="Exact final words",
        script_ref=_ref(script_bytes),
        take_id="take-01",
        recorder_receipt_ref=_ref(b"recorder receipt"),
    )
    provenance = receipt.provenance()
    changed_script_bytes = canonical_bytes(
        {"text": "Changed final words"}, domain="dlstudio.voice_script"
    )
    changed = SpeechTakeReceipt(
        script_text="Changed final words",
        script_ref=_ref(changed_script_bytes),
        take_id="take-01",
        recorder_receipt_ref=_ref(b"recorder receipt"),
    )
    assert provenance.capture_method == "voice_take"
    assert provenance.script_ref != changed.script_ref

    with pytest.raises(ValueError, match="script evidence"):
        replace(receipt, script_text="tampered")
