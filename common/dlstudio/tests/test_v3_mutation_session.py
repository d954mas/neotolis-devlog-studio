from __future__ import annotations

import hashlib
from pathlib import Path

import pytest

from dlstudio.foundation.api import CasConflict
from dlstudio.persistence import (
    MutationSession,
    ProductionRepository,
    RecoveryRequired,
)


def _repository(tmp_path: Path) -> ProductionRepository:
    studio = tmp_path / ".studio"
    return ProductionRepository(
        object_root=studio / "objects",
        state_root=studio / "state",
        staging_root=studio / "staging",
        lock_root=studio / "locks",
        production_id="fixture.reel",
    )


def test_mutation_session_holds_writer_lease_from_read_through_commit(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    value = repo.objects.put_bytes(b"value")
    operation_id = hashlib.sha256(b"mutation").hexdigest()
    with MutationSession(
        repo, operation_id=operation_id, expected_revision=0
    ) as session:
        assert session.root.revision == 0
        contender = repo.writer_lease(timeout=0.05)
        with pytest.raises(TimeoutError):
            contender.acquire()
        head = session.commit_records({"plain": value})
        assert head.revision == 1
        assert session.root.records["plain"] == value


def test_recovery_marker_blocks_every_canonical_mutation_until_reconciled(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    operation_id = hashlib.sha256(b"delivery").hexdigest()
    with MutationSession(
        repo, operation_id=operation_id, expected_revision=0
    ) as session:
        marker_hash = session.write_recovery_marker(
            {"kind": "delivery", "candidate_id": "c" * 64}
        )

    value = repo.objects.put_bytes(b"blocked")
    with pytest.raises(RecoveryRequired, match="unresolved recovery"):
        repo.update_records({"plain": value}, expected_revision=0)
    other = hashlib.sha256(b"other").hexdigest()
    with pytest.raises(RecoveryRequired, match="unresolved recovery"):
        MutationSession(
            repo, operation_id=other, expected_revision=0
        ).open()

    with MutationSession(
        repo,
        operation_id=operation_id,
        expected_revision=0,
        allow_recovery=True,
    ) as recovery:
        assert recovery.read_recovery_marker()["kind"] == "delivery"
        recovery.clear_recovery_marker(expected_hash=marker_hash)

    assert repo.update_records({"plain": value}, expected_revision=0).revision == 1


def test_recovery_session_rejects_missing_or_changed_marker(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    operation_id = hashlib.sha256(b"delivery").hexdigest()
    with pytest.raises(RecoveryRequired, match="does not exist"):
        MutationSession(
            repo,
            operation_id=operation_id,
            expected_revision=0,
            allow_recovery=True,
        ).open()

    with MutationSession(
        repo, operation_id=operation_id, expected_revision=0
    ) as session:
        marker_hash = session.write_recovery_marker({"kind": "delivery"})
    marker = (
        repo.staging_root / "recovery" / operation_id / "recovery.json"
    )
    marker.write_bytes(marker.read_bytes() + b" ")
    with MutationSession(
        repo,
        operation_id=operation_id,
        expected_revision=0,
        allow_recovery=True,
    ) as recovery:
        with pytest.raises(CasConflict, match="hash changed"):
            recovery.clear_recovery_marker(expected_hash=marker_hash)


def test_public_update_cannot_write_phase4_owner_namespaces(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    ref = repo.objects.put_bytes(b"owned")
    for key in (
        "constraint_set:" + "a" * 64,
        "review_verdict:" + "b" * 64,
        "workflow_run:fixture",
        "release_candidate:" + "c" * 64,
        "delivery_receipt:" + "d" * 64,
        "constraints:current",
        "workflow:current",
        "release:eligible",
        "release:receipt",
    ):
        with pytest.raises(ValueError, match="namespace"):
            repo.update_records({key: ref}, expected_revision=0)
        with MutationSession(
            repo,
            operation_id=hashlib.sha256(key.encode("utf-8")).hexdigest(),
            expected_revision=0,
        ) as session:
            with pytest.raises(ValueError, match="namespace"):
                session.commit_records({key: ref})


def test_committed_head_can_be_reconciled_before_marker_clear(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    operation_id = hashlib.sha256(b"promoted-delivery").hexdigest()
    receipt = repo.objects.put_bytes(b"receipt")
    receipt_key = "delivery_receipt:" + hashlib.sha256(b"receipt").hexdigest()
    with MutationSession(
        repo, operation_id=operation_id, expected_revision=0
    ) as session:
        marker_hash = session.write_recovery_marker(
            {"kind": "delivery", "receipt_key": receipt_key}
        )
        session._commit_owned_records(
            {receipt_key: receipt},
            owned_record_keys=frozenset({receipt_key}),
        )
        # Simulated process death: the committed head is durable but marker
        # cleanup did not execute.

    with MutationSession(
        repo,
        operation_id=operation_id,
        expected_revision=0,
        allow_recovery=True,
    ) as recovery:
        assert recovery.head is not None
        assert recovery.head.revision == 1
        assert recovery.read_recovery_marker()["receipt_key"] == receipt_key
        recovery.clear_recovery_marker(expected_hash=marker_hash)
    assert repo.update_records(
        {"after": repo.objects.put_bytes(b"after")}, expected_revision=1
    ).revision == 2


def test_operation_transaction_cannot_remove_recovery_marker_with_same_id(
    tmp_path: Path,
) -> None:
    from dlstudio.persistence import OperationTransaction

    repo = _repository(tmp_path)
    operation_id = hashlib.sha256(b"shared-id").hexdigest()
    with MutationSession(
        repo, operation_id=operation_id, expected_revision=0
    ) as session:
        session.write_recovery_marker({"kind": "delivery"})

    transaction = OperationTransaction(
        repo, operation_id=operation_id, inputs={}
    )
    with pytest.raises(RecoveryRequired, match="its unresolved"):
        transaction.prepare()
    marker = (
        repo.staging_root / "recovery" / operation_id / "recovery.json"
    )
    assert marker.is_file()
    with pytest.raises(RecoveryRequired):
        repo.update_records(
            {"blocked": repo.objects.put_bytes(b"blocked")},
            expected_revision=0,
        )
