from __future__ import annotations

import json

import pytest

from dlstudio.foundation.api import BlobRef
from dlstudio.review.api import (
    REVIEW_PACK_MAX_BYTES,
    REVIEW_PACK_MAX_ITEMS,
    ReviewFinding,
    ReviewVerdict,
    build_review_pack,
)


def _verdict(**changes: object) -> ReviewVerdict:
    values: dict[str, object] = {
        "artifact": BlobRef("1" * 64, 100),
        "outcome": "pass",
        "check_report": BlobRef("9" * 64, 90),
        "constraints": BlobRef("8" * 64, 80),
        "scope": ("audio", "visual", "constraints"),
        "reviewer": "video.reviewer",
        "reviewed_at": "2026-07-27T00:00:00Z",
    }
    values.update(changes)
    return ReviewVerdict(**values)  # type: ignore[arg-type]


def test_verdict_round_trip_binds_policy_snapshot_and_exact_artifact() -> None:
    verdict = _verdict(
        review_pack=BlobRef("2" * 64, 20),
        evidence=(BlobRef("3" * 64, 30),),
    )
    assert ReviewVerdict.from_canonical_bytes(verdict.canonical_bytes()) == verdict
    assert verdict.reachable_blobs == (
        BlobRef("1" * 64, 100),
        BlobRef("9" * 64, 90),
        BlobRef("8" * 64, 80),
        BlobRef("2" * 64, 20),
        BlobRef("3" * 64, 30),
    )
    with pytest.raises(ValueError, match="stale"):
        verdict.require_artifact(BlobRef("4" * 64, 100))


def test_required_findings_are_the_change_requests() -> None:
    finding = ReviewFinding("safe.zone", "Move the title down.", True)
    verdict = _verdict(
        outcome="changes_requested",
        findings=(finding,),
    )
    assert verdict.findings == (finding,)
    with pytest.raises(ValueError, match="cannot require"):
        _verdict(findings=(finding,))


def test_simple_review_does_not_require_pack_or_roles() -> None:
    verdict = _verdict()
    assert verdict.review_pack is None
    assert verdict.findings == ()


@pytest.mark.performance_smoke
def test_review_pack_bounded() -> None:
    evidence = tuple(
        BlobRef(f"{index:064x}", 300_000) for index in range(100)
    )
    wrapped = json.loads(build_review_pack(BlobRef("a" * 64, 10), evidence))
    payload = wrapped["payload"]
    assert len(payload["evidence"]) <= REVIEW_PACK_MAX_ITEMS
    assert payload["evidence_bytes"] <= REVIEW_PACK_MAX_BYTES
