from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from dlstudio.production import ProductManifest, ProductionManifest
from dlstudio.services.delivery import (
    DeliveryCollisionError,
    DeliveryValidationError,
    build_delivery_bundle,
    parse_metadata,
)


def _manifest(tmp_path: Path, *, kind: str = "devlog") -> ProductionManifest:
    product_root = (tmp_path / "product").resolve()
    production_id = f"2026_07_18_{kind}_01"
    product = ProductManifest(
        root=product_root,
        id="fixture_product",
        title="Fixture Product",
        version=1,
        game_root=(tmp_path / "game").resolve(),
        sources={},
        devlogs_dir=product_root / "devlogs",
        reels_dir=product_root / "reels",
        shared_dir=product_root / "shared",
        delivery_dir=product_root / "delivery",
    )
    production_root = product_root / ("devlogs" if kind == "devlog" else "reels") / production_id
    return ProductionManifest(
        root=production_root,
        id=production_id,
        kind=kind,
        date="2026-07-18",
        orientation="landscape" if kind == "devlog" else "vertical",
        version=1,
        edit_dir=production_root / "edit",
        data_dir=production_root / "data",
        delivery_dir=product.delivery_dir / ("devlogs" if kind == "devlog" else "reels") / production_id,
        product=product,
    )


def _sources(tmp_path: Path, *, metadata: str | None = None) -> tuple[Path, Path, Path]:
    source_dir = tmp_path / "sources"
    source_dir.mkdir()
    video = source_dir / "finished.mp4"
    video.write_bytes(b"final-video-bytes")
    metadata_path = source_dir / "youtube.md"
    metadata_path.write_text(
        metadata
        or """## Title
Building a Trolley Game

## Description
The real story of building the game in thirteen days.

## YouTube tags
game development, trolley problem, indie game

## Hashtags
#GameDev #IndieGame #Игра_2026

## Chapters
00:00 The problem
00:15 The build
""",
        encoding="utf-8",
    )
    image = source_dir / "art.png"
    image.write_bytes(b"thumbnail-png-bytes")
    return video, metadata_path, image


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def test_parse_metadata_keeps_multiword_tags_separate_from_valid_unicode_hashtags():
    parsed = parse_metadata(
        """## Title
Title
## Description
Description
## YouTube tags
game development, trolley problem
## Copy-ready hashtags
#GameDev #Игра_2026
"""
    )

    assert parsed.title == "Title"
    assert parsed.description == "Description"
    assert parsed.tags == ("game development", "trolley problem")
    assert parsed.hashtags == ("#GameDev", "#Игра_2026")


@pytest.mark.parametrize(
    "hashtags",
    ["#game dev", "game", "#game-dev", "#game!", "#"],
)
def test_parse_metadata_rejects_invalid_or_multiword_pseudo_hashtags(hashtags: str):
    with pytest.raises(DeliveryValidationError, match="hashtag"):
        parse_metadata(
            f"""## Title
Title
## Description
Description
## Tags
game development
## Hashtags
{hashtags}
"""
        )


@pytest.mark.parametrize(
    "metadata",
    [
        "## Description\nDescription\n## Hashtags\n#GameDev\n",
        "## Title\nTitle\n## Description\n   \n## Hashtags\n#GameDev\n",
    ],
)
def test_parse_metadata_requires_nonempty_title_and_description(metadata: str):
    with pytest.raises(DeliveryValidationError):
        parse_metadata(metadata)


