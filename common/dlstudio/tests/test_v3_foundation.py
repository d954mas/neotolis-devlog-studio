from __future__ import annotations

import json
import hashlib
import multiprocessing
import os
import unicodedata
from collections.abc import Iterator, Mapping
from pathlib import Path

import pytest

from dlstudio.application.api import ProductionContext
from dlstudio.foundation.api import (
    CanonicalEncodingError,
    CasConflict,
    CorruptObject,
    DomainId,
    SchemaEnvelope,
    canonical_bytes,
    canonical_hash,
    normalize_logical_path,
)
from dlstudio.persistence import (
    ObjectRef,
    OperationTransaction,
    ProductionRepository,
)
from dlstudio.persistence import api as persistence_api


def _context(root: Path, production_id: str = "fixture.reel") -> ProductionContext:
    return ProductionContext.create(
        workspace_root=root,
        project_root=root,
        production_id=production_id,
        production_root=root / production_id,
    )


def _repository(
    root: Path, production_id: str = "fixture.reel"
) -> ProductionRepository:
    paths = _context(root, production_id).paths
    return ProductionRepository(
        object_root=paths.object_root,
        state_root=paths.state_root,
        staging_root=paths.staging_root,
        lock_root=paths.lock_root,
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

    values = {"ffmpeg_build": "one"}
    bindings = _context(tmp_path).machine_bindings
    custom = type(bindings)(values=values)
    values["ffmpeg_build"] = "two"
    assert custom.values["ffmpeg_build"] == "one"

    records: dict[str, ObjectRef] = {}
    root = persistence_api.ProductionStateRoot("fixture.reel", 0, records)
    records["late"] = ObjectRef("0" * 64, 0)
    assert "late" not in root.records
    with pytest.raises(TypeError):
        root.records["late"] = ObjectRef("0" * 64, 0)  # type: ignore[index]


def test_logical_paths_are_portable() -> None:
    assert normalize_logical_path(r"assets\clip.mp4") == "assets/clip.mp4"
    for value in ("/etc/passwd", r"C:\clip.mp4", "../clip.mp4"):
        with pytest.raises(CanonicalEncodingError):
            normalize_logical_path(value)


def test_real_date_prefixed_production_id_is_valid(tmp_path: Path) -> None:
    context = _context(tmp_path, "2026_07_18_reel_02")
    assert str(context.production_id) == "2026_07_18_reel_02"


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
    missing = ObjectRef("0" * 64, 1)
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
        repo._commit_root(root, expected_revision=0, operation_key=None)
    assert repo.read_head() is None


def test_two_contexts_share_no_state(tmp_path: Path) -> None:
    one = _repository(tmp_path, "one.reel")
    two = _repository(tmp_path, "two.reel")
    one.update_records({"x": one.objects.put_bytes(b"one")}, expected_revision=0)
    two.update_records({"x": two.objects.put_bytes(b"two")}, expected_revision=0)
    assert one.objects.read(one.read_root().records["x"]) == b"one"
    assert two.objects.read(two.read_root().records["x"]) == b"two"


def test_operation_prepare_is_idempotent_and_input_bound(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    operation_id = OperationTransaction.derive_id(
        production_id="fixture.reel",
        contract="compile.v1",
        inputs={"asset": "abc"},
        implementation="source-1",
        toolchain="python-3.12",
    )
    tx = OperationTransaction(
        repo, operation_id=operation_id, inputs={"asset": "abc"}
    )
    assert tx.prepare() == tx.prepare()
    payload = json.loads(tx.record_path.read_text(encoding="utf-8"))
    assert payload["state"] == "prepared"
    with pytest.raises(TypeError):
        tx.inputs["asset"] = "different"  # type: ignore[index]
    tx.close()


@pytest.mark.parametrize(
    "operation_id",
    ["../outside", "A" * 64, "a" * 63, "/absolute", r"..\outside"],
)
def test_operation_id_cannot_escape_staging(
    tmp_path: Path, operation_id: str
) -> None:
    repo = _repository(tmp_path)
    with pytest.raises(ValueError, match="64 lowercase hex"):
        OperationTransaction(repo, operation_id=operation_id, inputs={})


def test_prepare_reconciles_unrecorded_crash_stage(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    tx = OperationTransaction(
        repo, operation_id="a" * 64, inputs={"asset": "abc"}
    )
    tx.stage.mkdir(parents=True)
    (tx.stage / "partial.bin").write_bytes(b"untrusted")
    tx.prepare()
    assert not (tx.stage / "partial.bin").exists()
    assert tx.record_path.is_file()
    tx.close()


def test_operation_commit_and_resume_have_one_canonical_attempt(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    operation_id = OperationTransaction.derive_id(
        production_id="fixture.reel",
        contract="render.v1",
        inputs={"ir": "abc"},
        implementation="source-1",
        toolchain="ffmpeg-7",
    )
    tx = OperationTransaction(
        repo, operation_id=operation_id, inputs={"ir": "abc"}
    )
    stage = tx.prepare()
    artifact_path = stage / "artifact.mp4"
    artifact_path.write_bytes(b"rendered")
    artifact = tx.publish_file(artifact_path)
    head = tx.commit(outputs={"artifact": artifact}, expected_revision=0)
    assert head.revision == 1

    resumed = OperationTransaction(
        repo, operation_id=operation_id, inputs={"ir": "abc"}
    )
    resumed.prepare()
    assert resumed.committed_outputs == {"artifact": artifact}
    later = repo.objects.put_bytes(b"later")
    later_head = repo.update_records({"later": later}, expected_revision=1)
    assert later_head.revision == 2
    assert resumed.commit(outputs={"artifact": artifact}, expected_revision=0) == head
    resumed.prepare()
    with pytest.raises(CasConflict, match="outputs differ"):
        resumed.commit(
            outputs={"artifact": later},
            expected_revision=0,
        )
    resumed.prepare()
    with pytest.raises(CasConflict, match="expected revision"):
        resumed.commit(outputs={"artifact": artifact}, expected_revision=1)
    resumed.close()


def test_operation_mutation_requires_live_lease(tmp_path: Path) -> None:
    repo = _repository(tmp_path)
    tx = OperationTransaction(repo, operation_id="b" * 64, inputs={})
    stage = tx.prepare()
    artifact_path = stage / "artifact.bin"
    artifact_path.write_bytes(b"bytes")
    artifact = tx.publish_file(artifact_path)
    tx.close()

    with pytest.raises(RuntimeError, match="lease"):
        tx.commit(outputs={"artifact": artifact}, expected_revision=0)
    with pytest.raises(RuntimeError, match="prepare"):
        tx.publish_file(artifact_path)

    owner = OperationTransaction(repo, operation_id="b" * 64, inputs={})
    owner.prepare()
    tx._lease.timeout = 0.1
    tx._lease.poll_interval = 0.01
    with pytest.raises(TimeoutError):
        tx.abandon()
    assert owner.stage.is_dir()
    owner.close()
    tx.abandon()
    assert not tx.stage.exists()


def test_failed_operation_commit_releases_lease_and_reserves_namespace(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    tx = OperationTransaction(repo, operation_id="c" * 64, inputs={})
    tx.prepare()
    with pytest.raises(ValueError, match="namespace"):
        tx.commit(
            outputs={},
            record_updates={"operation:" + "d" * 64: ObjectRef("0" * 64, 0)},
            expected_revision=0,
        )
    with OperationTransaction(
        repo, operation_id="c" * 64, inputs={}
    ) as resumed:
        assert resumed.stage.is_dir()

    with pytest.raises(ValueError, match="namespace"):
        repo.update_records(
            {"operation:" + "d" * 64: ObjectRef("0" * 64, 0)},
            expected_revision=0,
        )
    assert not hasattr(repo, "commit_root")


def test_internal_root_transition_cannot_remove_operation_record(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    tx = OperationTransaction(repo, operation_id="f" * 64, inputs={})
    tx.prepare()
    committed_head = tx.commit(outputs={}, expected_revision=0)
    committed_root = repo.read_root(committed_head)
    stripped = persistence_api.ProductionStateRoot(
        "fixture.reel",
        2,
        {
            key: ref
            for key, ref in committed_root.records.items()
            if not key.startswith("operation:")
        },
        committed_head.root_hash,
    )
    with pytest.raises(ValueError, match="namespace transition"):
        repo._commit_root(
            stripped,
            expected_revision=1,
            operation_key=None,
        )
    assert repo.read_head() == committed_head


def test_operation_snapshots_adversarial_output_mapping(
    tmp_path: Path,
) -> None:
    repo = _repository(tmp_path)
    good = repo.objects.put_bytes(b"good")
    missing = ObjectRef("0" * 64, 1)

    class ChangingOutputs(Mapping[str, ObjectRef]):
        calls = 0

        def __getitem__(self, key: str) -> ObjectRef:
            self.calls += 1
            return good if self.calls == 1 else missing

        def __iter__(self) -> Iterator[str]:
            yield "artifact"

        def __len__(self) -> int:
            return 1

    tx = OperationTransaction(repo, operation_id="e" * 64, inputs={})
    tx.prepare()
    outputs = ChangingOutputs()
    head = tx.commit(outputs=outputs, expected_revision=0)
    committed = repo.read_root(head).records[tx.root_record_key]
    record = json.loads(repo.objects.read(committed))
    assert record["payload"]["outputs"]["artifact"]["sha256"] == good.sha256


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
