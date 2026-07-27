from __future__ import annotations

import hashlib
import json
import os
import shutil
from pathlib import Path
from typing import Any

from .inventory import hash_path, validate_manifest


class RecoveryError(RuntimeError):
    """A backup or restore proof failed."""


def _validate_destination(source: Path, destination: Path) -> None:
    source = source.resolve()
    destination_resolved = destination.resolve()
    if destination_resolved == source or destination_resolved.is_relative_to(source):
        raise RecoveryError("destination must be outside the source tree")


def _copy_entry(source: Path, destination: Path, kind: str) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if kind == "symlink":
        os.symlink(os.readlink(source), destination)
    else:
        shutil.copyfile(source, destination)


def _manifest_digest(manifest: dict[str, Any]) -> str:
    raw = json.dumps(
        manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return hashlib.sha256(raw).hexdigest()


def _same_entry(path: Path, entry: dict[str, Any]) -> bool:
    return (
        (path.exists() or path.is_symlink())
        and hash_path(path) == entry["sha256"]
        and path.lstat().st_size == entry["bytes"]
    )


def _copy_tree_atomic(
    source: Path,
    destination: Path,
    manifest: dict[str, Any],
    *,
    label: str,
) -> dict[str, Any]:
    manifest = validate_manifest(manifest)
    source = source.resolve()
    destination = destination.resolve()
    _validate_destination(source, destination)
    if destination.exists():
        report = verify_tree_against_manifest(destination, manifest)
        if report["verified"]:
            return {
                **report,
                "manifest_sha256": _manifest_digest(manifest),
                "resumed_entries": len(manifest["entries"]),
            }
        raise RecoveryError(f"destination differs: {destination}")

    digest = _manifest_digest(manifest)
    staging = destination.with_name(f".{destination.name}.{digest[:16]}.staging")
    if staging.exists() and not staging.is_dir():
        raise RecoveryError(f"invalid {label} staging path: {staging}")
    staging.mkdir(parents=True, exist_ok=True)
    resumed = 0
    for entry in manifest["entries"]:
        relative = Path(entry["path"])
        source_path = source / relative
        if not _same_entry(source_path, entry):
            raise RecoveryError(f"source changed since manifest: {entry['path']}")
        target = staging / relative
        if _same_entry(target, entry):
            resumed += 1
            continue
        if target.exists() or target.is_symlink():
            if target.is_dir() and not target.is_symlink():
                raise RecoveryError(f"unexpected staging directory: {entry['path']}")
            target.unlink()
        target.parent.mkdir(parents=True, exist_ok=True)
        temporary = target.with_name(f".{target.name}.tmp")
        if temporary.exists() or temporary.is_symlink():
            temporary.unlink()
        _copy_entry(source_path, temporary, entry["kind"])
        if not _same_entry(temporary, entry):
            temporary.unlink(missing_ok=True)
            raise RecoveryError(f"copied entry verification failed: {entry['path']}")
        os.replace(temporary, target)
    report = verify_tree_against_manifest(staging, manifest)
    if not report["verified"]:
        raise RecoveryError(f"{label} staging verification failed: {report}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    os.replace(staging, destination)
    return {
        **report,
        "manifest_sha256": digest,
        "resumed_entries": resumed,
    }


def verify_tree_against_manifest(root: Path, manifest: dict[str, Any]) -> dict[str, Any]:
    manifest = validate_manifest(manifest)
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
    return _copy_tree_atomic(
        source, destination, manifest, label="backup"
    )


def rehearse_restore(
    backup: Path, destination: Path, manifest: dict[str, Any]
) -> dict[str, Any]:
    manifest = validate_manifest(manifest)
    source_report = verify_tree_against_manifest(backup, manifest)
    if not source_report["verified"]:
        raise RecoveryError(f"backup is not verified: {source_report}")
    return _copy_tree_atomic(
        backup, destination, manifest, label="restore"
    )
