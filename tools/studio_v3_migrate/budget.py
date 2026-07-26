from __future__ import annotations

import shutil
from pathlib import Path
from typing import Any


def _volume_identity(path: Path) -> str:
    resolved = path.resolve()
    if resolved.drive:
        return resolved.drive.casefold()
    return str(resolved.stat().st_dev)


def build_disk_budget(
    workspace: Path,
    manifest: dict[str, Any],
    backup_destination: Path,
    clone_destination: Path | None = None,
) -> dict[str, Any]:
    total = int(manifest["summary"]["bytes"])
    media = int(manifest["summary"]["source_media_bytes"])
    backup_parent = backup_destination.resolve()
    while not backup_parent.exists():
        backup_parent = backup_parent.parent
    free = shutil.disk_usage(backup_parent).free
    clone_destination = clone_destination or backup_destination
    same_volume = _volume_identity(workspace) == _volume_identity(
        clone_destination.resolve().parent
        if not clone_destination.exists()
        else clone_destination
    )
    # A verified backup is always a byte copy. Hardlinks are safe only for the
    # disposable migration clone and never count as recovery.
    additional_for_backup = total
    additional_for_backup_and_restore_rehearsal = total * 2
    clone_copy_bytes = 0 if same_volume else total
    required_peak = additional_for_backup_and_restore_rehearsal + clone_copy_bytes
    return {
        "schema_version": 1,
        "workspace_bytes": total,
        "source_media_bytes": media,
        "verified_backup_copy_bytes": additional_for_backup,
        "restore_rehearsal_copy_bytes": total,
        "clone_policy": "hardlink_then_verify" if same_volume else "verified_copy",
        "clone_copy_bytes": clone_copy_bytes,
        "required_additional_peak_bytes": required_peak,
        "destination_free_bytes": free,
        "sufficient": free >= required_peak,
        "hardlinks_are_backup": False,
    }
