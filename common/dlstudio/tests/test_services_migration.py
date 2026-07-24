"""Tests for safe, source-preserving filesystem migration primitives."""
from __future__ import annotations

import hashlib
import json

import pytest

from dlstudio.services import migration
from dlstudio.services.migration import (
    MigrationCollisionError,
    MigrationFile,
    MigrationIntegrityError,
    MigrationPlan,
    apply_migration_plan,
    deduplicate_product_assets,
    inventory_source_files,
    load_migration_plan,
    plan_migration,
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def test_inventory_records_relative_paths_sizes_and_sha256(tmp_path):
    source = tmp_path / "legacy"
    (source / "data" / "images").mkdir(parents=True)
    (source / "edit.py").write_bytes(b"EDIT = object()\n")
    (source / "data" / "images" / "frame.bin").write_bytes(b"\x00\x01\x02")

    inventory = inventory_source_files(source)

    assert [entry.path for entry in inventory] == [
        "data/images/frame.bin",
        "edit.py",
    ]
    assert inventory[0].size == 3
    assert inventory[0].sha256 == _sha256(b"\x00\x01\x02")
    assert inventory[1].size == len(b"EDIT = object()\n")
    assert inventory[1].sha256 == _sha256(b"EDIT = object()\n")


def test_plan_is_json_serializable_and_names_each_from_and_to(tmp_path):
    source = tmp_path / "legacy"
    target = tmp_path / "product" / "reels" / "2026_07_18_reel_01"
    source.mkdir()
    (source / "beats.py").write_bytes(b"BEATS = {}\n")
    plan_path = tmp_path / "migration-plan.json"

    plan = plan_migration(source, target, plan_path=plan_path)

    payload = json.loads(plan_path.read_text(encoding="utf-8"))
    assert payload["version"] == 1
    assert payload["files"] == [
        {
            "from": str((source / "beats.py").resolve()),
            "to": str((target / "beats.py").resolve()),
            "size": len("BEATS = {}\n".encode()),
            "sha256": _sha256(b"BEATS = {}\n"),
        }
    ]
    assert load_migration_plan(plan_path) == plan


def test_plan_detects_existing_destination_with_different_content(tmp_path):
    source = tmp_path / "legacy"
    target = tmp_path / "product"
    source.mkdir()
    target.mkdir()
    (source / "same-name.txt").write_text("source", encoding="utf-8")
    (target / "same-name.txt").write_text("different", encoding="utf-8")

    with pytest.raises(MigrationCollisionError, match="same-name.txt"):
        plan_migration(source, target)


def test_plan_detects_two_different_sources_for_one_destination(tmp_path):
    first = tmp_path / "first.txt"
    second = tmp_path / "second.txt"
    destination = tmp_path / "target.txt"
    first.write_text("first", encoding="utf-8")
    second.write_text("second", encoding="utf-8")

    with pytest.raises(MigrationCollisionError, match="target.txt"):
        MigrationPlan.from_files(
            [
                MigrationFile.from_paths(first, destination),
                MigrationFile.from_paths(second, destination),
            ]
        )


def test_dry_run_reports_copy_without_writing_any_files_or_directories(tmp_path):
    source = tmp_path / "legacy"
    target = tmp_path / "new" / "deep" / "production"
    source.mkdir()
    (source / "asset.bin").write_bytes(b"asset")
    rollback = tmp_path / "state" / "rollback.json"
    plan = plan_migration(source, target, rollback_manifest_path=rollback)

    result = apply_migration_plan(plan, dry_run=True)

    assert result.dry_run is True
    assert result.would_copy == (target.resolve() / "asset.bin",)
    assert result.copied == ()
    assert not target.exists()
    assert not rollback.exists()


def test_apply_copies_verifies_and_writes_rollback_manifest(tmp_path):
    source = tmp_path / "legacy"
    target = tmp_path / "product"
    source.mkdir()
    payload = b"final-video-bytes"
    (source / "final.mp4").write_bytes(payload)
    rollback = tmp_path / "rollback.json"
    plan = plan_migration(source, target, rollback_manifest_path=rollback)

    result = apply_migration_plan(plan)

    copied = target / "final.mp4"
    assert result.copied == (copied.resolve(),)
    assert copied.read_bytes() == payload
    assert (source / "final.mp4").read_bytes() == payload
    rollback_payload = json.loads(rollback.read_text(encoding="utf-8"))
    assert rollback_payload["version"] == 1
    assert rollback_payload["created"] == [
        {
            "path": str(copied.resolve()),
            "size": len(payload),
            "sha256": _sha256(payload),
        }
    ]


def test_reapplying_same_plan_is_idempotent_and_preserves_rollback_manifest(tmp_path):
    source = tmp_path / "legacy"
    target = tmp_path / "product"
    source.mkdir()
    (source / "asset.bin").write_bytes(b"asset")
    rollback = tmp_path / "rollback.json"
    plan = plan_migration(source, target, rollback_manifest_path=rollback)
    first = apply_migration_plan(plan)
    manifest_before = rollback.read_bytes()

    second = apply_migration_plan(plan)

    assert first.copied == (target.resolve() / "asset.bin",)
    assert second.copied == ()
    assert second.skipped == (target.resolve() / "asset.bin",)
    assert rollback.read_bytes() == manifest_before
    assert (source / "asset.bin").read_bytes() == b"asset"


def test_apply_rechecks_collision_if_destination_changes_after_planning(tmp_path):
    source = tmp_path / "legacy"
    target = tmp_path / "product"
    source.mkdir()
    (source / "asset.bin").write_bytes(b"source")
    plan = plan_migration(source, target)
    target.mkdir()
    (target / "asset.bin").write_bytes(b"raced")

    with pytest.raises(MigrationCollisionError, match="asset.bin"):
        apply_migration_plan(plan)

    assert (target / "asset.bin").read_bytes() == b"raced"
    assert (source / "asset.bin").read_bytes() == b"source"


def test_apply_rejects_a_copy_that_fails_post_copy_hash_verification(tmp_path, monkeypatch):
    source = tmp_path / "legacy"
    target = tmp_path / "product"
    source.mkdir()
    (source / "asset.bin").write_bytes(b"source")
    plan = plan_migration(source, target)

    def corrupt_copy(_source, destination):
        destination.write_bytes(b"corrupt")

    monkeypatch.setattr(migration.shutil, "copy2", corrupt_copy)

    with pytest.raises(MigrationIntegrityError, match="post-copy hash"):
        apply_migration_plan(plan)

    assert (source / "asset.bin").read_bytes() == b"source"


def test_product_asset_dedup_dry_run_is_read_only_and_reports_only_cross_production_duplicates(tmp_path):
    product = tmp_path / "not_a_trolley_problem"
    (product / "product.toml").parent.mkdir(parents=True)
    (product / "product.toml").write_text('id = "not_a_trolley_problem"\n', encoding="utf-8")
    first = product / "devlogs" / "2026_07_17_devlog_01" / "data" / "images"
    second = product / "reels" / "2026_07_18_reel_01" / "data" / "footage"
    first.mkdir(parents=True)
    second.mkdir(parents=True)
    (first / "same.png").write_bytes(b"shared-real-product")
    (second / "same.png").write_bytes(b"shared-real-product")
    (first / "only-here.png").write_bytes(b"unique")

    result = deduplicate_product_assets(product, dry_run=True)

    assert len(result.canonical_files) == 1
    assert set(result.relinked) == {
        (first / "same.png").resolve(),
        (second / "same.png").resolve(),
    }
    assert not result.canonical_files[0].exists()
    assert not result.report_path.exists()
    assert (first / "same.png").read_bytes() == b"shared-real-product"


def test_product_asset_dedup_keeps_paths_and_hashes_but_uses_one_physical_file(tmp_path):
    product = tmp_path / "not_a_trolley_problem"
    product.mkdir()
    (product / "product.toml").write_text('id = "not_a_trolley_problem"\n', encoding="utf-8")
    first = product / "devlogs" / "2026_07_17_devlog_01" / "data" / "music" / "track.ogg"
    second = product / "reels" / "2026_07_18_reel_01" / "data" / "music" / "track.ogg"
    first.parent.mkdir(parents=True)
    second.parent.mkdir(parents=True)
    payload = b"licensed-track-bytes"
    first.write_bytes(payload)
    second.write_bytes(payload)
    before_hash = _sha256(payload)

    result = deduplicate_product_assets(product, dry_run=False)

    assert first.read_bytes() == payload
    assert second.read_bytes() == payload
    assert _sha256(first.read_bytes()) == before_hash
    assert len(result.canonical_files) == 1
    canonical = result.canonical_files[0]
    assert canonical.read_bytes() == payload
    assert first.samefile(canonical)
    assert second.samefile(canonical)
    report = json.loads(result.report_path.read_text(encoding="utf-8"))
    assert report["physical_storage"] == "hardlink"
    assert report["groups"][0]["sha256"] == before_hash
    assert set(report["groups"][0]["aliases"]) == {str(first.resolve()), str(second.resolve())}

    second_result = deduplicate_product_assets(product, dry_run=False)
    assert second_result.relinked == ()
    assert set(second_result.skipped) == {first.resolve(), second.resolve()}
