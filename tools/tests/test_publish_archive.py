from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.publish_archive import ArchiveConflict, archive_publish_packages


def _write(path: Path, content: bytes | str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    if isinstance(content, bytes):
        path.write_bytes(content)
    else:
        path.write_text(content, encoding="utf-8")
    return path


def _make_delivered_production(
    workspace: Path,
    *,
    product: str = "game",
    collection: str = "devlogs",
    production: str = "2026_07_26_devlog_01",
) -> None:
    production_root = workspace / product / collection / production
    publish = production_root / "data" / "publish"
    delivery = workspace / product / "delivery" / collection / production

    _write(publish / "youtube_package.md", "# Description")
    _write(publish / "music_license.md", "CC0")
    _write(publish / "thumbnail.png", b"publish-thumbnail")
    _write(publish / "publish.json", json.dumps({"version": 1}))
    _write(production_root / "data" / "recordings" / "raw.wav", b"raw voice")

    _write(delivery / "video.mp4", b"final-video")
    _write(delivery / "thumbnail.png", b"delivery-thumbnail")
    _write(delivery / "metadata.md", "# Final metadata")
    _write(delivery / "delivery_manifest.json", json.dumps({"version": 1}))


def test_archives_only_the_final_publish_package_and_merges_delivery_files(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    destination = tmp_path / "yandex" / "Devlogs" / "projects"
    _make_delivered_production(workspace)
    _write(
        workspace
        / "game"
        / "delivery"
        / "devlogs"
        / "2026_07_26_devlog_01_pre_fix"
        / "video.mp4",
        b"obsolete",
    )

    report = archive_publish_packages(workspace, destination)

    archived = (
        destination
        / "game"
        / "devlogs"
        / "2026_07_26_devlog_01"
        / "publish"
    )
    assert (archived / "video.mp4").read_bytes() == b"final-video"
    assert (archived / "thumbnail.png").read_bytes() == b"delivery-thumbnail"
    assert (archived / "youtube_package.md").read_text(encoding="utf-8") == (
        "# Description"
    )
    assert (archived / "music_license.md").read_text(encoding="utf-8") == "CC0"
    assert (archived / "delivery_manifest.json").is_file()
    assert not (destination / "game" / "recordings").exists()
    assert not any(destination.rglob("*pre_fix*"))
    assert report.packages == 1
    assert report.copied >= 6
    assert report.conflicts == 0


def test_ignores_publish_directories_without_a_final_delivery_video(
    tmp_path: Path,
) -> None:
    workspace = tmp_path / "workspace"
    destination = tmp_path / "yandex" / "Devlogs" / "projects"
    _write(
        workspace
        / "game"
        / "devlogs"
        / "2026_07_26_devlog_02"
        / "data"
        / "publish"
        / "youtube_package.md",
        "draft",
    )

    report = archive_publish_packages(workspace, destination)

    assert report.packages == 0
    assert not destination.exists()


def test_repeated_archive_is_idempotent_when_hashes_match(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    destination = tmp_path / "yandex" / "Devlogs" / "projects"
    _make_delivered_production(workspace)

    first = archive_publish_packages(workspace, destination)
    second = archive_publish_packages(workspace, destination)

    assert first.copied > 0
    assert second.copied == 0
    assert second.skipped == first.copied
    assert second.conflicts == 0


def test_refuses_to_overwrite_a_different_archived_file(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    destination = tmp_path / "yandex" / "Devlogs" / "projects"
    _make_delivered_production(workspace)
    conflicting = (
        destination
        / "game"
        / "devlogs"
        / "2026_07_26_devlog_01"
        / "publish"
        / "video.mp4"
    )
    _write(conflicting, b"older-different-final")

    with pytest.raises(ArchiveConflict, match="video.mp4"):
        archive_publish_packages(workspace, destination)

    assert conflicting.read_bytes() == b"older-different-final"
