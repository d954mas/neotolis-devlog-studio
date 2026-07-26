from __future__ import annotations

from pathlib import Path

import pytest

from tools.studio_v3_migrate.budget import build_disk_budget
from tools.studio_v3_migrate.inventory import DispositionRules, build_before_manifest
from tools.studio_v3_migrate.recovery import (
    RecoveryError,
    create_verified_backup,
    rehearse_restore,
    verify_tree_against_manifest,
)


def _fixture(tmp_path: Path) -> tuple[Path, dict]:
    workspace = tmp_path / "workspace"
    project = workspace / "video_product"
    (project / "data" / "recordings").mkdir(parents=True)
    (project / "product.toml").write_text("[product]\nid='video'\n", encoding="utf-8")
    (project / "data" / "recordings" / "raw.wav").write_bytes(b"irreplaceable-raw")
    manifest = build_before_manifest(workspace, DispositionRules.load_default())
    return workspace, manifest


def test_verified_backup_and_restore_rehearsal_match_manifest(tmp_path: Path) -> None:
    workspace, manifest = _fixture(tmp_path)
    backup = tmp_path / "backup"
    restored = tmp_path / "restored"

    backup_report = create_verified_backup(workspace, backup, manifest)
    restore_report = rehearse_restore(backup, restored, manifest)

    assert backup_report["verified"] is True
    assert restore_report["verified"] is True
    assert verify_tree_against_manifest(restored, manifest)["verified"] is True
    assert (restored / "video_product/data/recordings/raw.wav").read_bytes() == (
        b"irreplaceable-raw"
    )


def test_backup_refuses_nonempty_destination(tmp_path: Path) -> None:
    workspace, manifest = _fixture(tmp_path)
    backup = tmp_path / "backup"
    backup.mkdir()
    (backup / "existing.txt").write_text("do not overwrite", encoding="utf-8")

    with pytest.raises(RecoveryError, match="empty"):
        create_verified_backup(workspace, backup, manifest)


def test_backup_detects_source_changed_after_manifest(tmp_path: Path) -> None:
    workspace, manifest = _fixture(tmp_path)
    recording = workspace / "video_product/data/recordings/raw.wav"
    recording.write_bytes(b"changed-after-manifest")

    with pytest.raises(RecoveryError, match="source changed"):
        create_verified_backup(workspace, tmp_path / "backup", manifest)


def test_restore_rehearsal_never_overwrites_destination(tmp_path: Path) -> None:
    workspace, manifest = _fixture(tmp_path)
    backup = tmp_path / "backup"
    create_verified_backup(workspace, backup, manifest)
    restored = tmp_path / "restored"
    restored.mkdir()
    (restored / "user-file.txt").write_text("keep", encoding="utf-8")

    with pytest.raises(RecoveryError, match="empty"):
        rehearse_restore(backup, restored, manifest)


def test_disk_budget_never_counts_hardlinks_as_backup(tmp_path: Path) -> None:
    workspace, manifest = _fixture(tmp_path)

    report = build_disk_budget(
        workspace,
        manifest,
        tmp_path / "backup",
        tmp_path / "clone",
    )

    total = manifest["summary"]["bytes"]
    assert report["verified_backup_copy_bytes"] == total
    assert report["restore_rehearsal_copy_bytes"] == total
    assert report["required_additional_peak_bytes"] >= total * 2
    assert report["hardlinks_are_backup"] is False
