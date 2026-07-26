"""Explicit local context for every Studio v3 application use case."""

from __future__ import annotations

from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from types import MappingProxyType

from dlstudio.foundation.api import DomainId


@dataclass(frozen=True, slots=True)
class ProductionPaths:
    production_root: Path
    studio_root: Path
    object_root: Path
    state_root: Path
    staging_root: Path
    lock_root: Path
    delivery_root: Path

    @classmethod
    def from_root(
        cls,
        production_root: Path,
        *,
        delivery_root: Path | None = None,
    ) -> "ProductionPaths":
        root = production_root.resolve()
        studio = root / "data" / ".studio"
        return cls(
            production_root=root,
            studio_root=studio,
            object_root=studio / "objects",
            state_root=studio / "state",
            staging_root=studio / "staging",
            lock_root=studio / "locks",
            delivery_root=(delivery_root or root / "delivery").resolve(),
        )


@dataclass(frozen=True, slots=True)
class MachineBindings:
    ffmpeg: str = "ffmpeg"
    ffprobe: str = "ffprobe"
    values: Mapping[str, str] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "values", MappingProxyType(dict(self.values))
        )


@dataclass(frozen=True, slots=True)
class ProductionContext:
    workspace_root: Path
    project_root: Path
    production_id: DomainId[object]
    paths: ProductionPaths
    machine_bindings: MachineBindings = MachineBindings()
    clock: Callable[[], datetime] = lambda: datetime.now(UTC)

    @classmethod
    def create(
        cls,
        *,
        workspace_root: Path,
        project_root: Path,
        production_id: str,
        production_root: Path,
        delivery_root: Path | None = None,
        machine_bindings: MachineBindings | None = None,
        clock: Callable[[], datetime] | None = None,
    ) -> "ProductionContext":
        kwargs: dict[str, object] = {}
        if clock is not None:
            kwargs["clock"] = clock
        return cls(
            workspace_root=workspace_root.resolve(),
            project_root=project_root.resolve(),
            production_id=DomainId(production_id),
            paths=ProductionPaths.from_root(
                production_root, delivery_root=delivery_root
            ),
            machine_bindings=machine_bindings or MachineBindings(),
            **kwargs,
        )
