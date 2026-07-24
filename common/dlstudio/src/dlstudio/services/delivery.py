"""Deterministic, content-verified production delivery bundles.

The service is intentionally below the CLI layer.  Callers supply the exact
final artifacts; this module validates their publish metadata and copies them
to the output root already resolved by :class:`ProductionManifest`.  It never
searches ``finalize`` or ``publish`` directories for likely-looking files.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import tempfile
import unicodedata
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

from dlstudio.production import ProductionManifest


class DeliveryError(RuntimeError):
    """Base class for delivery validation, collision, and integrity errors."""


class DeliveryValidationError(DeliveryError):
    """A required artifact or metadata field is absent or invalid."""


class DeliveryCollisionError(DeliveryError):
    """A delivery destination already contains different content."""


class DeliveryIntegrityError(DeliveryError):
    """Copied bytes do not match their source SHA-256."""


@dataclass(frozen=True)
class DeliveryMetadata:
    """Validated fields extracted from ``metadata.md``."""

    title: str
    description: str
    tags: tuple[str, ...]
    hashtags: tuple[str, ...]
    chapters: tuple[str, ...]


@dataclass(frozen=True)
class DeliveryResult:
    """Paths and copy disposition for one completed delivery bundle."""

    delivery_dir: Path
    video_path: Path
    metadata_path: Path
    image_path: Path
    manifest_path: Path
    metadata: DeliveryMetadata
    copied: tuple[Path, ...]
    skipped: tuple[Path, ...]


@dataclass(frozen=True)
class _DeliveryFile:
    role: str
    source: Path
    destination: Path
    size: int
    sha256: str


_HEADING_RE = re.compile(r"^\s{0,3}#{1,6}\s+(.+?)\s*#*\s*$")
_SECTION_ALIASES = {
    "title": "title",
    "selected title": "title",
    "description": "description",
    "tags": "tags",
    "youtube tags": "tags",
    "youtube keyword tags": "tags",
    "hashtags": "hashtags",
    "copy ready hashtags": "hashtags",
    "chapters": "chapters",
}


def _normalise_heading(value: str) -> str:
    value = value.casefold().replace("-", " ").replace("_", " ")
    return " ".join(value.split())


def _section_lines(markdown: str) -> dict[str, list[str]]:
    sections: dict[str, list[str]] = {
        "title": [],
        "description": [],
        "tags": [],
        "hashtags": [],
        "chapters": [],
    }
    current: str | None = None
    for line in markdown.splitlines():
        match = _HEADING_RE.match(line)
        if match:
            current = _SECTION_ALIASES.get(_normalise_heading(match.group(1)))
            continue
        if current is not None:
            sections[current].append(line)
    return sections


def _nonempty_lines(lines: Iterable[str]) -> tuple[str, ...]:
    return tuple(line.strip() for line in lines if line.strip())


def _parse_tags(lines: Iterable[str]) -> tuple[str, ...]:
    values: list[str] = []
    for line in _nonempty_lines(lines):
        line = re.sub(r"^[-*+]\s+", "", line)
        values.extend(part.strip() for part in line.split(",") if part.strip())
    return tuple(values)


def _valid_hashtag(value: str) -> bool:
    if not value.startswith("#") or len(value) == 1:
        return False
    return all(
        char == "_" or unicodedata.category(char)[0] in {"L", "N"}
        for char in value[1:]
    )


def validate_hashtags(values: Iterable[str]) -> tuple[str, ...]:
    """Return hashtags as a tuple, rejecting anything outside ``L/N/_``.

    Validation is deliberately token-level.  Thus ``#game dev`` cannot be
    mistaken for one hashtag: ``dev`` is a second, invalid token.
    """
    hashtags = tuple(values)
    if not hashtags:
        raise DeliveryValidationError("metadata must contain copy-ready hashtags")
    invalid = [value for value in hashtags if not _valid_hashtag(value)]
    if invalid:
        raise DeliveryValidationError(
            "invalid hashtag token(s): " + ", ".join(repr(value) for value in invalid)
        )
    return hashtags


def parse_metadata(markdown: str) -> DeliveryMetadata:
    """Parse and validate the publish fields in delivery markdown.

    YouTube keyword tags are comma-separated and may contain spaces.  The
    hashtag section is parsed separately as whitespace-delimited copy-ready
    tokens, each of which must match ``^#[\\p{L}\\p{N}_]+$`` semantics.
    """
    if not isinstance(markdown, str):
        raise TypeError("markdown must be a string")
    sections = _section_lines(markdown)
    title_lines = _nonempty_lines(sections["title"])
    description_lines = _nonempty_lines(sections["description"])
    if not title_lines:
        raise DeliveryValidationError("metadata title is required")
    if not description_lines:
        raise DeliveryValidationError("metadata description is required")

    hashtag_tokens = tuple(
        token
        for line in _nonempty_lines(sections["hashtags"])
        for token in line.split()
    )
    return DeliveryMetadata(
        title=" ".join(title_lines),
        description="\n".join(description_lines),
        tags=_parse_tags(sections["tags"]),
        hashtags=validate_hashtags(hashtag_tokens),
        chapters=_nonempty_lines(sections["chapters"]),
    )


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _source_file(path_value: str | Path, role: str) -> tuple[Path, int, str]:
    path = Path(path_value).resolve()
    if path.is_symlink() or not path.is_file():
        raise DeliveryValidationError(
            f"required {role} source is not a regular file: {path}"
        )
    try:
        size = path.stat().st_size
        sha256 = _sha256_file(path)
    except OSError as exc:
        raise DeliveryValidationError(f"cannot read required {role} source: {path}") from exc
    return path, size, sha256


def _destination_matches(entry: _DeliveryFile) -> bool:
    path = entry.destination
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return path.stat().st_size == entry.size and _sha256_file(path) == entry.sha256
    except OSError:
        return False


def _manifest_bytes(
    manifest: ProductionManifest,
    entries: tuple[_DeliveryFile, ...],
    metadata: DeliveryMetadata,
) -> bytes:
    payload = {
        "version": 1,
        "product_id": manifest.product.id,
        "production_id": manifest.id,
        "production_kind": manifest.kind,
        "metadata": {
            "title": metadata.title,
            "description": metadata.description,
            "tags": list(metadata.tags),
            "hashtags": list(metadata.hashtags),
            "chapters": list(metadata.chapters),
        },
        "files": [
            {
                "role": entry.role,
                "source": str(entry.source),
                "destination": str(entry.destination),
                "size": entry.size,
                "source_sha256": entry.sha256,
                "destination_sha256": entry.sha256,
            }
            for entry in entries
        ],
    }
    return (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode(
        "utf-8"
    )


def _atomic_copy(entry: _DeliveryFile) -> None:
    entry.destination.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{entry.destination.name}.",
        suffix=".tmp",
        dir=entry.destination.parent,
    )
    os.close(handle)
    temporary = Path(temporary_name)
    try:
        shutil.copy2(entry.source, temporary)
        if temporary.stat().st_size != entry.size or _sha256_file(temporary) != entry.sha256:
            raise DeliveryIntegrityError(
                f"post-copy hash verification failed: {entry.destination}"
            )
        os.replace(temporary, entry.destination)
    finally:
        temporary.unlink(missing_ok=True)


def _atomic_write(path: Path, content: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "wb") as stream:
            stream.write(content)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _file_bytes_match(path: Path, content: bytes) -> bool:
    if path.is_symlink() or not path.is_file():
        return False
    try:
        return path.read_bytes() == content
    except OSError:
        return False


def build_delivery_bundle(
    manifest: ProductionManifest,
    *,
    video_path: str | Path,
    metadata_path: str | Path,
    image_path: str | Path,
    overwrite: bool = False,
) -> DeliveryResult:
    """Validate, copy, and SHA-verify one production's delivery bundle.

    The output names are fixed: ``video.mp4``, ``metadata.md``, and either
    ``thumbnail.png`` (devlog) or ``cover.png`` (reel).  Existing same-hash
    files are idempotent skips.  Existing different bytes cause a collision
    unless the caller explicitly passes ``overwrite=True``.
    """
    if not isinstance(manifest, ProductionManifest):
        raise TypeError("manifest must be a ProductionManifest")
    if manifest.kind not in {"devlog", "reel"}:
        raise DeliveryValidationError(f"unsupported production kind: {manifest.kind!r}")

    video_source, video_size, video_hash = _source_file(video_path, "video")
    metadata_source, metadata_size, metadata_hash = _source_file(metadata_path, "metadata")
    image_source, image_size, image_hash = _source_file(image_path, "image")
    try:
        metadata_text = metadata_source.read_text(encoding="utf-8")
    except (OSError, UnicodeError) as exc:
        raise DeliveryValidationError(
            f"metadata must be readable UTF-8 text: {metadata_source}"
        ) from exc
    parsed_metadata = parse_metadata(metadata_text)

    delivery_dir = manifest.delivery_dir.resolve()
    image_name = "thumbnail.png" if manifest.kind == "devlog" else "cover.png"
    entries = (
        _DeliveryFile("video", video_source, delivery_dir / "video.mp4", video_size, video_hash),
        _DeliveryFile(
            "metadata",
            metadata_source,
            delivery_dir / "metadata.md",
            metadata_size,
            metadata_hash,
        ),
        _DeliveryFile("image", image_source, delivery_dir / image_name, image_size, image_hash),
    )
    manifest_path = delivery_dir / "delivery_manifest.json"
    desired_manifest = _manifest_bytes(manifest, entries, parsed_metadata)

    skipped_entries: list[_DeliveryFile] = []
    for entry in entries:
        destination = entry.destination
        if destination.exists() or destination.is_symlink():
            if _destination_matches(entry):
                skipped_entries.append(entry)
            elif not overwrite:
                raise DeliveryCollisionError(
                    f"destination contains different content: {destination}"
                )
    manifest_matches = False
    if manifest_path.exists() or manifest_path.is_symlink():
        manifest_matches = _file_bytes_match(manifest_path, desired_manifest)
        if not manifest_matches and not overwrite:
            raise DeliveryCollisionError(
                f"destination contains different content: {manifest_path}"
            )

    copied: list[Path] = []
    skipped: list[Path] = []
    for entry in entries:
        if entry in skipped_entries:
            skipped.append(entry.destination)
            continue
        # Recheck at the write boundary: another process may have populated
        # the path after preflight, and overwrite=False is a hard guarantee.
        if entry.destination.exists() or entry.destination.is_symlink():
            if _destination_matches(entry):
                skipped.append(entry.destination)
                continue
            if not overwrite:
                raise DeliveryCollisionError(
                    f"destination contains different content: {entry.destination}"
                )
        _atomic_copy(entry)
        if not _destination_matches(entry):
            raise DeliveryIntegrityError(
                f"destination hash does not match source: {entry.destination}"
            )
        copied.append(entry.destination)

    if manifest_matches:
        skipped.append(manifest_path)
    else:
        write_manifest = True
        if manifest_path.exists() or manifest_path.is_symlink():
            if _file_bytes_match(manifest_path, desired_manifest):
                skipped.append(manifest_path)
                write_manifest = False
            elif not overwrite:
                raise DeliveryCollisionError(
                    f"destination contains different content: {manifest_path}"
                )
        if write_manifest:
            _atomic_write(manifest_path, desired_manifest)
            if not _file_bytes_match(manifest_path, desired_manifest):
                raise DeliveryIntegrityError(
                    f"delivery manifest verification failed: {manifest_path}"
                )
            copied.append(manifest_path)

    return DeliveryResult(
        delivery_dir=delivery_dir,
        video_path=entries[0].destination,
        metadata_path=entries[1].destination,
        image_path=entries[2].destination,
        manifest_path=manifest_path,
        metadata=parsed_metadata,
        copied=tuple(copied),
        skipped=tuple(skipped),
    )


__all__ = [
    "DeliveryCollisionError",
    "DeliveryError",
    "DeliveryIntegrityError",
    "DeliveryMetadata",
    "DeliveryResult",
    "DeliveryValidationError",
    "build_delivery_bundle",
    "parse_metadata",
    "validate_hashtags",
]
