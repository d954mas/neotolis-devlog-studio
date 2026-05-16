"""Workspace-local configuration for fast devlog iteration.

The CLI stays runnable directly from the workspace via dl/dl.bat. This module
only adds smart defaults; it is not packaging machinery.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
import tomllib


CONFIG_NAME = "devlog.toml"


@dataclass(frozen=True)
class DevlogConfig:
    path: Path | None = None
    default_edit: str | None = None
    defaults: dict[str, Any] = field(default_factory=dict)
    final: dict[str, Any] = field(default_factory=dict)
    watch: dict[str, Any] = field(default_factory=dict)


def find_config_path(start: Path | None = None) -> Path | None:
    """Search upward from start/cwd for devlog.toml."""
    cur = (start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent
    for parent in (cur, *cur.parents):
        candidate = parent / CONFIG_NAME
        if candidate.exists():
            return candidate
    return None


def load_config(start: Path | None = None) -> DevlogConfig:
    path = find_config_path(start)
    if path is None:
        return DevlogConfig()
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    defaults = dict(data.get("defaults", {}))
    final = dict(data.get("final", {}))
    watch = dict(data.get("watch", {}))
    default_edit = data.get("default_edit") or defaults.get("edit")
    return DevlogConfig(
        path=path,
        default_edit=default_edit,
        defaults=defaults,
        final=final,
        watch=watch,
    )
