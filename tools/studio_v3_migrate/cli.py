from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from .budget import build_disk_budget
from .asset_translation import AssetTranslationError, translate_asset_schemas
from .inventory import (
    DispositionRules,
    InventoryError,
    build_before_manifest,
    load_manifest,
    project_roots_report,
)
from .recovery import (
    RecoveryError,
    create_verified_backup,
    rehearse_restore,
    verify_tree_against_manifest,
)


def _write_json(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    temporary.replace(path)


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="studio-v3-migrate",
        description="Offline, fail-closed Studio v3 inventory/recovery harness.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    roots = subparsers.add_parser("roots")
    roots.add_argument("--workspace", type=Path, required=True)
    roots.add_argument("--rules", type=Path)
    roots.add_argument("--report", type=Path, required=True)

    for command in ("inventory", "dry-run"):
        inventory = subparsers.add_parser(command)
        inventory.add_argument("--workspace", type=Path, required=True)
        inventory.add_argument("--rules", type=Path)
        inventory.add_argument("--manifest", type=Path, required=True)
        inventory.add_argument("--budget", type=Path)
        inventory.add_argument("--backup-destination", type=Path)
        inventory.add_argument("--restore-destination", type=Path)
        inventory.add_argument("--clone-destination", type=Path)

    backup = subparsers.add_parser("backup")
    backup.add_argument("--workspace", type=Path, required=True)
    backup.add_argument("--manifest", type=Path, required=True)
    backup.add_argument("--destination", type=Path, required=True)
    backup.add_argument("--report", type=Path, required=True)

    verify = subparsers.add_parser("verify-backup")
    verify.add_argument("--manifest", type=Path, required=True)
    verify.add_argument("--backup", type=Path, required=True)

    restore = subparsers.add_parser("restore-rehearsal")
    restore.add_argument("--manifest", type=Path, required=True)
    restore.add_argument("--backup", type=Path, required=True)
    restore.add_argument("--destination", type=Path, required=True)
    restore.add_argument("--report", type=Path, required=True)

    assets = subparsers.add_parser("translate-assets")
    assets.add_argument("--production", type=Path, required=True)
    assets.add_argument("--report", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "translate-assets":
            report = translate_asset_schemas(args.production)
            _write_json(args.report, report)
            print(json.dumps(report["summary"], sort_keys=True))
            return 0
        if args.command in {"roots", "inventory", "dry-run"}:
            rules = (
                DispositionRules.load(args.rules)
                if args.rules
                else DispositionRules.load_default()
            )
            if args.command == "roots":
                report = project_roots_report(args.workspace, rules)
                _write_json(args.report, report)
                print(json.dumps(report["summary"], sort_keys=True))
                return 0
            manifest = build_before_manifest(args.workspace, rules)
            _write_json(args.manifest, manifest)
            if args.budget:
                if not args.backup_destination:
                    raise InventoryError("--budget requires --backup-destination")
                if not args.restore_destination:
                    raise InventoryError("--budget requires --restore-destination")
                if not args.clone_destination:
                    raise InventoryError("--budget requires --clone-destination")
                budget = build_disk_budget(
                    args.workspace,
                    manifest,
                    args.backup_destination,
                    args.restore_destination,
                    args.clone_destination,
                )
                _write_json(args.budget, budget)
            print(json.dumps(manifest["summary"], sort_keys=True))
            return 0
        manifest = load_manifest(args.manifest)
        if args.command == "backup":
            report = create_verified_backup(args.workspace, args.destination, manifest)
            _write_json(args.report, report)
        elif args.command == "verify-backup":
            report = verify_tree_against_manifest(args.backup, manifest)
            print(json.dumps(report, sort_keys=True))
            return 0 if report["verified"] else 2
        elif args.command == "restore-rehearsal":
            report = rehearse_restore(args.backup, args.destination, manifest)
            _write_json(args.report, report)
        else:  # pragma: no cover - argparse enforces commands.
            raise AssertionError(args.command)
        print(json.dumps(report, sort_keys=True))
        return 0
    except (
        AssetTranslationError,
        InventoryError,
        RecoveryError,
        OSError,
    ) as exc:
        print(f"BLOCKED: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
