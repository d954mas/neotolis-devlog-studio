"""Filesystem implementation of the Studio v3 asset contracts."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from dlstudio.assets.api import (
    Approval,
    AssetIndexRevision,
    AssetIngestResult,
    AssetRevision,
    AssetRevisionRef,
    License,
    MediaFacts,
    Provenance,
)
from dlstudio.foundation.api import BlobRef, CasConflict, CorruptObject

from .api import ProductionRepository

ASSET_INDEX_KEY = "assets:index"


@dataclass(frozen=True, slots=True)
class MaterializeResult:
    target: Path
    method: str
    blob: BlobRef


@dataclass(frozen=True, slots=True)
class GarbageCollectionReport:
    reachable: int
    candidates: tuple[BlobRef, ...]
    removed: tuple[BlobRef, ...]
    candidate_bytes: int


class AssetRepository:
    """Owns immutable asset revisions and their canonical current index."""

    def __init__(self, repository: ProductionRepository) -> None:
        self.repository = repository

    def read_index(self) -> AssetIndexRevision:
        return self._read_index_from_root(self.repository.read_root())

    def _read_index_from_root(self, root: Any) -> AssetIndexRevision:
        ref = root.records.get(ASSET_INDEX_KEY)
        if ref is None:
            return AssetIndexRevision()
        try:
            return AssetIndexRevision.from_canonical_bytes(
                self.repository.objects.read(ref)
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CorruptObject("invalid canonical asset index") from exc

    def read_revision(self, ref: AssetRevisionRef) -> AssetRevision:
        return self._read_revision(ref)

    def _read_revision(self, ref: AssetRevisionRef) -> AssetRevision:
        try:
            revision = AssetRevision.from_canonical_bytes(
                self.repository.objects.read(ref.object)
            )
        except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
            raise CorruptObject("invalid canonical asset revision") from exc
        if revision.ref != ref:
            raise CorruptObject("asset revision ref/payload mismatch")
        for reachable in revision.reachable_blobs:
            self.repository.objects.verify(reachable)
        return revision

    def ingest(
        self,
        source: Path,
        *,
        asset_id: str,
        media: MediaFacts,
        provenance: Provenance,
        approval: Approval,
        license: License,
        expected_revision: int,
        inspect_media: Callable[[Path], MediaFacts],
    ) -> AssetIngestResult:
        from .api import WriterLease

        with WriterLease(self.repository.lock_root / "gc.barrier"):
            return self._ingest_under_gc_barrier(
                source,
                asset_id=asset_id,
                media=media,
                provenance=provenance,
                approval=approval,
                license=license,
                expected_revision=expected_revision,
                inspect_media=inspect_media,
            )

    def _ingest_under_gc_barrier(
        self,
        source: Path,
        *,
        asset_id: str,
        media: MediaFacts,
        provenance: Provenance,
        approval: Approval,
        license: License,
        expected_revision: int,
        inspect_media: Callable[[Path], MediaFacts],
    ) -> AssetIngestResult:
        source = source.resolve(strict=True)
        before = (source.stat().st_size, source.stat().st_mtime_ns)
        blob = self.repository.objects.ingest_file(source)
        after_ingest = (source.stat().st_size, source.stat().st_mtime_ns)
        if before != after_ingest:
            raise CasConflict("source changed during ingest")
        inspected = inspect_media(self.repository.objects.path_for(blob))
        if inspected != media:
            raise ValueError("declared media facts differ from inspected blob")
        for evidence in (
            *provenance.evidence_refs,
            *approval.evidence_refs,
        ):
            self.repository.objects.verify(evidence)
        return self._commit_ingest_with_cas(
            asset_id=asset_id,
            blob=blob,
            media=media,
            provenance=provenance,
            approval=approval,
            license=license,
            expected_revision=expected_revision,
        )

    def _commit_ingest_with_cas(
        self,
        *,
        asset_id: str,
        blob: BlobRef,
        media: MediaFacts,
        provenance: Provenance,
        approval: Approval,
        license: License,
        expected_revision: int,
    ) -> AssetIngestResult:
        snapshot_head = self.repository.read_head()
        snapshot_root = self.repository.read_root(snapshot_head)
        index = self._read_index_from_root(snapshot_root)
        previous = index.entries.get(asset_id)
        if previous is not None:
            current_revision = self._read_revision(previous)
            repeat_candidate = AssetRevision(
                asset_id=asset_id,
                blob=blob,
                media=media,
                provenance=provenance,
                approval=approval,
                license=license,
            )
            if repeat_candidate.ref == previous:
                if snapshot_head is None:
                    raise CorruptObject("indexed revision has no canonical head")
                if self.repository.read_head() != snapshot_head:
                    raise CasConflict("head changed during idempotence check")
                return AssetIngestResult(
                    current_revision,
                    snapshot_head.root_hash,
                    snapshot_head.revision,
                    False,
                )
        revision = AssetRevision(
            asset_id=asset_id,
            blob=blob,
            media=media,
            provenance=provenance,
            approval=approval,
            license=license,
        )
        revision_object = self.repository.objects.put_bytes(
            revision.canonical_bytes()
        )
        if revision_object != revision.ref.object:
            raise CorruptObject("asset revision object identity mismatch")
        next_index = AssetIndexRevision(
            {**index.entries, asset_id: revision.ref}
        )
        index_object = self.repository.objects.put_bytes(
            next_index.canonical_bytes()
        )
        updates = {ASSET_INDEX_KEY: index_object}
        head = self.repository._update_records(
            updates,
            expected_revision=expected_revision,
            allowed_reserved_keys=frozenset({ASSET_INDEX_KEY}),
        )
        return AssetIngestResult(
            revision, head.root_hash, head.revision, True
        )

    def materialize(self, blob: BlobRef, target: Path) -> MaterializeResult:
        self.repository.objects.verify(blob)
        source = self.repository.objects.path_for(blob)
        target = target.resolve()
        for protected in (
            self.repository.object_root,
            self.repository.state_root,
            self.repository.staging_root,
            self.repository.lock_root,
        ):
            try:
                target.relative_to(protected.resolve())
            except ValueError:
                continue
            raise ValueError("materialize target cannot be inside canonical storage")
        target.parent.mkdir(parents=True, exist_ok=True)
        fd, raw_temp = tempfile.mkstemp(
            prefix=f".{target.name}.", dir=target.parent
        )
        os.close(fd)
        temp = Path(raw_temp)
        temp.unlink()
        method = "verified-copy"
        try:
            shutil.copy2(source, temp)
            if (
                temp.stat().st_size != blob.size
                or self.repository.objects.ingest_file(temp) != blob
            ):
                raise CorruptObject("materialized blob verification failed")
            os.replace(temp, target)
            return MaterializeResult(target, method, blob)
        finally:
            temp.unlink(missing_ok=True)

    def collect_garbage(self, *, apply: bool = False) -> GarbageCollectionReport:
        gc_barrier = self.repository.lock_root / "gc.barrier"
        from .api import WriterLease

        with WriterLease(gc_barrier):
            return self._collect_garbage_under_barrier(apply=apply)

    def _collect_garbage_under_barrier(
        self, *, apply: bool
    ) -> GarbageCollectionReport:
        with self.repository.writer_lease():
            reachable: set[str] = set()

            def visit(ref: BlobRef, *, strict: bool = True) -> None:
                if ref.sha256 in reachable:
                    return
                self.repository.objects.verify(ref)
                reachable.add(ref.sha256)
                raw = self.repository.objects.read(ref)
                try:
                    value = json.loads(raw)
                except (UnicodeDecodeError, json.JSONDecodeError):
                    return

                known_canonical = (
                    isinstance(value, Mapping)
                    and value.get("$domain")
                    in {
                        AssetRevision.DOMAIN,
                        AssetIndexRevision.DOMAIN,
                    }
                )

                def scan(item: Any) -> None:
                    if isinstance(item, Mapping):
                        if set(item) >= {"sha256", "size"}:
                            try:
                                visit(BlobRef.from_payload(item))
                            except (KeyError, TypeError, ValueError, CorruptObject):
                                if known_canonical or strict:
                                    raise
                        for nested in item.values():
                            scan(nested)
                    elif isinstance(item, list):
                        for nested in item:
                            scan(nested)

                scan(value)

            if self.repository.roots_path.is_dir():
                for root_path in self.repository.roots_path.glob("*.json"):
                    raw = root_path.read_bytes()
                    if hashlib.sha256(raw).hexdigest() != root_path.stem:
                        raise CorruptObject("production root hash mismatch")
                    wrapped = json.loads(raw)
                    if (
                        wrapped.get("$domain")
                        != self.repository.ROOT_SCHEMA
                        or wrapped.get("$version") != 1
                    ):
                        raise CorruptObject("invalid production root schema")
                    for value in wrapped["payload"]["records"].values():
                        visit(BlobRef.from_payload(value))

            candidates: list[BlobRef] = []
            removed: list[BlobRef] = []
            if self.repository.object_root.is_dir():
                for path in sorted(self.repository.object_root.iterdir()):
                    if (
                        not path.is_file()
                        or len(path.name) != 64
                        or path.name in reachable
                    ):
                        continue
                    ref = BlobRef(path.name, path.stat().st_size)
                    self.repository.objects.verify(ref)
                    candidates.append(ref)
                    if apply:
                        path.unlink()
                        removed.append(ref)
            return GarbageCollectionReport(
                reachable=len(reachable),
                candidates=tuple(candidates),
                removed=tuple(removed),
                candidate_bytes=sum(ref.size for ref in candidates),
            )
