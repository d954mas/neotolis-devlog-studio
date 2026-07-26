"""Crash-safe filesystem repositories for Studio v3.

The only mutable canonical file is ``state/head.json``. Immutable bytes are
published first; the head advances with a same-directory replace under a
single production writer lease and an expected-revision comparison.
"""

from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import socket
import tempfile
import time
import uuid
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from types import MappingProxyType
from typing import Any, BinaryIO

from dlstudio.assets.api import BlobRef
from dlstudio.foundation.api import (
    CasConflict,
    CorruptObject,
    DomainId,
    StudioError,
    canonical_bytes,
    canonical_hash,
)

_RESERVED_RECORD_PREFIXES = (
    "operation:",
    "asset_revision:",
    "constraint_set:",
    "review_verdict:",
    "workflow_run:",
    "release_candidate:",
    "delivery_receipt:",
)
_RESERVED_RECORD_KEYS = frozenset(
    {
        "assets:index",
        "constraints:current",
        "workflow:current",
        "release:eligible",
        "release:receipt",
    }
)


def _reserved_record(key: str) -> bool:
    return key in _RESERVED_RECORD_KEYS or key.startswith(
        _RESERVED_RECORD_PREFIXES
    )


def _fsync_dir(path: Path) -> None:
    if os.name == "nt":
        return
    fd = os.open(path, os.O_RDONLY)
    try:
        os.fsync(fd)
    finally:
        os.close(fd)


