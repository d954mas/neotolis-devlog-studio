from __future__ import annotations

import json

import pytest

from dlstudio.foundation.api import BlobRef, canonical_bytes
from dlstudio.review.api import (
    REVIEW_PACK_MAX_BYTES,
    REVIEW_PACK_MAX_ITEMS,
    ReviewFinding,
    ReviewLocator,
    ReviewResolution,
    ReviewRegion,
    ReviewRound,
    ReviewVerdict,
    build_review_pack,
    validate_review_round_transition,
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


def test_review_verdict_v3_golden_bytes_are_unchanged() -> None:
    assert _verdict().canonical_bytes() == (
        b'{"$domain":"dlstudio.review_verdict","$version":3,"payload":'
        b'{"artifact":{"sha256":"111111111111111111111111111111111111'
        b'1111111111111111111111111111","size":100},"check_report":{"sha256":'
        b'"999999999999999999999999999999999999999999999999999999999999'
        b'9999","size":90},"constraints":{"sha256":"888888888888888888888888'
        b'8888888888888888888888888888888888888888","size":80},"evidence":[],'
        b'"findings":[],"outcome":"pass","review_pack":null,"reviewed_at":'
        b'"2026-07-27T00:00:00Z","reviewer":"video.reviewer","scope":'
        b'["audio","constraints","visual"]}}'
    )


def test_review_round_v1_round_trip_orders_resolutions_and_direct_refs() -> None:
    verdict = BlobRef("a" * 64, 10)
    previous = BlobRef("b" * 64, 20)
    review_round = ReviewRound(
        verdict,
        previous,
        (
            ReviewResolution("finding.second", "obsolete"),
            ReviewResolution(
                "finding.first",
                "still_wrong",
                "finding.current",
            ),
        ),
    )

    assert review_round.resolutions == (
        ReviewResolution(
            "finding.first",
            "still_wrong",
            "finding.current",
        ),
        ReviewResolution("finding.second", "obsolete"),
    )
    assert review_round.reachable_blobs == (verdict, previous)
    assert ReviewRound.from_canonical_bytes(
        review_round.canonical_bytes()
    ) == review_round
    assert review_round.ref.size == len(review_round.canonical_bytes())


def test_review_resolution_enforces_status_and_current_finding_rules() -> None:
    with pytest.raises(ValueError, match="current finding"):
        ReviewResolution("finding.previous", "still_wrong")
    with pytest.raises(ValueError, match="only for still_wrong"):
        ReviewResolution(
            "finding.previous",
            "fixed",
            "finding.current",
        )
    with pytest.raises(ValueError, match="unsupported resolution"):
        ReviewResolution("finding.previous", "ignored")  # type: ignore[arg-type]


def test_review_round_rejects_ambiguous_or_first_round_resolutions() -> None:
    verdict = BlobRef("a" * 64, 10)
    previous = BlobRef("b" * 64, 20)
    with pytest.raises(ValueError, match="first review round"):
        ReviewRound(
            verdict,
            resolutions=(ReviewResolution("finding.previous", "fixed"),),
        )
    with pytest.raises(ValueError, match="duplicate previous"):
        ReviewRound(
            verdict,
            previous,
            (
                ReviewResolution("finding.previous", "fixed"),
                ReviewResolution("finding.previous", "obsolete"),
            ),
        )
    with pytest.raises(ValueError, match="duplicate current"):
        ReviewRound(
            verdict,
            previous,
            (
                ReviewResolution(
                    "finding.first",
                    "still_wrong",
                    "finding.current",
                ),
                ReviewResolution(
                    "finding.second",
                    "still_wrong",
                    "finding.current",
                ),
            ),
        )


def test_review_round_loader_rejects_noncanonical_resolution_order() -> None:
    raw = canonical_bytes(
        {
            "verdict": BlobRef("a" * 64, 10).as_payload(),
            "previous_round": BlobRef("b" * 64, 20).as_payload(),
            "resolutions": [
                {
                    "previous_finding_id": "finding.second",
                    "status": "fixed",
                    "current_finding_id": None,
                },
                {
                    "previous_finding_id": "finding.first",
                    "status": "obsolete",
                    "current_finding_id": None,
                },
            ],
        },
        domain="dlstudio.review_round",
        version=1,
    )
    with pytest.raises(ValueError, match="not canonical"):
        ReviewRound.from_canonical_bytes(raw)


def test_review_round_transition_supports_three_round_issue_lineage() -> None:
    first_finding = ReviewFinding(
        "issue.first",
        "The transition is too abrupt.",
        True,
        ReviewLocator(10, 15, target_ids=("visual.000",)),
    )
    first_verdict = _verdict(
        artifact=BlobRef("a" * 64, 100),
        outcome="changes_requested",
        findings=(first_finding,),
    )
    first_round = ReviewRound(first_verdict.ref)
    validate_review_round_transition(
        first_round,
        first_verdict,
        previous_round=None,
        previous_verdict=None,
    )

    second_finding = ReviewFinding(
        "issue.second",
        "The transition is still too abrupt.",
        True,
        ReviewLocator(11, 16, target_ids=("visual.000",)),
    )
    second_verdict = _verdict(
        artifact=BlobRef("b" * 64, 100),
        outcome="changes_requested",
        findings=(second_finding,),
    )
    second_round = ReviewRound(
        second_verdict.ref,
        first_round.ref,
        (
            ReviewResolution(
                "issue.first",
                "still_wrong",
                "issue.second",
            ),
        ),
    )
    validate_review_round_transition(
        second_round,
        second_verdict,
        previous_round=first_round,
        previous_verdict=first_verdict,
    )

    final_verdict = _verdict(artifact=BlobRef("c" * 64, 100))
    final_round = ReviewRound(
        final_verdict.ref,
        second_round.ref,
        (ReviewResolution("issue.second", "fixed"),),
    )
    validate_review_round_transition(
        final_round,
        final_verdict,
        previous_round=second_round,
        previous_verdict=second_verdict,
    )


def test_block_round_keeps_required_issue_lineage_open() -> None:
    blocked_finding = ReviewFinding(
        "issue.blocked",
        "The legal card is wrong.",
        True,
    )
    blocked_verdict = _verdict(
        artifact=BlobRef("a" * 64, 100),
        outcome="block",
        findings=(blocked_finding,),
    )
    blocked_round = ReviewRound(blocked_verdict.ref)
    validate_review_round_transition(
        blocked_round,
        blocked_verdict,
        previous_round=None,
        previous_verdict=None,
    )

    current_finding = ReviewFinding(
        "issue.blocked.current",
        "The legal card is still wrong.",
        True,
    )
    current_verdict = _verdict(
        artifact=BlobRef("b" * 64, 100),
        outcome="block",
        findings=(current_finding,),
    )
    current_round = ReviewRound(
        current_verdict.ref,
        blocked_round.ref,
        (
            ReviewResolution(
                "issue.blocked",
                "still_wrong",
                "issue.blocked.current",
            ),
        ),
    )
    validate_review_round_transition(
        current_round,
        current_verdict,
        previous_round=blocked_round,
        previous_verdict=blocked_verdict,
    )


def test_review_round_transition_requires_exact_complete_resolutions() -> None:
    previous_finding = ReviewFinding(
        "issue.previous",
        "Move this title.",
        True,
    )
    previous_verdict = _verdict(
        artifact=BlobRef("a" * 64, 100),
        outcome="changes_requested",
        findings=(previous_finding,),
    )
    previous_round = ReviewRound(previous_verdict.ref)
    current_verdict = _verdict(artifact=BlobRef("b" * 64, 100))

    with pytest.raises(ValueError, match="coverage"):
        validate_review_round_transition(
            ReviewRound(
                current_verdict.ref,
                previous_round.ref,
            ),
            current_verdict,
            previous_round=previous_round,
            previous_verdict=previous_verdict,
        )
    with pytest.raises(ValueError, match="coverage"):
        validate_review_round_transition(
            ReviewRound(
                current_verdict.ref,
                previous_round.ref,
                (ReviewResolution("issue.unknown", "fixed"),),
            ),
            current_verdict,
            previous_round=previous_round,
            previous_verdict=previous_verdict,
        )


def test_still_wrong_requires_a_required_current_finding() -> None:
    previous_finding = ReviewFinding(
        "issue.previous",
        "Move this title.",
        True,
    )
    previous_verdict = _verdict(
        artifact=BlobRef("a" * 64, 100),
        outcome="changes_requested",
        findings=(previous_finding,),
    )
    previous_round = ReviewRound(previous_verdict.ref)
    current_verdict = _verdict(artifact=BlobRef("b" * 64, 100))
    current_round = ReviewRound(
        current_verdict.ref,
        previous_round.ref,
        (
            ReviewResolution(
                "issue.previous",
                "still_wrong",
                "issue.current",
            ),
        ),
    )

    with pytest.raises(ValueError, match="required current finding"):
        validate_review_round_transition(
            current_round,
            current_verdict,
            previous_round=previous_round,
            previous_verdict=previous_verdict,
        )


def test_required_findings_are_the_change_requests() -> None:
    finding = ReviewFinding(
        "safe.zone",
        "Move the title down.",
        True,
        ReviewLocator(
            120,
            121,
            ReviewRegion(100, 200, 400, 180),
            ("visual.002",),
        ),
    )
    verdict = _verdict(
        outcome="changes_requested",
        findings=(finding,),
    )
    assert verdict.findings == (finding,)
    with pytest.raises(ValueError, match="cannot require"):
        _verdict(findings=(finding,))


def test_review_locator_supports_exact_frames_ranges_and_regions() -> None:
    frame = ReviewLocator(42, 43)
    time_range = ReviewLocator(
        42,
        75,
        ReviewRegion(10, 20, 300, 400),
        ("visual.003", "audio.001", "visual.003"),
    )
    assert frame.is_frame
    assert not time_range.is_frame
    assert time_range.target_ids == ("audio.001", "visual.003")
    with pytest.raises(ValueError, match="frame range"):
        ReviewLocator(12, 12)
    with pytest.raises(ValueError, match="exceeds"):
        ReviewRegion(900, 0, 101, 100)


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
