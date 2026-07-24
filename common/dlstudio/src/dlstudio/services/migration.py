"""Safe, source-preserving filesystem migration plans.

The service deliberately stops below project-specific manifest rewriting.  It
inventories bytes, produces an auditable JSON copy plan, rejects collisions,
and applies that plan without moving, deleting, or overwriting source data.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping


SHAREABLE_PRODUCTION_DIRS: tuple[str, ...] = (
    "footage",
    "images",
    "fonts",
    "music",
    "sfx",
)


class MigrationError(RuntimeError):
    """Base class for an invalid or unsafe migration operation."""


class MigrationCollisionError(MigrationError):
    """A destination is already claimed by different content."""


class MigrationIntegrityError(MigrationError):
    """Source or copied bytes do not match the recorded inventory."""


@dataclass(frozen=True)
class InventoryFile:
    """One source file, addressed relative to its inventory root."""

    path: str
    size: int
    sha256: str


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _size_and_sha256(path: Path) -> tuple[int, str]:
    if path.is_symlink():
        raise MigrationError(f"symbolic links are not migration files: {path}")
    if not path.is_file():
        raise MigrationError(f"migration source is not a regular file: {path}")
    return path.stat().st_size, _sha256_file(path)


def inventory_source_files(source_root: str | Path) -> tuple[InventoryFile, ...]:
    """Recursively inventory regular files below ``source_root``.

    Paths are stable POSIX-style relative names so inventories compare the
    same way on Windows and POSIX; byte counts and SHA-256 values describe the
    source at the instant the inventory is produced.
    """
    root = Path(source_root).resolve()
    if not root.is_dir():
        raise MigrationError(f"migration source root is not a directory: {root}")

    entries: list[InventoryFile] = []
    for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
        if path.is_symlink():
            raise MigrationError(f"symbolic links are not supported: {path}")
        if not path.is_file():
            continue
        size, sha256 = _size_and_sha256(path)
        entries.append(
            InventoryFile(
                path=path.relative_to(root).as_posix(),
                size=size,
                sha256=sha256,
            )
        )
    return tuple(entries)


@dataclass(frozen=True)
class MigrationFile:
    """A content-addressed copy from one absolute path to another."""

    source: Path
    destination: Path
    size: int
    sha256: str

    @classmethod
    def from_paths(cls, source: str | Path, destination: str | Path) -> "MigrationFile":
        source_path = Path(source).resolve()
        destination_path = Path(destination).resolve()
        size, sha256 = _size_and_sha256(source_path)
        return cls(source_path, destination_path, size, sha256)

    def to_dict(self) -> dict[str, object]:
        return {
            "from": str(self.source),
            "to": str(self.destination),
            "size": self.size,
            "sha256": self.sha256,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, object]) -> "MigrationFile":
        source = value.get("from")
        destination = value.get("to")
        size = value.get("size")
        sha256 = value.get("sha256")
        if not isinstance(source, str) or not isinstance(destination, str):
            raise MigrationError("migration file requires string 'from' and 'to' paths")
        if not isinstance(size, int) or size < 0:
            raise MigrationError("migration file size must be a non-negative integer")
        if (
            not isinstance(sha256, str)
            or len(sha256) != 64
            or any(char not in "0123456789abcdef" for char in sha256)
        ):
            raise MigrationError("migration file sha256 must be a lowercase SHA-256 digest")
        return cls(Path(source).resolve(), Path(destination).resolve(), size, sha256)


def _path_key(path: Path) -> str:
    return os.path.normcase(str(path.resolve()))


def _destination_matches(entry: MigrationFile) -> bool:
    destination = entry.destination
    if destination.is_symlink() or not destination.is_file():
        return False
    if destination.stat().st_size != entry.size:
        return False
    return _sha256_file(destination) == entry.sha256


def _default_rollback_path(files: tuple[MigrationFile, ...]) -> Path:
    if not files:
        return (Path.cwd() / ".migration-rollback.json").resolve()
    common = Path(os.path.commonpath([str(entry.destination.parent) for entry in files]))
    return (common / ".migration-rollback.json").resolve()


@dataclass(frozen=True)
class MigrationPlan:
    """Validated immutable copy plan suitable for JSON persistence."""

    files: tuple[MigrationFile, ...]
    rollback_manifest_path: Path
    version: int = 1

    @classmethod
    def from_files(
        cls,
        files: Iterable[MigrationFile],
        *,
        rollback_manifest_path: str | Path | None = None,
    ) -> "MigrationPlan":
        unique: dict[str, MigrationFile] = {}
        for entry in files:
            key = _path_key(entry.destination)
            previous = unique.get(key)
            if previous is not None:
                if previous.size != entry.size or previous.sha256 != entry.sha256:
                    raise MigrationCollisionError(
                        f"different sources target the same destination: {entry.destination}"
                    )
                continue
            unique[key] = entry

        ordered = tuple(sorted(unique.values(), key=lambda item: _path_key(item.destination)))
        rollback = (
            Path(rollback_manifest_path).resolve()
            if rollback_manifest_path is not None
            else _default_rollback_path(ordered)
        )
        if any(_path_key(entry.destination) == _path_key(rollback) for entry in ordered):
            raise MigrationCollisionError(
                f"rollback manifest collides with a planned destination: {rollback}"
            )

        for entry in ordered:
            destination = entry.destination
            if destination.exists() or destination.is_symlink():
                if not _destination_matches(entry):
                    raise MigrationCollisionError(
                        f"destination contains different content: {destination}"
                    )
        return cls(files=ordered, rollback_manifest_path=rollback)

    def to_dict(self) -> dict[str, object]:
        return {
            "version": self.version,
            "rollback_manifest": str(self.rollback_manifest_path),
            "files": [entry.to_dict() for entry in self.files],
        }

    def write(self, path: str | Path) -> Path:
        output = Path(path).resolve()
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(
            json.dumps(self.to_dict(), indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return output


def plan_migration(
    source_root: str | Path,
    destination_root: str | Path,
    *,
    plan_path: str | Path | None = None,
    rollback_manifest_path: str | Path | None = None,
) -> MigrationPlan:
    """Map a source tree to the same relative paths below a destination.

    Planning reads both trees and rejects different-content destinations.  It
    writes only when ``plan_path`` is explicitly supplied.
    """
    source = Path(source_root).resolve()
    destination = Path(destination_root).resolve()
    inventory = inventory_source_files(source)
    files = [
        MigrationFile(
            source=source / entry.path,
            destination=destination / entry.path,
            size=entry.size,
            sha256=entry.sha256,
        )
        for entry in inventory
    ]
    rollback = (
        Path(rollback_manifest_path).resolve()
        if rollback_manifest_path is not None
        else destination / ".migration-rollback.json"
    )
    plan = MigrationPlan.from_files(files, rollback_manifest_path=rollback)
    if plan_path is not None:
        plan.write(plan_path)
    return plan


def load_migration_plan(path: str | Path) -> MigrationPlan:
    """Load and validate a JSON migration plan."""
    plan_path = Path(path)
    try:
        payload = json.loads(plan_path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise MigrationError(f"migration plan not found: {plan_path}") from exc
    except json.JSONDecodeError as exc:
        raise MigrationError(f"invalid migration plan JSON: {plan_path}: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("version") != 1:
        raise MigrationError("unsupported migration plan version")
    files_value = payload.get("files")
    rollback = payload.get("rollback_manifest")
    if not isinstance(files_value, list) or not all(isinstance(item, dict) for item in files_value):
        raise MigrationError("migration plan files must be a list of objects")
    if not isinstance(rollback, str) or not rollback:
        raise MigrationError("migration plan requires rollback_manifest")
    return MigrationPlan.from_files(
        (MigrationFile.from_dict(item) for item in files_value),
        rollback_manifest_path=rollback,
    )


@dataclass(frozen=True)
class MigrationResult:
    dry_run: bool
    would_copy: tuple[Path, ...]
    copied: tuple[Path, ...]
    skipped: tuple[Path, ...]
    rollback_manifest_path: Path


@dataclass(frozen=True)
class SharedAssetDedupResult:
    """Result of product-local, hash-based shared-asset hardlinking.

    Legacy roots are never touched.  Production paths remain valid, while
    duplicate directory entries point at one canonical file below
    ``shared/assets/by-hash`` and therefore occupy one physical copy on filesystems
    that support hardlinks.
    """

    dry_run: bool
    canonical_files: tuple[Path, ...]
    relinked: tuple[Path, ...]
    skipped: tuple[Path, ...]
    report_path: Path


def _plan_digest(plan: MigrationPlan) -> str:
    canonical = json.dumps(
        [entry.to_dict() for entry in plan.files],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(canonical).hexdigest()


def _verify_source(entry: MigrationFile) -> None:
    try:
        size, sha256 = _size_and_sha256(entry.source)
    except MigrationError as exc:
        raise MigrationIntegrityError(str(exc)) from exc
    if size != entry.size or sha256 != entry.sha256:
        raise MigrationIntegrityError(
            f"source changed after planning: {entry.source}"
        )


def _rollback_entry(entry: MigrationFile) -> dict[str, object]:
    return {
        "path": str(entry.destination),
        "size": entry.size,
        "sha256": entry.sha256,
    }


def _load_existing_rollback(plan: MigrationPlan) -> dict[str, object] | None:
    path = plan.rollback_manifest_path
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MigrationError(f"invalid rollback manifest: {path}") from exc
    if (
        not isinstance(payload, dict)
        or payload.get("version") != 1
        or payload.get("plan_sha256") != _plan_digest(plan)
        or not isinstance(payload.get("created"), list)
    ):
        raise MigrationCollisionError(
            f"rollback manifest belongs to a different migration: {path}"
        )
    return payload


def apply_migration_plan(
    plan: MigrationPlan | str | Path,
    *,
    dry_run: bool = False,
) -> MigrationResult:
    """Copy and verify a plan, preserving all source and existing files.

    A full preflight runs before the first write.  Same-hash destinations are
    idempotent skips; different content is always a collision.  The rollback
    manifest lists only destination files created by this migration, so a
    caller can switch manifests/defaults back and knows exactly which new
    bytes were introduced without restoring any backup.
    """
    resolved_plan = load_migration_plan(plan) if isinstance(plan, (str, Path)) else plan
    if not isinstance(resolved_plan, MigrationPlan):
        raise TypeError("plan must be a MigrationPlan or a JSON plan path")

    would_copy: list[Path] = []
    skipped: list[Path] = []
    for entry in resolved_plan.files:
        _verify_source(entry)
        destination = entry.destination
        if destination.exists() or destination.is_symlink():
            if not _destination_matches(entry):
                raise MigrationCollisionError(
                    f"destination contains different content: {destination}"
                )
            skipped.append(destination)
        else:
            would_copy.append(destination)

    if dry_run:
        return MigrationResult(
            dry_run=True,
            would_copy=tuple(would_copy),
            copied=(),
            skipped=tuple(skipped),
            rollback_manifest_path=resolved_plan.rollback_manifest_path,
        )

    existing_rollback = _load_existing_rollback(resolved_plan)
    copied: list[Path] = []
    copied_entries: list[MigrationFile] = []
    for entry in resolved_plan.files:
        if entry.destination in skipped:
            continue
        # Recheck immediately before copying in case another process won the
        # race between preflight and this operation.
        if entry.destination.exists() or entry.destination.is_symlink():
            if _destination_matches(entry):
                skipped.append(entry.destination)
                continue
            raise MigrationCollisionError(
                f"destination contains different content: {entry.destination}"
            )
        entry.destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(entry.source, entry.destination)
        if not _destination_matches(entry):
            raise MigrationIntegrityError(
                f"post-copy hash verification failed: {entry.destination}"
            )
        copied.append(entry.destination)
        copied_entries.append(entry)

    if existing_rollback is None or copied_entries:
        created_by_path: dict[str, dict[str, object]] = {}
        if existing_rollback is not None:
            for item in existing_rollback["created"]:
                if isinstance(item, dict) and isinstance(item.get("path"), str):
                    created_by_path[_path_key(Path(item["path"]))] = item
        for entry in copied_entries:
            created_by_path[_path_key(entry.destination)] = _rollback_entry(entry)
        payload = {
            "version": 1,
            "plan_sha256": _plan_digest(resolved_plan),
            "created": [created_by_path[key] for key in sorted(created_by_path)],
        }
        rollback = resolved_plan.rollback_manifest_path
        rollback.parent.mkdir(parents=True, exist_ok=True)
        rollback.write_text(
            json.dumps(payload, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )

    return MigrationResult(
        dry_run=False,
        would_copy=tuple(would_copy),
        copied=tuple(copied),
        skipped=tuple(skipped),
        rollback_manifest_path=resolved_plan.rollback_manifest_path,
    )


def _product_asset_candidates(product_root: Path) -> tuple[Path, ...]:
    candidates: list[Path] = []
    for collection in ("devlogs", "reels"):
        collection_root = product_root / collection
        if not collection_root.is_dir():
            continue
        for production in sorted(path for path in collection_root.iterdir() if path.is_dir()):
            data_root = production / "data"
            for dirname in SHAREABLE_PRODUCTION_DIRS:
                asset_root = data_root / dirname
                if not asset_root.is_dir():
                    continue
                for path in sorted(asset_root.rglob("*")):
                    if path.is_symlink():
                        raise MigrationError(f"symbolic links are not supported: {path}")
                    if path.is_file():
                        candidates.append(path.resolve())
    return tuple(candidates)


def deduplicate_product_assets(
    product_root: str | Path,
    *,
    dry_run: bool = True,
    report_path: str | Path | None = None,
) -> SharedAssetDedupResult:
    """Store repeated production assets once without changing public paths.

    Only exact SHA-256 duplicates occurring in at least two productions are
    eligible.  The operation first creates and verifies a canonical shared copy,
    then atomically replaces each duplicate with a hardlink.  A byte-level report
    makes the transformation auditable; source/legacy project roots remain intact.
    """

    root = Path(product_root).resolve()
    if not (root / "product.toml").is_file():
        raise MigrationError(f"product manifest not found: {root / 'product.toml'}")
    report = (
        Path(report_path).resolve()
        if report_path is not None
        else (root / "shared" / "migration" / "dedup_report.json").resolve()
    )

    by_hash: dict[str, list[Path]] = {}
    sizes: dict[str, int] = {}
    for path in _product_asset_candidates(root):
        size, sha256 = _size_and_sha256(path)
        by_hash.setdefault(sha256, []).append(path)
        sizes[sha256] = size

    def production_key(path: Path) -> tuple[str, str]:
        relative = path.relative_to(root)
        return relative.parts[0], relative.parts[1]

    groups = {
        sha256: tuple(sorted(paths, key=_path_key))
        for sha256, paths in by_hash.items()
        if len({production_key(path) for path in paths}) >= 2
    }
    canonical_files: list[Path] = []
    relinked: list[Path] = []
    skipped: list[Path] = []
    report_groups: list[dict[str, object]] = []

    for sha256 in sorted(groups):
        aliases = groups[sha256]
        extension = aliases[0].suffix.lower()
        canonical = (
            root / "shared" / "assets" / "by-hash" / sha256[:2] / f"{sha256}{extension}"
        ).resolve()
        canonical_files.append(canonical)
        report_groups.append(
            {
                "sha256": sha256,
                "size": sizes[sha256],
                "canonical": str(canonical),
                "aliases": [str(path) for path in aliases],
            }
        )
        if dry_run:
            relinked.extend(aliases)
            continue

        if canonical.exists() or canonical.is_symlink():
            if canonical.is_symlink() or not canonical.is_file():
                raise MigrationCollisionError(f"invalid shared canonical path: {canonical}")
            canonical_size, canonical_hash = _size_and_sha256(canonical)
            if canonical_size != sizes[sha256] or canonical_hash != sha256:
                raise MigrationCollisionError(
                    f"shared canonical contains different content: {canonical}"
                )
        else:
            canonical.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(aliases[0], canonical)
            canonical_size, canonical_hash = _size_and_sha256(canonical)
            if canonical_size != sizes[sha256] or canonical_hash != sha256:
                raise MigrationIntegrityError(
                    f"shared canonical hash verification failed: {canonical}"
                )

        for alias in aliases:
            try:
                if os.path.samefile(alias, canonical):
                    skipped.append(alias)
                    continue
            except OSError:
                pass
            temporary = alias.with_name(f".{alias.name}.dedupe-link.tmp")
            if temporary.exists() or temporary.is_symlink():
                raise MigrationCollisionError(f"temporary dedup path exists: {temporary}")
            try:
                os.link(canonical, temporary)
                linked_size, linked_hash = _size_and_sha256(temporary)
                if linked_size != sizes[sha256] or linked_hash != sha256:
                    raise MigrationIntegrityError(
                        f"temporary hardlink verification failed: {temporary}"
                    )
                os.replace(temporary, alias)
            finally:
                if temporary.exists() or temporary.is_symlink():
                    temporary.unlink()
            if not os.path.samefile(alias, canonical):
                raise MigrationIntegrityError(f"asset was not hardlinked: {alias}")
            relinked.append(alias)

    if not dry_run:
        report.parent.mkdir(parents=True, exist_ok=True)
        report.write_text(
            json.dumps(
                {
                    "version": 1,
                    "product_root": str(root),
                    "physical_storage": "hardlink",
                    "groups": report_groups,
                },
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    return SharedAssetDedupResult(
        dry_run=dry_run,
        canonical_files=tuple(canonical_files),
        relinked=tuple(relinked),
        skipped=tuple(skipped),
        report_path=report,
    )


__all__ = [
    "InventoryFile",
    "MigrationCollisionError",
    "MigrationError",
    "MigrationFile",
    "MigrationIntegrityError",
    "MigrationPlan",
    "MigrationResult",
    "SHAREABLE_PRODUCTION_DIRS",
    "SharedAssetDedupResult",
    "apply_migration_plan",
    "deduplicate_product_assets",
    "inventory_source_files",
    "load_migration_plan",
    "plan_migration",
]
