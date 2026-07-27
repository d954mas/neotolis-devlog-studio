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
    canonical_bytes,
)

_RESERVED_RECORD_PREFIXES = ("asset_revision:",)
_RESERVED_RECORD_KEYS = frozenset({"assets:index"})


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
        if root.production_id != self.production_id:
            raise ValueError("wrong production id")
        if root.revision != expected_revision + 1:
            raise ValueError("new root must increment expected revision once")
        raw = canonical_bytes(
            root.as_payload(), domain=self.ROOT_SCHEMA, version=1
        )
        root_hash = hashlib.sha256(raw).hexdigest()
        root_path = self.roots_path / f"{root_hash}.json"
        for ref in root.records.values():
            self.objects.verify(ref)
        if not root_path.exists():
            _atomic_write(root_path, raw)
        elif root_path.read_bytes() != raw:
            raise CorruptObject(
                f"immutable production root collision at {root_hash}"
            )
        with self.writer_lease():
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
                if key.startswith("asset_revision:") and (
                    key in previous_reserved or key not in next_reserved
                ):
                    raise CasConflict(
                        f"immutable reserved record cannot change: {key}"
                    )
                if key == "assets:index" and key not in next_reserved:
                    raise ValueError("asset index cannot be removed")
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
        return self._commit_root(
            ProductionStateRoot(
                self.production_id,
                expected_revision + 1,
                merged,
                None if current_head is None else current_head.root_hash,
            ),
            expected_revision=expected_revision,
            allowed_reserved_keys=allowed_reserved_keys,
        )
