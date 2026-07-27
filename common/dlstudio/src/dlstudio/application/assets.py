"""Asset ingest application use cases shared by all adapters."""

from __future__ import annotations

from dataclasses import dataclass
from collections.abc import Callable
from pathlib import Path

from dlstudio.assets.api import (
    Approval,
    AssetIngestPort,
    AssetIngestResult,
    License,
    MediaFacts,
    Provenance,
)
from dlstudio.foundation.api import BlobRef

from .release import BlobStore

@dataclass(frozen=True, slots=True)
class IngestAssetCommand:
    source: Path
    asset_id: str
    provenance: Provenance
    approval: Approval
    license: License
    expected_revision: int


def ingest_asset(
    repository: AssetIngestPort,
    command: IngestAssetCommand,
    *,
    inspect_media: Callable[[Path], MediaFacts],
) -> AssetIngestResult:
    media = inspect_media(command.source)
    return repository.ingest(
        command.source,
        asset_id=command.asset_id,
        media=media,
        provenance=command.provenance,
        approval=command.approval,
        license=command.license,
        expected_revision=command.expected_revision,
        inspect_media=inspect_media,
    )


def resolve_blob(store: BlobStore, sha256: str, size: int) -> Path:
    """Resolve one verified immutable blob for streaming adapters."""

    ref = BlobRef(sha256, size)
    store.verify(ref)
    return store.path_for(ref)
