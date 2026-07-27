from __future__ import annotations

import pytest

from dlstudio.constraints.api import Constraint, ConstraintSet


def test_constraint_set_is_small_canonical_owner() -> None:
    first = ConstraintSet(
        production_id="fixture.reel",
        source="production.toml",
        constraints=(
            Constraint("safe.zone", "Keep text inside the safe zone."),
            Constraint("hook", "Name the product in the first second.", "blocker"),
        ),
    )
    reordered = ConstraintSet(
        production_id="fixture.reel",
        source="production.toml",
        constraints=tuple(reversed(first.constraints)),
    )
    assert first.ref == reordered.ref
    assert ConstraintSet.from_canonical_bytes(first.canonical_bytes()) == first


def test_constraint_revision_is_just_exact_superseded_content() -> None:
    first = ConstraintSet(
        "fixture.reel",
        "user",
        (Constraint("hook", "Open with the product.", "blocker"),),
    )
    second = ConstraintSet(
        "fixture.reel",
        "user",
        (Constraint("hook", "Open with the product problem.", "blocker"),),
        supersedes=first.ref,
    )
    assert second.ref != first.ref
    assert second.supersedes == first.ref


def test_duplicate_constraint_id_is_rejected() -> None:
    duplicate = Constraint("hook", "One")
    with pytest.raises(ValueError, match="duplicate"):
        ConstraintSet("fixture.reel", "user", (duplicate, duplicate))
