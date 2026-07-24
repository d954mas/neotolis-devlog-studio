from __future__ import annotations

import argparse
from pathlib import Path

import pytest

from dlstudio import cli


def _parse(argv: list[str]) -> argparse.Namespace:
    return cli._build_parser().parse_args(argv)


def _workspace(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "devlog.toml").write_text("", encoding="utf-8")
    monkeypatch.chdir(tmp_path)
    product = tmp_path / "not_a_trolley_problem"
    product.mkdir()
    (product / "product.toml").write_text(
        '\n'.join((
            'id = "not_a_trolley_problem"',
            'title = "Not a Trolley Problem"',
            'game_root = "."',
            '',
            '[sources]',
            '',
        )),
        encoding="utf-8",
    )
    for name in ("devlogs", "reels", "shared/migration", "delivery"):
        (product / name).mkdir(parents=True, exist_ok=True)
    return product


def test_parser_exposes_safe_migrate_product_modes():
    args = _parse([
        "migrate-product",
        "--to", "not_a_trolley_problem",
        "--from", "trolley_devlog",
        "--from", "trolley3d",
        "--dry-run",
    ])

    assert args.to_product == "not_a_trolley_problem"
    assert args.sources == ["trolley_devlog", "trolley3d"]
    assert args.dry_run is True
    assert args.apply is False


def test_migrate_product_uses_product_default_plan_and_is_read_only_by_default(
    tmp_path, monkeypatch, capsys
):
    product = _workspace(tmp_path, monkeypatch)
    source = tmp_path / "trolley_devlog"
    source.mkdir()
    payload = source / "asset.bin"
    payload.write_bytes(b"asset")
    destination = product / "devlogs" / "2026_07_17_devlog_01" / "data" / "asset.bin"

    from dlstudio.services.migration import MigrationFile, MigrationPlan

    plan = MigrationPlan.from_files(
        [MigrationFile.from_paths(payload, destination)],
        rollback_manifest_path=product / "shared" / "migration" / "rollback.json",
    )
    plan.write(product / "shared" / "migration" / "plan.json")

    args = _parse([
        "migrate-product",
        "--to", "not_a_trolley_problem",
        "--from", "trolley_devlog",
        "--dry-run",
    ])
    assert args.func(args) == 0

    assert not destination.exists()
    assert "would copy: 1" in capsys.readouterr().out


def test_migrate_product_apply_is_idempotent_and_preserves_source(
    tmp_path, monkeypatch, capsys
):
    product = _workspace(tmp_path, monkeypatch)
    source = tmp_path / "trolley3d"
    source.mkdir()
    payload = source / "final.mp4"
    payload.write_bytes(b"exact-final")
    destination = product / "delivery" / "reels" / "2026_07_17_reel_01" / "video.mp4"

    from dlstudio.services.migration import MigrationFile, MigrationPlan

    plan_path = product / "shared" / "migration" / "plan.json"
    MigrationPlan.from_files(
        [MigrationFile.from_paths(payload, destination)],
        rollback_manifest_path=product / "shared" / "migration" / "rollback.json",
    ).write(plan_path)

    args = _parse([
        "migrate-product",
        "--plan", str(plan_path),
        "--to", "not_a_trolley_problem",
        "--from", str(source),
        "--apply",
    ])
    assert args.func(args) == 0
    assert destination.read_bytes() == b"exact-final"
    assert payload.read_bytes() == b"exact-final"
    capsys.readouterr()

    assert args.func(args) == 0
    assert "copied: 0" in capsys.readouterr().out


def test_migrate_product_explicit_plan_can_infer_destination_product(
    tmp_path, monkeypatch
):
    product = _workspace(tmp_path, monkeypatch)
    source = tmp_path / "legacy" / "asset.bin"
    source.parent.mkdir()
    source.write_bytes(b"asset")
    destination = product / "shared" / "assets" / "asset.bin"

    from dlstudio.services.migration import MigrationFile, MigrationPlan

    plan_path = tmp_path / "explicit-plan.json"
    MigrationPlan.from_files(
        [MigrationFile.from_paths(source, destination)],
        rollback_manifest_path=product / "shared" / "migration" / "rollback.json",
    ).write(plan_path)

    args = _parse(["migrate-product", "--plan", str(plan_path), "--apply"])
    assert args.func(args) == 0
    assert destination.read_bytes() == b"asset"


def test_migrate_product_rejects_plan_paths_outside_declared_scopes(
    tmp_path, monkeypatch
):
    product = _workspace(tmp_path, monkeypatch)
    declared = tmp_path / "trolley_devlog"
    undeclared = tmp_path / "other_project"
    declared.mkdir()
    undeclared.mkdir()
    source_file = undeclared / "secret.bin"
    source_file.write_bytes(b"not-declared")
    destination = product / "devlogs" / "2026_07_17_devlog_01" / "data" / "secret.bin"

    from dlstudio.services.migration import MigrationFile, MigrationPlan

    plan_path = product / "shared" / "migration" / "plan.json"
    MigrationPlan.from_files(
        [MigrationFile.from_paths(source_file, destination)],
        rollback_manifest_path=product / "shared" / "migration" / "rollback.json",
    ).write(plan_path)

    args = _parse([
        "migrate-product",
        "--plan", str(plan_path),
        "--to", "not_a_trolley_problem",
        "--from", str(declared),
        "--dry-run",
    ])
    with pytest.raises(cli.CliError, match="outside declared --from roots"):
        args.func(args)


def test_migrate_product_requires_exactly_one_execution_mode():
    with pytest.raises(SystemExit):
        _parse(["migrate-product", "--plan", "plan.json", "--apply", "--dry-run"])
