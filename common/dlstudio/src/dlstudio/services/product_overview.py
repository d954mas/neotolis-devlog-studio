"""Read-only product overview used by Studio and automation reports."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from dlstudio.production import (
    load_production_manifest,
    load_product_manifest,
)


@dataclass(frozen=True)
class ProductionOverview:
    id: str
    kind: str
    date: str
    orientation: str
    studio_ref: str
    current: bool


@dataclass(frozen=True)
class ProductOverview:
    product_id: str
    title: str
    current_production_id: str
    productions: tuple[ProductionOverview, ...]


def build_product_overview(current_production_root: str | Path) -> ProductOverview:
    """List every manifest-backed production in the current product."""

    current = load_production_manifest(current_production_root)
    product = load_product_manifest(current.product.root)
    manifests = []
    for collection_root in (product.devlogs_dir, product.reels_dir):
        if not collection_root.is_dir():
            continue
        for path in collection_root.glob("*/production.toml"):
            manifests.append(load_production_manifest(path))
    productions = tuple(
        ProductionOverview(
            id=manifest.id,
            kind=manifest.kind,
            date=manifest.date,
            orientation=manifest.orientation,
            studio_ref=f"{product.id}:{manifest.id}",
            current=manifest.id == current.id,
        )
        for manifest in sorted(manifests, key=lambda item: item.id)
    )
    return ProductOverview(
        product_id=product.id,
        title=product.title,
        current_production_id=current.id,
        productions=productions,
    )


__all__ = [
    "ProductOverview",
    "ProductionOverview",
    "build_product_overview",
]
