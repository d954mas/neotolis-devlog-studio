from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def _volume_identity(path: Path) -> str:
    resolved = path.resolve()
    while not resolved.exists():
        if resolved.parent == resolved:
            raise FileNotFoundError(path)
        resolved = resolved.parent
    if resolved.drive:
        return resolved.drive.casefold()
    return str(resolved.stat().st_dev)


def _free_bytes(path: Path) -> int:
    resolved = path.resolve()
    while not resolved.exists():
        resolved = resolved.parent
    return shutil.disk_usage(resolved).free


def build_disk_budget(
    workspace: Path,
    manifest: dict[str, Any],
    backup_destination: Path,
    restore_destination: Path,
    clone_destination: Path,
) -> dict[str, Any]:
    total = int(manifest["summary"]["bytes"])
    media = int(manifest["summary"]["source_media_bytes"])
    workspace_volume = _volume_identity(workspace)
    clone_volume = _volume_identity(clone_destination)
    same_volume = workspace_volume == clone_volume
    # A verified backup is always a byte copy. Hardlinks are safe only for the
    # disposable migration clone and never count as recovery.
    additional_for_backup = total
    additional_for_backup_and_restore_rehearsal = total * 2
    clone_copy_bytes = 0 if same_volume else total
    destinations = (
        ("backup", backup_destination, total),
        ("restore", restore_destination, total),
        ("clone", clone_destination, clone_copy_bytes),
    )
    grouped: dict[str, dict[str, Any]] = {}
    for name, destination, required in destinations:
        volume = _volume_identity(destination)
        item = grouped.setdefault(
            volume,
            {
                "id": volume,
                "free_bytes": _free_bytes(destination),
                "required_bytes": 0,
                "destinations": [],
            },
        )
        item["required_bytes"] += required
        item["destinations"].append(
            {
                "kind": name,
                "path": str(destination.resolve()),
                "required_bytes": required,
            }
        )
    volumes = []
    for item in sorted(grouped.values(), key=lambda value: value["id"]):
        item["sufficient"] = item["free_bytes"] >= item["required_bytes"]
        volumes.append(item)
    required_peak = sum(item["required_bytes"] for item in volumes)
    return {
        "schema_version": 2,
        "workspace_bytes": total,
        "source_media_bytes": media,
        "verified_backup_copy_bytes": additional_for_backup,
        "restore_rehearsal_copy_bytes": total,
        "clone_policy": "hardlink_then_verify" if same_volume else "verified_copy",
        "clone_copy_bytes": clone_copy_bytes,
        "required_additional_peak_bytes": required_peak,
        "volumes": volumes,
        "sufficient": all(item["sufficient"] for item in volumes),
        "hardlinks_are_backup": False,
    }