def test_build_delivery_bundle_uses_manifest_directory_exact_names_and_hashes(tmp_path: Path):
    manifest = _manifest(tmp_path)
    video, metadata, image = _sources(tmp_path)

    result = build_delivery_bundle(
        manifest,
        video_path=video,
        metadata_path=metadata,
        image_path=image,
    )

    assert result.delivery_dir == manifest.delivery_dir.resolve()
    assert result.video_path == manifest.delivery_dir / "video.mp4"
    assert result.metadata_path == manifest.delivery_dir / "metadata.md"
    assert result.image_path == manifest.delivery_dir / "thumbnail.png"
    assert result.manifest_path == manifest.delivery_dir / "delivery_manifest.json"
    assert result.video_path.read_bytes() == video.read_bytes()
    assert result.metadata_path.read_bytes() == metadata.read_bytes()
    assert result.image_path.read_bytes() == image.read_bytes()

    payload = json.loads(result.manifest_path.read_text(encoding="utf-8"))
    assert payload["production_id"] == manifest.id
    assert payload["metadata"]["tags"] == [
        "game development",
        "trolley problem",
        "indie game",
    ]
    assert payload["metadata"]["hashtags"] == ["#GameDev", "#IndieGame", "#Игра_2026"]
    assert [entry["destination"] for entry in payload["files"]] == [
        str((manifest.delivery_dir / "video.mp4").resolve()),
        str((manifest.delivery_dir / "metadata.md").resolve()),
        str((manifest.delivery_dir / "thumbnail.png").resolve()),
    ]
    for entry in payload["files"]:
        assert entry["source_sha256"] == entry["destination_sha256"]
        assert entry["destination_sha256"] == _sha256(Path(entry["destination"]))


def test_reel_bundle_uses_cover_name(tmp_path: Path):
    manifest = _manifest(tmp_path, kind="reel")
    video, metadata, image = _sources(tmp_path)

    result = build_delivery_bundle(
        manifest,
        video_path=video,
        metadata_path=metadata,
        image_path=image,
    )

    assert result.image_path == manifest.delivery_dir / "cover.png"
    assert not (manifest.delivery_dir / "thumbnail.png").exists()


@pytest.mark.parametrize("missing", ["video", "metadata", "image"])
def test_bundle_rejects_missing_required_source_before_creating_delivery(
    tmp_path: Path, missing: str
):
    manifest = _manifest(tmp_path)
    video, metadata, image = _sources(tmp_path)
    {"video": video, "metadata": metadata, "image": image}[missing].unlink()

    with pytest.raises(DeliveryValidationError, match=missing):
        build_delivery_bundle(
            manifest,
            video_path=video,
            metadata_path=metadata,
            image_path=image,
        )

    assert not manifest.delivery_dir.exists()


def test_bundle_is_idempotent_when_destination_content_matches(tmp_path: Path):
    manifest = _manifest(tmp_path)
    video, metadata, image = _sources(tmp_path)
    first = build_delivery_bundle(
        manifest, video_path=video, metadata_path=metadata, image_path=image
    )

    second = build_delivery_bundle(
        manifest, video_path=video, metadata_path=metadata, image_path=image
    )

    assert second.copied == ()
    assert second.skipped == (
        first.video_path,
        first.metadata_path,
        first.image_path,
        first.manifest_path,
    )
    assert first.manifest_path.read_bytes() == second.manifest_path.read_bytes()


def test_bundle_refuses_to_overwrite_different_content_by_default(tmp_path: Path):
    manifest = _manifest(tmp_path)
    video, metadata, image = _sources(tmp_path)
    manifest.delivery_dir.mkdir(parents=True)
    destination = manifest.delivery_dir / "video.mp4"
    destination.write_bytes(b"an-existing-different-video")

    with pytest.raises(DeliveryCollisionError, match="video.mp4"):
        build_delivery_bundle(
            manifest,
            video_path=video,
            metadata_path=metadata,
            image_path=image,
        )

    assert destination.read_bytes() == b"an-existing-different-video"
    assert not (manifest.delivery_dir / "metadata.md").exists()


def test_bundle_overwrites_different_content_only_with_explicit_flag(tmp_path: Path):
    manifest = _manifest(tmp_path)
    video, metadata, image = _sources(tmp_path)
    manifest.delivery_dir.mkdir(parents=True)
    destination = manifest.delivery_dir / "video.mp4"
    destination.write_bytes(b"old-video")

    result = build_delivery_bundle(
        manifest,
        video_path=video,
        metadata_path=metadata,
        image_path=image,
        overwrite=True,
    )

    assert destination.read_bytes() == video.read_bytes()
    assert destination in result.copied
