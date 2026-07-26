"""Copy final Studio publish packages to an append-only external archive."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import sys
import uuid
from dataclasses import asdict, dataclass
from pathlib import Path


class ArchiveConflict(RuntimeError):
    """Raised when an archive path already contains different bytes."""


@dataclass(frozen=True)
class ArchiveReport:
    packages: int
    copied: int
    skipped: int
    conflicts: int
    bytes_copied: int
    destination: str
    dry_run: bool


@dataclass(frozen=True)
class _Package:
    product: str
    collection: str
    production: str
    files: dict[Path, Path]


_OBSOLETE_MARKERS = (
    "_pre_fix",
    "_pre_caption_fix",
    "_draft",
    "_backup",
    "_old",
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _is_obsolete_production(name: str) -> bool:
    folded = name.casefold()
    return any(marker in folded for marker in _OBSOLETE_MARKERS)


def _relative_files(root: Path) -> dict[Path, Path]:
    if not root.is_dir():
        return {}
    return {
        path.relative_to(root): path
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def _discover_packages(workspace: Path) -> list[_Package]:
    packages: list[_Package] = []
    for product_root in sorted(workspace.iterdir() if workspace.is_dir() else ()):
        if not product_root.is_dir() or product_root.name.startswith("."):
            continue
        delivery_root = product_root / "delivery"
        if not delivery_root.is_dir():
            continue
        for collection in ("devlogs", "reels"):
            collection_root = delivery_root / collection
            if not collection_root.is_dir():
                continue
            for delivery in sorted(collection_root.iterdir()):
                if not delivery.is_dir() or _is_obsolete_production(delivery.name):
                    continue
                if not (delivery / "video.mp4").is_file():
                    continue

                files = _relative_files(
                    product_root
                    / collection
                    / delivery.name
                    / "data"
                    / "publish"
                )
                # The immutable delivery bundle wins when a production publish
                # directory contains an earlier image, metadata, or video.
                files.update(_relative_files(delivery))
                packages.append(
                    _Package(
                        product=product_root.name,
                        collection=collection,
                        production=delivery.name,
                        files=files,
                    )
                )
    return packages


def _copy_verified(source: Path, destination: Path) -> int:
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = destination.with_name(
        f".{destination.name}.archive-{uuid.uuid4().hex}.tmp"
    )
    try:
        shutil.copy2(source, temporary)
        source_hash = _sha256(source)
        if _sha256(temporary) != source_hash:
            raise OSError(f"SHA-256 verification failed for {source}")
        os.replace(temporary, destination)
        if _sha256(destination) != source_hash:
            raise OSError(f"post-copy SHA-256 verification failed for {destination}")
    finally:
        temporary.unlink(missing_ok=True)
    return source.stat().st_size


def archive_publish_packages(
    workspace: str | Path,
    destination: str | Path,
    *,
    dry_run: bool = False,
) -> ArchiveReport:
    """Archive all delivered publish packages without deleting or overwriting."""

    workspace_path = Path(workspace).resolve()
    destination_path = Path(destination).resolve()
    packages = _discover_packages(workspace_path)

    copy_plan: list[tuple[Path, Path]] = []
    skipped = 0
    conflicts: list[Path] = []
    for package in packages:
        package_destination = (
            destination_path
            / package.product
            / package.collection
            / package.production
            / "publish"
        )
        for relative, source in package.files.items():
            target = package_destination / relative
            if not target.exists():
                copy_plan.append((source, target))
            elif target.is_file() and _sha256(source) == _sha256(target):
                skipped += 1
            else:
                conflicts.append(target)

    if conflicts:
        joined = ", ".join(str(path) for path in conflicts)
        raise ArchiveConflict(
            "archive is append-only; refusing to overwrite different files: "
            f"{joined}"
        )

    copied = 0
    bytes_copied = 0
    if not dry_run:
        for source, target in copy_plan:
            bytes_copied += _copy_verified(source, target)
            copied += 1

    return ArchiveReport(
        packages=len(packages),
        copied=copied if not dry_run else len(copy_plan),
        skipped=skipped,
        conflicts=0,
        bytes_copied=bytes_copied,
        destination=str(destination_path),
        dry_run=dry_run,
    )


def _default_destination() -> Path | None:
    configured = os.environ.get("DEVLOG_PUBLISH_ARCHIVE")
    if configured:
        return Path(configured)
    if os.name == "nt":
        candidate = Path.home() / "YandexDisk" / "Devlogs" / "projects"
        if candidate.parent.parent.is_dir():
            return candidate
    return None


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Copy delivered videos and their complete publish folders to an "
            "append-only external archive."
        )
    )
    parser.add_argument(
        "--workspace",
        type=Path,
        default=Path.cwd(),
        help="devlogs workspace root (default: current directory)",
    )
    parser.add_argument(
        "--destination",
        type=Path,
        default=_default_destination(),
        help=(
            "archive projects root; defaults to "
            "%%USERPROFILE%%\\YandexDisk\\Devlogs\\projects when available"
        ),
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="list and hash the plan without creating archive files",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _parser()
    args = parser.parse_args(argv)
    if args.destination is None:
        parser.error(
            "--destination is required because no YandexDisk folder was detected"
        )
    try:
        report = archive_publish_packages(
            args.workspace,
            args.destination,
            dry_run=args.dry_run,
        )
    except ArchiveConflict as exc:
        print(f"[publish-archive] ERROR: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(asdict(report), ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