def _atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, raw_tmp = tempfile.mkstemp(prefix=f".{path.name}.", dir=path.parent)
    tmp = Path(raw_tmp)
    try:
        with os.fdopen(fd, "wb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(tmp, path)
        _fsync_dir(path.parent)
    finally:
        tmp.unlink(missing_ok=True)


class RecoveryRequired(StudioError):
    """A visible side effect must be reconciled before canonical mutation."""


class ObjectStore:
    def __init__(self, root: Path, staging_root: Path) -> None:
        self.root = root
        self.staging_root = staging_root

    def path_for(self, ref: BlobRef) -> Path:
        return self.root / ref.sha256

    def put_bytes(self, data: bytes) -> BlobRef:
        ref = BlobRef(hashlib.sha256(data).hexdigest(), len(data))
        target = self.path_for(ref)
        if target.exists():
            self.verify(ref)
            return ref
        target.parent.mkdir(parents=True, exist_ok=True)
        stage = self.staging_root / f"object-{uuid.uuid4().hex}"
        stage.parent.mkdir(parents=True, exist_ok=True)
        try:
            with stage.open("xb") as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
            if hashlib.sha256(stage.read_bytes()).hexdigest() != ref.sha256:
                raise CorruptObject("staged bytes changed before publish")
            try:
                os.replace(stage, target)
            except FileExistsError:
                stage.unlink(missing_ok=True)
            _fsync_dir(target.parent)
            self.verify(ref)
            return ref
        finally:
            stage.unlink(missing_ok=True)

    def ingest_file(self, source: Path) -> BlobRef:
        hasher = hashlib.sha256()
        size = 0
        source = source.resolve()
        stage = self.staging_root / f"ingest-{uuid.uuid4().hex}"
        stage.parent.mkdir(parents=True, exist_ok=True)
        try:
            with source.open("rb") as src, stage.open("xb") as dst:
                while chunk := src.read(1024 * 1024):
                    hasher.update(chunk)
                    size += len(chunk)
                    dst.write(chunk)
                dst.flush()
                os.fsync(dst.fileno())
            ref = BlobRef(hasher.hexdigest(), size)
            target = self.path_for(ref)
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                self.verify(ref)
            else:
                os.replace(stage, target)
                _fsync_dir(target.parent)
                self.verify(ref)
            return ref
        finally:
            stage.unlink(missing_ok=True)

    def read(self, ref: BlobRef) -> bytes:
        self.verify(ref)
        return self.path_for(ref).read_bytes()

    def verify(self, ref: BlobRef) -> None:
        path = self.path_for(ref)
        if not path.is_file() or path.stat().st_size != ref.size:
            raise CorruptObject(f"missing or wrong-sized object {ref.sha256}")
        hasher = hashlib.sha256()
        with path.open("rb") as handle:
            while chunk := handle.read(1024 * 1024):
                hasher.update(chunk)
        if hasher.hexdigest() != ref.sha256:
            raise CorruptObject(f"hash mismatch for object {ref.sha256}")


@dataclass(frozen=True, slots=True)
class ProductionStateRoot:
    production_id: str
    revision: int
    records: Mapping[str, BlobRef] = field(default_factory=dict)
    parent_root_hash: str | None = None

    def __post_init__(self) -> None:
        DomainId(self.production_id)
        if self.revision < 0:
            raise ValueError("negative state revision")
        if self.parent_root_hash is not None and (
            re.fullmatch(r"[0-9a-f]{64}", self.parent_root_hash) is None
        ):
            raise ValueError("invalid parent root hash")
        if (
            self.revision > 1
            and self.parent_root_hash is None
        ) or (
            self.revision <= 1
            and self.parent_root_hash is not None
        ):
            raise ValueError(
                "root parent does not match its revision"
            )
        object.__setattr__(
            self, "records", MappingProxyType(dict(self.records))
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "production_id": self.production_id,
            "revision": self.revision,
            "parent_root_hash": self.parent_root_hash,
            "records": {
                key: ref.as_payload()
                for key, ref in sorted(self.records.items())
            },
        }


@dataclass(frozen=True, slots=True)
class HeadRef:
    root_hash: str
    revision: int

    def __post_init__(self) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", self.root_hash) is None:
            raise ValueError("invalid root hash")
        if self.revision < 1:
            raise ValueError("head revision must be positive")


class WriterLease:
    """A crash-recoverable, cross-process exclusive OS file lease.

    The kernel owns exclusion, so process termination releases the lease even
    if the diagnostic JSON is empty or stale. The file contents are never used
    to decide ownership.
    """

    def __init__(
        self,
        path: Path,
        *,
        timeout: float = 30.0,
        poll_interval: float = 0.05,
    ) -> None:
        self.path = path
        self.timeout = timeout
        self.poll_interval = poll_interval
        self._nonce = uuid.uuid4().hex
        self._held = False
        self._handle: BinaryIO | None = None

    @property
    def held(self) -> bool:
        return self._held

    @staticmethod
    def _try_lock(handle: BinaryIO) -> bool:
        handle.seek(0)
        try:
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
        except OSError:
            return False
        return True

    @staticmethod
    def _unlock(handle: BinaryIO) -> None:
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_UN)

    def acquire(self) -> "WriterLease":
        deadline = time.monotonic() + self.timeout
        self.path.parent.mkdir(parents=True, exist_ok=True)
        payload = json.dumps(
            {
                "pid": os.getpid(),
                "nonce": self._nonce,
                "host": socket.gethostname(),
            },
            sort_keys=True,
        ).encode("utf-8")
        while True:
            handle = self.path.open("a+b")
            if self.path.stat().st_size == 0:
                handle.write(b"\0")
                handle.flush()
            if self._try_lock(handle):
                # Byte zero is a permanent lock sentinel. Diagnostics start at
                # byte one, so rewriting them never exposes a zero-length file
                # to contenders on Windows.
                handle.seek(1)
                handle.truncate()
                handle.write(payload)
                handle.flush()
                os.fsync(handle.fileno())
                self._handle = handle
                self._held = True
                return self
            handle.close()
            if time.monotonic() >= deadline:
                raise TimeoutError(f"writer lease is busy: {self.path}")
            time.sleep(self.poll_interval)

    def release(self) -> None:
        if not self._held:
            return
        assert self._handle is not None
        self._unlock(self._handle)
        self._handle.close()
        self._handle = None
        self._held = False

    def __enter__(self) -> "WriterLease":
        return self.acquire()

    def __exit__(self, *_exc: object) -> None:
        self.release()


