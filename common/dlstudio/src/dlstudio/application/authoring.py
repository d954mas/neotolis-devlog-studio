"""Resolve current assets once, then compile a self-contained TimelineIR."""

from __future__ import annotations

from dlstudio.assets.api import AssetReadPort
from dlstudio.authoring.api import (
    Edit,
    MediaLayer,
    TextLayer,
    _compile_resolved,
)
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
