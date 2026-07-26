from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Any

from .inventory import hash_path


class RecoveryError(RuntimeError):
    """A backup or restore proof failed."""


def _prepare_empty_destination(source: Path, destination: Path) -> None:
    source = source.resolve()
    destination_resolved = destination.resolve()
    if destination_resolved == source or destination_resolved.is_relative_to(source):
        raise RecoveryError("destination must be outside the source tree")
    if destination.exists():
        if not destination.is_dir() or any(destination.iterdir()):
            raise RecoveryError(f"destination must be empty: {destination}")
    else:
        destination.mkdir(parents=True)


def _copy_entry(source: Path, destination: Path, kind: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if kind == "symlink":
        os.symlink(os.readlink(source), destination)
    else:
        shutil.copy2(source, destination)


def verify_tree_against_manifest(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    expected = {entry["path"]: entry for entry in manifest["entries"]}
    actual: set[str] = set()
    for current, directories, names in os.walk(root, followlinks=False):
        actual.update(
            (Path(current) / name).relative_to(root).as_posix()
            for name in directories
            if (Path(current) / name).is_symlink()
        )
        directories[:] = [
            name for name in directories if not (Path(current) / name).is_symlink()
        ]
        for name in names:
            actual.add((Path(current) / name).relative_to(root).as_posix())
    missing = sorted(set(expected) - actual)
    extra = sorted(actual - set(expected))
    mismatched: list[str] = []
    for relative in sorted(set(expected) & actual):
        entry = expected[relative]
        path = root / Path(relative)
        if hash_path(path) != entry["sha256"] or path.lstat().st_size != entry["bytes"]:
            mismatched.append(relative)
    verified = not missing and not extra and not mismatched
    return {
        "verified": verified,
        "entries": len(expected),
        "missing": missing,
        "extra": extra,
        "mismatched": mismatched,
    }


def create_verified_backup(
    source: Path, destination: Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    source = source.resolve()
    _prepare_empty_destination(source, destination)
    for entry in manifest["entries"]:
        relative = Path(entry["path"])
        source_path = source / relative
        if not source_path.exists() and not source_path.is_symlink():
            raise RecoveryError(f"source changed: missing {entry['path']}")
        if (
            hash_path(source_path) != entry["sha256"]
            or source_path.lstat().st_size != entry["bytes"]
        ):
            raise RecoveryError(f"source changed since manifest: {entry['path']}")
        _copy_entry(source_path, destination / relative, entry["kind"])
    report = verify_tree_against_manifest(destination, manifest)
    if not report["verified"]:
        raise RecoveryError(f"backup verification failed: {report}")
    return report


def rehearse_restore(
    backup: Path, destination: Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    source_report = verify_tree_against_manifest(backup, manifest)
    if not source_report["verified"]:
        raise RecoveryError(f"backup is not verified: {source_report}")
    _prepare_empty_destination(backup.resolve(), destination)
    for entry in manifest["entries"]:
        relative = Path(entry["path"])
        _copy_entry(backup / relative, destination / relative, entry["kind"])
    report = verify_tree_against_manifest(destination, manifest)
    if not report["verified"]:
        raise RecoveryError(f"restore rehearsal failed: {report}")
    return report
