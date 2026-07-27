"""Filesystem implementation of the Studio v3 asset contracts."""

from __future__ import annotations

import json
import os
import shutil
import tempfile
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
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
ASSET_REVISION_PREFIX = "asset_revision:"


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
        return self._read_revision_from_root(self.repository.read_root(), ref)

    def _read_revision_from_root(
        self, root: Any, ref: AssetRevisionRef
    ) -> AssetRevision:
        object_ref = root.records.get(
            f"{ASSET_REVISION_PREFIX}{ref.revision_hash}"
        )
        if object_ref is None:
            raise CorruptObject(
                f"asset revision is not reachable: {ref.revision_hash}"
            )
        try:
            revision = AssetRevision.from_canonical_bytes(
                self.repository.objects.read(object_ref)
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
        parent = None if previous is None else previous.revision_hash
        if provenance.parent_revision_hash not in {None, parent}:
            raise CasConflict("asset parent revision is stale")
        if previous is not None:
            current_revision = self._read_revision_from_root(
                snapshot_root, previous
            )
            repeat_candidate = AssetRevision(
                asset_id=asset_id,
                blob=blob,
                media=media,
                provenance=replace(
                    provenance,
                    parent_revision_hash=(
                        current_revision.provenance.parent_revision_hash
                    ),
                ),
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
            provenance=replace(provenance, parent_revision_hash=parent),
            approval=approval,
            license=license,
        )
        revision_object = self.repository.objects.put_bytes(
            revision.canonical_bytes()
        )
        next_index = AssetIndexRevision(
            {**index.entries, asset_id: revision.ref}
        )
        index_object = self.repository.objects.put_bytes(
            next_index.canonical_bytes()
        )
        updates = {
            ASSET_INDEX_KEY: index_object,
            f"{ASSET_REVISION_PREFIX}{revision.revision_hash}": revision_object,
        }
        head = self.repository._update_records(
            updates,
            expected_revision=expected_revision,
            allowed_reserved_keys=frozenset(updates),
        )
        return AssetIngestResult(
            revision, head.root_hash, head.revision, True
        )

    def rebuild_index(self) -> AssetIndexRevision:
        root = self.repository.read_root()
        revisions: dict[str, AssetRevision] = {}
        parent_hashes: set[str] = set()
        for key, object_ref in root.records.items():
            if not key.startswith(ASSET_REVISION_PREFIX):
                continue
            revision = AssetRevision.from_canonical_bytes(
                self.repository.objects.read(object_ref)
            )
            if key != f"{ASSET_REVISION_PREFIX}{revision.revision_hash}":
                raise CorruptObject("asset revision record key mismatch")
            revisions[revision.revision_hash] = revision
            for reachable in revision.reachable_blobs:
                self.repository.objects.verify(reachable)
            parent = revision.provenance.parent_revision_hash
            if parent is not None:
                parent_hashes.add(parent)
        by_asset: dict[str, dict[str, AssetRevision]] = {}
        for revision_hash, revision in revisions.items():
            by_asset.setdefault(revision.asset_id, {})[revision_hash] = revision
            parent = revision.provenance.parent_revision_hash
            if parent is not None:
                parent_revision = revisions.get(parent)
                if parent_revision is None:
                    raise CorruptObject("asset revision parent is missing")
                if parent_revision.asset_id != revision.asset_id:
                    raise CorruptObject("asset revision parent crosses assets")
        leaves: dict[str, AssetRevisionRef] = {}
        for asset_id, chain in by_asset.items():
            roots = [
                revision
                for revision in chain.values()
                if revision.provenance.parent_revision_hash is None
            ]
            if len(roots) != 1:
                raise CorruptObject(f"asset chain needs one root: {asset_id}")
            children: dict[str, list[AssetRevision]] = {}
            for revision in chain.values():
                parent = revision.provenance.parent_revision_hash
                if parent is not None:
                    children.setdefault(parent, []).append(revision)
            if any(len(items) != 1 for items in children.values()):
                raise CorruptObject(f"forked asset revision chain: {asset_id}")
            visited: set[str] = set()
            cursor = roots[0]
            while True:
                if cursor.revision_hash in visited:
                    raise CorruptObject(f"cyclic asset revision chain: {asset_id}")
                visited.add(cursor.revision_hash)
                next_items = children.get(cursor.revision_hash, [])
                if not next_items:
                    break
                cursor = next_items[0]
            if visited != set(chain):
                raise CorruptObject(f"disconnected asset revision chain: {asset_id}")
            leaves[asset_id] = cursor.ref
        return AssetIndexRevision(leaves)

    def verify_index_projection(self) -> None:
        if self.rebuild_index() != self.read_index():
            raise CorruptObject("asset index differs from rebuilt projection")

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
            root = self.repository.read_root()
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

            for direct in root.records.values():
                visit(direct)

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
