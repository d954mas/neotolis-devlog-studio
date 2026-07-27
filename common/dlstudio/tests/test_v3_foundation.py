from __future__ import annotations

import json
import hashlib
import multiprocessing
import os
import unicodedata
from pathlib import Path

import pytest

from dlstudio.foundation.api import (
    BlobRef,
    CanonicalEncodingError,
    CasConflict,
    CorruptObject,
    DomainId,
    SchemaEnvelope,
    canonical_bytes,
    canonical_hash,
    normalize_logical_path,
)
from dlstudio.persistence import ProductionRepository
from dlstudio.persistence import api as persistence_api


def _repository(
    root: Path, production_id: str = "fixture.reel"
) -> ProductionRepository:
    studio = root / production_id / "data" / ".studio"
    return ProductionRepository(
        object_root=studio / "objects",
        state_root=studio / "state",
        staging_root=studio / "staging",
        lock_root=studio / "locks",
        production_id=production_id,
    )


def _hold_lease(path: str, ready: multiprocessing.Queue[str]) -> None:
    from dlstudio.persistence.api import WriterLease

    with WriterLease(Path(path)):
        ready.put("locked")
        ready.get(timeout=5)


def _crash_with_lease(path: str, ready: multiprocessing.Queue[str]) -> None:
    from dlstudio.persistence.api import WriterLease

    WriterLease(Path(path)).acquire()
    ready.put("locked")
    ready.get(timeout=5)
    os._exit(17)


def test_canonical_vector_is_normalized_and_stable() -> None:
    decomposed = unicodedata.normalize("NFD", "Тест")
    payload = {"z": 2, "name": decomposed, "value": -0.0}
    assert canonical_bytes(payload, domain="studio.fixture") == (
        b'{"$domain":"studio.fixture","$version":1,'
        b'"payload":{"name":"\xd0\xa2\xd0\xb5\xd1\x81\xd1\x82",'
        b'"value":0.0,"z":2}}'
    )
    assert canonical_hash(payload, domain="studio.fixture") == (
        "6a684609036858b6eba4ae750a90fa2e1397d0f84747485cb4d8faf3618a7d94"
    )


@pytest.mark.parametrize("value", [float("nan"), float("inf"), float("-inf")])
def test_canonical_rejects_nonfinite_floats(value: float) -> None:
    with pytest.raises(CanonicalEncodingError):
        canonical_bytes({"value": value}, domain="studio.fixture")


def test_domain_id_canonicalizes_as_scalar() -> None:
    assert canonical_bytes(
        {"id": DomainId("2026_07_18_reel_02")},
        domain="studio.fixture",
    ) == (
        b'{"$domain":"studio.fixture","$version":1,'
        b'"payload":{"id":"2026_07_18_reel_02"}}'
    )


def test_semantic_mappings_are_defensively_frozen(tmp_path: Path) -> None:
    nested: dict[str, object] = {"items": ["first"]}
    envelope = SchemaEnvelope("studio.fixture", 1, nested)
    nested["items"].append("mutated")  # type: ignore[union-attr]
    assert envelope.payload["items"] == ("first",)
    with pytest.raises(TypeError):
        envelope.payload["new"] = "value"  # type: ignore[index]

    records: dict[str, BlobRef] = {}
    root = persistence_api.ProductionStateRoot("fixture.reel", 0, records)
    records["late"] = BlobRef("0" * 64, 0)
    assert "late" not in root.records
    with pytest.raises(TypeError):
        root.records["late"] = BlobRef("0" * 64, 0)  # type: ignore[index]


def test_logical_paths_are_portable() -> None:
    assert normalize_logical_path(r"assets\clip.mp4") == "assets/clip.mp4"
    for value in ("/etc/passwd", r"C:\clip.mp4", "../clip.mp4"):
        with pytest.raises(CanonicalEncodingError):
            normalize_logical_path(value)


def test_real_date_prefixed_production_id_is_valid(tmp_path: Path) -> None:
    assert str(DomainId("2026_07_18_reel_02")) == "2026_07_18_reel_02"


def test_persistence_rejects_noncanonical_production_id(
    tmp_path: Path,
) -> None:
    with pytest.raises(ValueError, match="domain id"):
        _repository(tmp_path, "../outside")
    with pytest.raises(ValueError, match="domain id"):
        persistence_api.ProductionStateRoot("e\u0301", 0, {})