class ProductionRepository:
    HEAD_SCHEMA = "dlstudio.production_head"
    ROOT_SCHEMA = "dlstudio.production_root"

    def __init__(
        self,
        *,
        object_root: Path,
        state_root: Path,
        staging_root: Path,
        lock_root: Path,
        production_id: str,
    ) -> None:
        self.object_root = object_root
        self.state_root = state_root
        self.staging_root = staging_root
        self.lock_root = lock_root
        self.production_id = str(DomainId(production_id))
        self.objects = ObjectStore(object_root, staging_root)

    @property
    def head_path(self) -> Path:
        return self.state_root / "head.json"

    @property
    def roots_path(self) -> Path:
        return self.state_root / "roots"

    def writer_lease(self, *, timeout: float = 30.0) -> WriterLease:
        return WriterLease(
            self.lock_root / "production.writer", timeout=timeout
        )

    def pending_recovery_markers(self) -> tuple[Path, ...]:
        """Return durable recovery markers without interpreting domain payloads."""

        if not self.staging_root.is_dir():
            return ()
        return tuple(
            sorted(
                (
                    path
                    for path in self.staging_root.glob("*/recovery.json")
                    if path.is_file()
                ),
                key=lambda path: path.as_posix(),
            )
        )

    def _assert_no_pending_recovery_under_lease(
        self, *, allowed: Path | None = None
    ) -> None:
        pending = tuple(
            path
            for path in self.pending_recovery_markers()
            if allowed is None or path.resolve() != allowed.resolve()
        )
        if pending:
            relative = ", ".join(
                path.relative_to(self.staging_root).as_posix()
                for path in pending
            )
            raise RecoveryRequired(
                "canonical mutation is blocked by unresolved recovery: "
                f"{relative}"
            )

    def read_head(self) -> HeadRef | None:
        if not self.head_path.exists():
            return None
        payload = json.loads(self.head_path.read_text(encoding="utf-8"))
        if (
            payload.get("schema") != self.HEAD_SCHEMA
            or payload.get("version") != 1
        ):
            raise CorruptObject("invalid production head schema")
        head = HeadRef(
            root_hash=str(payload["root_hash"]),
            revision=int(payload["revision"]),
        )
        self.read_root(head)
        return head

    def read_root(self, head: HeadRef | None = None) -> ProductionStateRoot:
        selected = head or self.read_head()
        if selected is None:
            return ProductionStateRoot(self.production_id, 0, {})
        path = self.roots_path / f"{selected.root_hash}.json"
        raw = path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != selected.root_hash:
            raise CorruptObject("production root filename/hash mismatch")
        wrapped = json.loads(raw.decode("utf-8"))
        if (
            wrapped.get("$domain") != self.ROOT_SCHEMA
            or wrapped.get("$version") != 1
        ):
            raise CorruptObject("invalid production root schema")
        payload = wrapped["payload"]
        root = ProductionStateRoot(
            production_id=str(payload["production_id"]),
            revision=int(payload["revision"]),
            records={
                key: BlobRef(
                    sha256=str(value["sha256"]), size=int(value["size"])
                )
                for key, value in payload["records"].items()
            },
            parent_root_hash=(
                None
                if payload["parent_root_hash"] is None
                else str(payload["parent_root_hash"])
            ),
        )
        if (
            root.production_id != self.production_id
            or root.revision != selected.revision
        ):
            raise CorruptObject("production root does not match head")
        for ref in root.records.values():
            self.objects.verify(ref)
        return root

    def _commit_root(
        self,
        root: ProductionStateRoot,
        *,
        expected_revision: int,
        allowed_reserved_keys: frozenset[str],
    ) -> HeadRef:
        with self.writer_lease():
            self._assert_no_pending_recovery_under_lease()
            return self._commit_root_under_lease(
                root,
                expected_revision=expected_revision,
                allowed_reserved_keys=allowed_reserved_keys,
            )

    def _commit_root_under_lease(
        self,
        root: ProductionStateRoot,
        *,
        expected_revision: int,
        allowed_reserved_keys: frozenset[str],
    ) -> HeadRef:
        if root.production_id != self.production_id:
            raise ValueError("wrong production id")
        if root.revision != expected_revision + 1:
            raise ValueError("new root must increment expected revision once")
        current = self.read_head()
        actual = 0 if current is None else current.revision
        if actual != expected_revision:
            raise CasConflict(
                f"expected head revision {expected_revision}, got {actual}"
            )
        expected_parent = None if current is None else current.root_hash
        if root.parent_root_hash != expected_parent:
            raise CasConflict(
                "new root parent does not match the canonical head"
            )
        current_root = self.read_root(current)
        previous_reserved = {
            key: ref
            for key, ref in current_root.records.items()
            if _reserved_record(key)
        }
        next_reserved = {
            key: ref
            for key, ref in root.records.items()
            if _reserved_record(key)
        }
        changed_reserved = {
            key
            for key in previous_reserved.keys() | next_reserved.keys()
            if previous_reserved.get(key) != next_reserved.get(key)
        }
        if changed_reserved != allowed_reserved_keys:
            raise ValueError(
                "reserved record transition does not match its owner"
            )
        for key in changed_reserved:
            if key.startswith(
                (
                    "operation:",
                    "asset_revision:",
                    "constraint_set:",
                    "review_verdict:",
                    "release_candidate:",
                    "delivery_receipt:",
                )
            ) and (key in previous_reserved or key not in next_reserved):
                raise CasConflict(
                    f"immutable reserved record cannot change: {key}"
                )
            if key in {
                "assets:index",
                "constraints:current",
                "workflow:current",
                "release:eligible",
                "release:receipt",
            } and key not in next_reserved:
                raise ValueError(f"canonical owner record cannot be removed: {key}")
        for ref in root.records.values():
            self.objects.verify(ref)
        raw = canonical_bytes(
            root.as_payload(), domain=self.ROOT_SCHEMA, version=1
        )
        root_hash = hashlib.sha256(raw).hexdigest()
        root_path = self.roots_path / f"{root_hash}.json"
        if not root_path.exists():
            _atomic_write(root_path, raw)
        elif root_path.read_bytes() != raw:
            raise CorruptObject(
                f"immutable production root collision at {root_hash}"
            )
        head = {
            "schema": self.HEAD_SCHEMA,
            "version": 1,
            "root_hash": root_hash,
            "revision": root.revision,
        }
        _atomic_write(
            self.head_path,
            json.dumps(
                head, sort_keys=True, separators=(",", ":")
            ).encode("utf-8"),
        )
        return HeadRef(root_hash, root.revision)

    def update_records(
        self,
        records: Mapping[str, BlobRef],
        *,
        expected_revision: int,
    ) -> HeadRef:
        return self._update_records(
            records,
            expected_revision=expected_revision,
            allowed_reserved_keys=frozenset(),
        )

    def _update_records(
        self,
        records: Mapping[str, BlobRef],
        *,
        expected_revision: int,
        allowed_reserved_keys: frozenset[str],
    ) -> HeadRef:
        with self.writer_lease():
            self._assert_no_pending_recovery_under_lease()
            return self._update_records_under_lease(
                records,
                expected_revision=expected_revision,
                allowed_reserved_keys=allowed_reserved_keys,
            )

    def _update_records_under_lease(
        self,
        records: Mapping[str, BlobRef],
        *,
        expected_revision: int,
        allowed_reserved_keys: frozenset[str],
    ) -> HeadRef:
        snapshot = dict(records)
        requested_reserved = frozenset(
            key for key in snapshot if _reserved_record(key)
        )
        if requested_reserved != allowed_reserved_keys:
            raise ValueError("reserved record namespace is owned")
        current_head = self.read_head()
        actual_revision = 0 if current_head is None else current_head.revision
        if actual_revision != expected_revision:
            raise CasConflict(
                f"expected head revision {expected_revision}, "
                f"got {actual_revision}"
            )
        current = self.read_root(current_head)
        merged = dict(current.records)
        merged.update(snapshot)
        return self._commit_root_under_lease(
            ProductionStateRoot(
                self.production_id,
                expected_revision + 1,
                merged,
                None if current_head is None else current_head.root_hash,
            ),
            expected_revision=expected_revision,
            allowed_reserved_keys=allowed_reserved_keys,
        )


