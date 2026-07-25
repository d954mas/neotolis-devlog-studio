"""Transactional promotion for multi-file production artifacts."""
from __future__ import annotations

import os
import uuid
from pathlib import Path


def promote_bundle(replacements: list[tuple[Path, Path]]) -> None:
    """Publish staged files together, restoring every prior target on failure."""

    nonce = uuid.uuid4().hex[:8]
    backups: list[tuple[Path, Path]] = []
    promoted: list[Path] = []
    try:
        for _staged, target in replacements:
            target.parent.mkdir(parents=True, exist_ok=True)
            if target.exists():
                backup = target.with_name(f".{target.name}.backup-{nonce}")
                os.replace(target, backup)
                backups.append((backup, target))
        for staged, target in replacements:
            os.replace(staged, target)
            promoted.append(target)
    except Exception:
        for target in reversed(promoted):
            target.unlink(missing_ok=True)
        for backup, target in reversed(backups):
            if backup.exists():
                os.replace(backup, target)
        raise
    else:
        for backup, _target in backups:
            backup.unlink(missing_ok=True)
