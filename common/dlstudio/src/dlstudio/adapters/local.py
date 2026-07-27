"""Explicit local-production loading for Studio v3."""

from __future__ import annotations

import tomllib
from dataclasses import dataclass
from pathlib import Path

from dlstudio.persistence.api import open_local_repositories

_SCHEMA = "dlstudio.production"
_VERSION = 3
_FIELDS = frozenset(
    {
        "schema",
        "version",
        "id",
        "authoring",
        "delivery_root",
    }
)


@dataclass(frozen=True, slots=True)
class LocalProduction:
    """Validated local-production paths and their concrete repositories."""

    manifest_path: Path
    production_id: str
    authoring_path: Path
    delivery_root: Path

    @property
    def production_root(self) -> Path:
        return self.manifest_path.parent

    @property
    def repository(self):
        return open_local_repositories(
            self.production_root, self.production_id
        )[0]

    @property
    def workflows(self):
        return open_local_repositories(
            self.production_root, self.production_id
        )[2]

    @property
    def assets(self):
        return open_local_repositories(
            self.production_root, self.production_id
        )[1]


def _resolve_contained_path(
    *,
    production_root: Path,
    configured_path: object,
    field: str,
    must_exist: bool,
) -> Path:
    if not isinstance(configured_path, str) or not configured_path.strip():
        raise ValueError(f"{field} must be a non-empty relative path")

    relative_path = Path(configured_path)
    if relative_path.is_absolute():
        raise ValueError(f"{field} must be relative to the production root")

    try:
        resolved = (production_root / relative_path).resolve(strict=must_exist)
    except FileNotFoundError as exc:
        raise ValueError(f"{field} does not exist: {configured_path}") from exc
    try:
        resolved.relative_to(production_root)
    except ValueError as exc:
        raise ValueError(f"{field} escapes the production root") from exc

    if resolved == production_root:
        raise ValueError(f"{field} must not resolve to the production root")
    return resolved


def load_local_production(manifest_path: str | Path) -> LocalProduction:
    """Load one explicitly named v3 local-production manifest."""

    manifest = Path(manifest_path).resolve(strict=True)
    if not manifest.is_file():
        raise ValueError(f"production manifest is not a file: {manifest}")

    payload = tomllib.loads(manifest.read_text(encoding="utf-8"))
    fields = set(payload)
    if fields != _FIELDS:
        missing = sorted(_FIELDS - fields)
        unknown = sorted(fields - _FIELDS)
        raise ValueError(
            f"production manifest fields mismatch; missing={missing}, unknown={unknown}"
        )
    if payload["schema"] != _SCHEMA:
        raise ValueError(f"unsupported production schema: {payload['schema']!r}")
    if type(payload["version"]) is not int or payload["version"] != _VERSION:
        raise ValueError(f"unsupported production version: {payload['version']!r}")
    if not isinstance(payload["id"], str):
        raise ValueError("id must be a string")

    production_root = manifest.parent
    repository, _, _ = open_local_repositories(
        production_root, payload["id"]
    )
    authoring_path = _resolve_contained_path(
        production_root=production_root,
        configured_path=payload["authoring"],
        field="authoring",
        must_exist=True,
    )
    if not authoring_path.is_file():
        raise ValueError(f"authoring must resolve to a file: {authoring_path}")
    delivery_root = _resolve_contained_path(
        production_root=production_root,
        configured_path=payload["delivery_root"],
        field="delivery_root",
        must_exist=False,
    )

    return LocalProduction(
        manifest_path=manifest,
        production_id=repository.production_id,
        authoring_path=authoring_path,
        delivery_root=delivery_root,
    )
