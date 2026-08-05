"""Resolve current assets once, then compile a self-contained TimelineIR."""

from __future__ import annotations

from dlstudio.assets.api import AssetReadPort, AssetRevision
from dlstudio.authoring.api import (
    Edit,
    MediaLayer,
    TextLayer,
    _compile_resolved,
)
from dlstudio.release.api import PublicationManifest, PublicationManifestFile
from dlstudio.timeline.api import TimelineIR


def compile_production(edit: Edit, assets: AssetReadPort) -> TimelineIR:
    identifiers = {
        layer.asset_id
        for layer in edit.visuals
        if isinstance(layer, MediaLayer)
    }
    identifiers.update(
        layer.font_asset_id
        for layer in edit.visuals
        if isinstance(layer, TextLayer)
    )
    identifiers.update(clip.asset_id for clip in edit.audio)
    return _compile_resolved(
        edit, (assets.current(asset_id) for asset_id in sorted(identifiers))
    )


def resolve_publication(
    edit: Edit,
    assets: AssetReadPort,
) -> tuple[PublicationManifest, tuple[AssetRevision, ...]]:
    """Resolve authored logical publication files to exact current revisions."""

    revisions = tuple(
        assets.current(asset_id)
        for asset_id in sorted({item.asset_id for item in edit.publication})
    )
    by_id = {item.asset_id: item for item in revisions}
    manifest = PublicationManifest(
        edit.production_id,
        tuple(
            PublicationManifestFile(
                role=item.role,
                path=item.path,
                asset_id=item.asset_id,
                revision=by_id[item.asset_id].ref.object,
                blob=by_id[item.asset_id].blob,
            )
            for item in edit.publication
        ),
    )
    return manifest, revisions
