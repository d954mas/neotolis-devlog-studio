from __future__ import annotations

import pytest

from dlstudio.foundation.api import BlobRef, CanonicalEncodingError
from dlstudio.release.api import DeliveryReceipt, PackageFile, ReleaseCandidate


def _blob(value: str, size: int = 10) -> BlobRef:
    return BlobRef(value * 64, size)


def _candidate() -> ReleaseCandidate:
    final = _blob("3", 100)
    return ReleaseCandidate(
        production_id="fixture.reel",
        timeline=_blob("1"),
        execution=_blob("2"),
        final_output=final,
        check_report=_blob("4"),
        review_verdict=_blob("5"),
        constraints=_blob("6"),
        asset_revisions=(_blob("7"), _blob("8")),
        license_bundle=_blob("9"),
        package=(
            PackageFile("video.mp4", final),
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
    assert len(candidate.reachable_blobs) == 10


def test_package_rejects_paths_and_arbitrary_final_output() -> None:
    with pytest.raises(CanonicalEncodingError, match="unsafe logical path"):
        PackageFile("../outside.mp4", _blob("1"))
    candidate = _candidate()
    with pytest.raises(ValueError, match="exact final"):
        ReleaseCandidate(
            production_id=candidate.production_id,
            timeline=candidate.timeline,
            execution=candidate.execution,
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