class MutationSession:
    """Hold the production writer lease across validation, side effect and commit."""

    RECOVERY_SCHEMA = "dlstudio.recovery_marker"

    def __init__(
        self,
        repository: ProductionRepository,
        *,
        operation_id: str,
        expected_revision: int,
        allow_recovery: bool = False,
        timeout: float = 30.0,
    ) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", operation_id) is None:
            raise ValueError("operation_id must be exactly 64 lowercase hex")
        if expected_revision < 0:
            raise ValueError("expected revision cannot be negative")
        self.repository = repository
        self.operation_id = operation_id
        self.expected_revision = expected_revision
        self.allow_recovery = allow_recovery
        self.stage = repository.staging_root / operation_id
        self.recovery_path = self.stage / "recovery.json"
        self._lease = repository.writer_lease(timeout=timeout)
        self._head: HeadRef | None = None
        self._root: ProductionStateRoot | None = None

    @property
    def held(self) -> bool:
        return self._lease.held

    @property
    def root(self) -> ProductionStateRoot:
        if not self.held or self._root is None:
            raise RuntimeError("mutation session is not open")
        return self._root

    @property
    def head(self) -> HeadRef | None:
        if not self.held:
            raise RuntimeError("mutation session is not open")
        return self._head

    def open(self) -> "MutationSession":
        if self.held:
            return self
        self._lease.acquire()
        try:
            allowed = self.recovery_path if self.allow_recovery else None
            self.repository._assert_no_pending_recovery_under_lease(
                allowed=allowed
            )
            if self.allow_recovery and not self.recovery_path.is_file():
                raise RecoveryRequired(
                    "requested recovery marker does not exist"
                )
            self._head = self.repository.read_head()
            actual = 0 if self._head is None else self._head.revision
            if actual != self.expected_revision:
                raise CasConflict(
                    f"expected head revision {self.expected_revision}, "
                    f"got {actual}"
                )
            self._root = self.repository.read_root(self._head)
            return self
        except BaseException:
            self.close()
            raise

    def write_recovery_marker(self, payload: Mapping[str, Any]) -> str:
        if not self.held:
            raise RuntimeError("mutation session is not open")
        raw = canonical_bytes(
            {
                "operation_id": self.operation_id,
                "production_id": self.repository.production_id,
                "expected_revision": self.expected_revision,
                "payload": dict(payload),
            },
            domain=self.RECOVERY_SCHEMA,
            version=1,
        )
        digest = hashlib.sha256(raw).hexdigest()
        if self.recovery_path.exists():
            if self.recovery_path.read_bytes() != raw:
                raise CasConflict(
                    "recovery marker differs for the same operation"
                )
            return digest
        self.stage.mkdir(parents=True, exist_ok=True)
        _atomic_write(self.recovery_path, raw)
        return digest

    def read_recovery_marker(self) -> Mapping[str, Any]:
        if not self.held or not self.recovery_path.is_file():
            raise RecoveryRequired("recovery marker is not available")
        raw = self.recovery_path.read_bytes()
        wrapped = json.loads(raw.decode("utf-8"))
        if (
            wrapped.get("$domain") != self.RECOVERY_SCHEMA
            or wrapped.get("$version") != 1
        ):
            raise CorruptObject("invalid recovery marker schema")
        payload = wrapped.get("payload")
        if (
            not isinstance(payload, dict)
            or payload.get("operation_id") != self.operation_id
            or payload.get("production_id") != self.repository.production_id
            or payload.get("expected_revision") != self.expected_revision
        ):
            raise CorruptObject("recovery marker identity mismatch")
        return MappingProxyType(dict(payload["payload"]))

    def clear_recovery_marker(self, *, expected_hash: str) -> None:
        if not self.held:
            raise RuntimeError("mutation session is not open")
        raw = self.recovery_path.read_bytes()
        if hashlib.sha256(raw).hexdigest() != expected_hash:
            raise CasConflict("recovery marker hash changed")
        self.recovery_path.unlink()
        _fsync_dir(self.recovery_path.parent)
        try:
            self.stage.rmdir()
        except OSError:
            pass

    def commit_records(
        self,
        records: Mapping[str, BlobRef],
        *,
        allowed_reserved_keys: frozenset[str],
    ) -> HeadRef:
        if not self.held:
            raise RuntimeError("mutation session is not open")
        head = self.repository._update_records_under_lease(
            records,
            expected_revision=self.expected_revision,
            allowed_reserved_keys=allowed_reserved_keys,
        )
        self.expected_revision = head.revision
        self._head = head
        self._root = self.repository.read_root(head)
        return head

    def close(self) -> None:
        self._lease.release()

    def __enter__(self) -> "MutationSession":
        return self.open()

    def __exit__(self, *_exc: object) -> None:
        self.close()


