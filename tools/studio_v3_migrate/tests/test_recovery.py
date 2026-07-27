from __future__ import annotations

from pathlib import Path

import pytest
import tools.studio_v3_migrate.recovery as recovery

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


def test_backup_copies_verified_bytes_without_filesystem_metadata(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, manifest = _fixture(tmp_path)
    monkeypatch.setattr(
        recovery.shutil,
        "copy2",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(
            AssertionError("metadata copy is outside the recovery contract")
        ),
    )

    report = create_verified_backup(workspace, tmp_path / "backup", manifest)

    assert report["verified"] is True


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

    with pytest.raises(RecoveryError, match="differs"):
        rehearse_restore(backup, restored, manifest)


def test_disk_budget_never_counts_hardlinks_as_backup(tmp_path: Path) -> None:
    workspace, manifest = _fixture(tmp_path)

    report = build_disk_budget(
        workspace,
        manifest,
        tmp_path / "backup",
        tmp_path / "restore",
        tmp_path / "clone",
    )

    total = manifest["summary"]["bytes"]
    assert report["verified_backup_copy_bytes"] == total
    assert report["restore_rehearsal_copy_bytes"] == total
    assert report["required_additional_peak_bytes"] >= total * 2
    assert report["hardlinks_are_backup"] is False


def test_interrupted_backup_resumes_from_staging(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, manifest = _fixture(tmp_path)
    backup = tmp_path / "backup"
    original = recovery._copy_entry
    calls = 0

    def fail_second(source: Path, destination: Path, kind: str) -> None:
        nonlocal calls
        calls += 1
        if calls == 2:
            raise OSError("injected copy failure")
        original(source, destination, kind)

    monkeypatch.setattr(recovery, "_copy_entry", fail_second)
    with pytest.raises(OSError, match="injected"):
        create_verified_backup(workspace, backup, manifest)
    assert not backup.exists()

    monkeypatch.setattr(recovery, "_copy_entry", original)
    report = create_verified_backup(workspace, backup, manifest)
    assert report["verified"] is True
    assert report["resumed_entries"] == 1


def test_verified_existing_backup_is_idempotent(tmp_path: Path) -> None:
    workspace, manifest = _fixture(tmp_path)
    backup = tmp_path / "backup"
    first = create_verified_backup(workspace, backup, manifest)
    second = create_verified_backup(workspace, backup, manifest)
    assert first["verified"] is True
    assert second["verified"] is True
    assert second["resumed_entries"] == len(manifest["entries"])


def test_existing_backup_does_not_hide_source_drift(tmp_path: Path) -> None:
    workspace, manifest = _fixture(tmp_path)
    backup = tmp_path / "backup"
    create_verified_backup(workspace, backup, manifest)
    (workspace / "video_product/data/recordings/raw.wav").write_bytes(b"changed")

    with pytest.raises(RecoveryError, match="source changed"):
        create_verified_backup(workspace, backup, manifest)


def test_backup_rejects_symlinked_staging_root(tmp_path: Path) -> None:
    workspace, manifest = _fixture(tmp_path)
    backup = tmp_path / "backup"
    digest = recovery._manifest_digest(manifest)
    staging = backup.with_name(f".{backup.name}.{digest[:16]}.staging")
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        staging.symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(RecoveryError, match="staging path"):
        create_verified_backup(workspace, backup, manifest)
    assert list(outside.iterdir()) == []


def test_backup_rejects_symlinked_staging_parent(tmp_path: Path) -> None:
    workspace, manifest = _fixture(tmp_path)
    backup = tmp_path / "backup"
    digest = recovery._manifest_digest(manifest)
    staging = backup.with_name(f".{backup.name}.{digest[:16]}.staging")
    staging.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    try:
        (staging / "video_product").symlink_to(outside, target_is_directory=True)
    except OSError as exc:
        pytest.skip(f"directory symlinks unavailable: {exc}")

    with pytest.raises(RecoveryError, match="unsafe staging"):
        create_verified_backup(workspace, backup, manifest)
    assert list(outside.iterdir()) == []


def test_budget_checks_each_destination_volume(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    workspace, manifest = _fixture(tmp_path)

    def volume(path: Path) -> str:
        name = path.name
        if name == "workspace":
            return "source"
        if name == "backup":
            return "backup-volume"
        return "full-volume"

    monkeypatch.setattr(
        "tools.studio_v3_migrate.budget._volume_identity", volume
    )
    monkeypatch.setattr(
        "tools.studio_v3_migrate.budget._free_bytes",
        lambda path: 10**9 if path.name == "backup" else 0,
    )
    report = build_disk_budget(
        workspace,
        manifest,
        tmp_path / "backup",
        tmp_path / "restore",
        tmp_path / "clone",
    )
    assert report["sufficient"] is False
    assert any(
        item["id"] == "full-volume" and not item["sufficient"]
        for item in report["volumes"]
    )