def test_object_store_and_head_cas(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    first = repo.objects.put_bytes(b"one")
    head = repo.update_records({"asset": first}, expected_revision=0)
    assert head.revision == 1
    assert repo.read_root().records["asset"] == first

    second = repo.objects.put_bytes(b"two")
    with pytest.raises(CasConflict):
        repo.update_records({"asset": second}, expected_revision=0)
    assert repo.read_root().records["asset"] == first


def test_root_rejects_dangling_object(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    missing = BlobRef("0" * 64, 1)
    with pytest.raises(Exception, match="missing or wrong-sized"):
        repo.update_records({"missing": missing}, expected_revision=0)
    assert repo.read_head() is None


def test_crash_before_head_swap_leaves_previous_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    repo = _repository(tmp_path)
    first = repo.objects.put_bytes(b"one")
    repo.update_records({"asset": first}, expected_revision=0)
    old_head = repo.read_head()
    second = repo.objects.put_bytes(b"two")
    real_atomic_write = persistence_api._atomic_write

    def fail_head(path: Path, data: bytes) -> None:
        if path == repo.head_path:
            raise KeyboardInterrupt("simulated termination before head swap")
        real_atomic_write(path, data)

    monkeypatch.setattr(persistence_api, "_atomic_write", fail_head)
    with pytest.raises(KeyboardInterrupt):
        repo.update_records({"asset": second}, expected_revision=1)
    assert repo.read_head() == old_head
    assert repo.read_root().records["asset"] == first


def test_commit_rejects_corrupt_preexisting_immutable_root(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    ref = repo.objects.put_bytes(b"one")
    root = persistence_api.ProductionStateRoot(
        "fixture.reel", 1, {"asset": ref}
    )
    raw = canonical_bytes(
        root.as_payload(), domain=repo.ROOT_SCHEMA, version=1
    )
    root_hash = hashlib.sha256(raw).hexdigest()
    repo.roots_path.mkdir(parents=True)
    (repo.roots_path / f"{root_hash}.json").write_bytes(b"corrupt")
    with pytest.raises(CorruptObject, match="collision"):
        repo._commit_root(
            root,
            expected_revision=0,
            allowed_reserved_keys=frozenset(),
        )
    assert repo.read_head() is None


def test_two_contexts_share_no_state(tmp_path: Path) -> None:
    one = _repository(tmp_path, "one.reel")
    two = _repository(tmp_path, "two.reel")
    one.update_records({"x": one.objects.put_bytes(b"one")}, expected_revision=0)
    two.update_records({"x": two.objects.put_bytes(b"two")}, expected_revision=0)
    assert one.objects.read(one.read_root().records["x"]) == b"one"
    assert two.objects.read(two.read_root().records["x"]) == b"two"


def test_root_keeps_only_current_owner_records(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    expected_revision = 0
    for index in range(50):
        current = repo.objects.put_bytes(f"revision-{index}".encode())
        repo.update_records(
            {"projection:current": current},
            expected_revision=expected_revision,
        )
        expected_revision += 1

    root = repo.read_root()
    assert root.revision == 50
    assert root.records == {"projection:current": current}
    assert not any(key.startswith("operation:") for key in root.records)


def test_writer_lease_blocks_spawned_process(tmp_path: Path) -> None:
    path = tmp_path / "writer.lock"
    ready: multiprocessing.Queue[str] = multiprocessing.Queue()
    process = multiprocessing.Process(target=_hold_lease, args=(str(path), ready))
    process.start()
    assert ready.get(timeout=5) == "locked"
    from dlstudio.persistence.api import WriterLease

    with pytest.raises(TimeoutError):
        WriterLease(path, timeout=0.15, poll_interval=0.02).acquire()
    ready.put("release")
    process.join(timeout=5)
    assert process.exitcode == 0
    with WriterLease(path, timeout=1):
        assert path.exists()


def test_writer_lease_recovers_crash_between_create_and_record(
    tmp_path: Path,
) -> None:
    path = tmp_path / "writer.lock"
    path.write_bytes(b"")
    from dlstudio.persistence.api import WriterLease

    with WriterLease(path, timeout=1, poll_interval=0.02):
        assert path.exists()
    payload = json.loads(path.read_bytes()[1:].decode("utf-8"))
    assert payload["pid"] == os.getpid()


def test_writer_lease_recovers_after_forced_process_termination(
    tmp_path: Path,
) -> None:
    path = tmp_path / "writer.lock"
    ready: multiprocessing.Queue[str] = multiprocessing.Queue()
    process = multiprocessing.Process(target=_crash_with_lease, args=(str(path), ready))
    process.start()
    assert ready.get(timeout=5) == "locked"
    ready.put("crash")
    process.join(timeout=5)
    assert process.exitcode == 17

    from dlstudio.persistence.api import WriterLease

    with WriterLease(path, timeout=1):
        assert path.exists()