class OperationTransaction:
    """Opaque storage operation; workflow semantics are intentionally absent."""

    RECORD_SCHEMA = "dlstudio.storage_operation"

    def __init__(
        self,
        repository: ProductionRepository,
        *,
        operation_id: str,
        inputs: Mapping[str, str],
    ) -> None:
        if re.fullmatch(r"[0-9a-f]{64}", operation_id) is None:
            raise ValueError("operation_id must be exactly 64 lowercase hex")
        self.repository = repository
        self.operation_id = operation_id
        self.inputs = MappingProxyType(dict(inputs))
        self.stage = repository.staging_root / operation_id
        try:
            self.stage.resolve().relative_to(repository.staging_root.resolve())
        except ValueError as exc:
            raise ValueError("operation staging path escaped its root") from exc
        self.record_path = self.stage / "operation.json"
        self._lease = WriterLease(
            repository.lock_root / f"operation.{operation_id}.writer",
            timeout=30.0,
        )
        self._gc_barrier = WriterLease(
            repository.lock_root / "gc.barrier",
            timeout=30.0,
        )
        self._prepared = False
        self._committed_outputs: dict[str, BlobRef] | None = None
        self._committed_updates: dict[str, BlobRef] | None = None
        self._committed_head: HeadRef | None = None

    @property
    def root_record_key(self) -> str:
        return f"operation:{self.operation_id}"

    @classmethod
    def derive_id(
        cls,
        *,
        production_id: str,
        contract: str,
        inputs: Mapping[str, str],
        implementation: str,
        toolchain: str,
    ) -> str:
        return canonical_hash(
            {
                "production_id": production_id,
                "contract": contract,
                "inputs": dict(inputs),
                "implementation": implementation,
                "toolchain": toolchain,
            },
            domain=cls.RECORD_SCHEMA,
        )

    def prepare(self) -> Path:
        with self._gc_barrier:
            return self._prepare_after_gc_barrier()

    def _prepare_after_gc_barrier(self) -> Path:
        """Prepare while the caller already excludes reachability GC."""

        if self._lease.held:
            return self.stage
        self._lease.acquire()
        try:
            current_root = self.repository.read_root()
            committed_ref = current_root.records.get(self.root_record_key)
            if committed_ref is not None:
                wrapped = json.loads(
                    self.repository.objects.read(committed_ref).decode("utf-8")
                )
                if (
                    wrapped.get("$domain") != self.RECORD_SCHEMA
                    or wrapped.get("$version") != 1
                ):
                    raise CorruptObject("invalid committed operation schema")
                committed = wrapped["payload"]
                if (
                    committed.get("operation_id") != self.operation_id
                    or committed.get("inputs") != dict(self.inputs)
                    or committed.get("state") != "committed"
                ):
                    raise CasConflict(
                        "operation id reused with different committed inputs"
                    )
                self._committed_outputs = {
                    key: BlobRef(
                        sha256=str(value["sha256"]), size=int(value["size"])
                    )
                    for key, value in committed["outputs"].items()
                }
                for ref in self._committed_outputs.values():
                    self.repository.objects.verify(ref)
                self._committed_updates = {
                    key: BlobRef(
                        sha256=str(value["sha256"]), size=int(value["size"])
                    )
                    for key, value in committed["record_updates"].items()
                }
                for ref in self._committed_updates.values():
                    self.repository.objects.verify(ref)
                committed_revision = int(committed["committed_revision"])
                if committed_revision < 1:
                    raise CorruptObject("invalid committed operation revision")
                candidate = self.repository.read_head()
                if candidate is None:
                    raise CorruptObject("committed operation has no head")
                while candidate.revision > committed_revision:
                    candidate_root = self.repository.read_root(candidate)
                    parent = candidate_root.parent_root_hash
                    if parent is None:
                        raise CorruptObject("broken production root history")
                    candidate = HeadRef(parent, candidate.revision - 1)
                if candidate.revision != committed_revision:
                    raise CorruptObject("committed operation revision is unreachable")
                committed_root = self.repository.read_root(candidate)
                if (
                    committed_root.records.get(self.root_record_key)
                    != committed_ref
                ):
                    raise CorruptObject(
                        "operation record does not match its committed root"
                    )
                self._committed_head = candidate
                self._prepared = True
                return self.stage

            self._committed_outputs = None
            self._committed_updates = None
            self._committed_head = None
            self._prepare_stage()
            self._prepared = True
            return self.stage
        except BaseException:
            self._release_leases()
            raise

    def _prepare_stage(self) -> None:
        payload = {
            "schema": self.RECORD_SCHEMA,
            "version": 1,
            "operation_id": self.operation_id,
            "inputs": dict(self.inputs),
            "state": "prepared",
        }
        if self.record_path.exists():
            current = json.loads(self.record_path.read_text(encoding="utf-8"))
            if current != payload:
                raise CasConflict("operation id reused with different inputs")
            return
        if self.stage.exists():
            # No canonical operation record means the directory is untrusted
            # debris from a crash before prepare committed. It is generated
            # staging only, so recovery discards it and restarts prepare.
            shutil.rmtree(self.stage)
        self.stage.mkdir(parents=True, exist_ok=False)
        _atomic_write(
            self.record_path,
            json.dumps(
                payload, sort_keys=True, separators=(",", ":")
            ).encode("utf-8"),
        )

    def publish_file(self, path: Path) -> BlobRef:
        if (
            not self._prepared
            or not self._lease.held
            or self._committed_outputs is not None
        ):
            raise RuntimeError("prepare an uncommitted operation before publish")
        resolved = path.resolve()
        try:
            resolved.relative_to(self.stage.resolve())
        except ValueError as exc:
            raise ValueError("operation output must live in its staging dir") from exc
        return self.repository.objects.ingest_file(resolved)

    @property
    def committed_outputs(self) -> Mapping[str, BlobRef] | None:
        if self._committed_outputs is None:
            return None
        return MappingProxyType(dict(self._committed_outputs))

    @property
    def committed_head(self) -> HeadRef | None:
        return self._committed_head

    @property
    def committed_record_updates(self) -> Mapping[str, BlobRef] | None:
        if self._committed_updates is None:
            return None
        return MappingProxyType(dict(self._committed_updates))

    def commit(
        self,
        *,
        outputs: Mapping[str, BlobRef],
        record_updates: Mapping[str, BlobRef] | None = None,
        expected_revision: int,
    ) -> HeadRef:
        if record_updates:
            self._release_leases()
            raise ValueError(
                "record namespace updates require their owning repository"
            )
        return self._commit_with_records(
            outputs=outputs,
            record_updates={},
            expected_revision=expected_revision,
            owned_record_keys=frozenset(),
        )

    def _commit_with_records(
        self,
        *,
        outputs: Mapping[str, BlobRef],
        record_updates: Mapping[str, BlobRef],
        expected_revision: int,
        owned_record_keys: frozenset[str],
    ) -> HeadRef:
        if not self._prepared or not self._lease.held:
            raise RuntimeError("operation lease must be held during commit")
        try:
            output_snapshot = dict(outputs)
            requested_updates = dict(record_updates)
            if frozenset(requested_updates) != owned_record_keys:
                raise ValueError("record update set differs from owner capability")
            if self._committed_outputs is not None:
                assert self._committed_updates is not None
                assert self._committed_head is not None
                if output_snapshot != self._committed_outputs:
                    raise CasConflict(
                        "retry outputs differ from committed outputs"
                    )
                if requested_updates != self._committed_updates:
                    raise CasConflict(
                        "retry record updates differ from committed updates"
                    )
                if expected_revision != self._committed_head.revision - 1:
                    raise CasConflict(
                        "retry expected revision differs from committed attempt"
                    )
                return self._committed_head
            for ref in output_snapshot.values():
                self.repository.objects.verify(ref)
            operation_payload = {
                "operation_id": self.operation_id,
                "inputs": dict(self.inputs),
                "outputs": {
                    key: ref.as_payload()
                    for key, ref in sorted(output_snapshot.items())
                },
                "record_updates": {
                    key: ref.as_payload()
                    for key, ref in sorted(requested_updates.items())
                },
                "committed_revision": expected_revision + 1,
                "state": "committed",
            }
            operation_ref = self.repository.objects.put_bytes(
                canonical_bytes(
                    operation_payload, domain=self.RECORD_SCHEMA, version=1
                )
            )
            updates = dict(requested_updates)
            updates[self.root_record_key] = operation_ref
            head = self.repository._update_records(
                updates,
                expected_revision=expected_revision,
                allowed_reserved_keys=frozenset(
                    {self.root_record_key, *owned_record_keys}
                ),
            )
            self._committed_outputs = output_snapshot
            self._committed_updates = dict(requested_updates)
            self._committed_head = head
            if self.stage.is_dir():
                shutil.rmtree(self.stage)
            return head
        finally:
            self._release_leases()

    def abandon(self) -> None:
        try:
            if not self._lease.held:
                self.prepare()
            if self.stage.is_dir() and self._committed_outputs is None:
                shutil.rmtree(self.stage)
        finally:
            self._release_leases()

    def close(self) -> None:
        """Release execution ownership but preserve staging for resume."""

        self._release_leases()

    def _release_leases(self) -> None:
        self._lease.release()

    def __enter__(self) -> "OperationTransaction":
        self.prepare()
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()
