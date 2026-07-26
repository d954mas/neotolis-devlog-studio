"""Safe, plan-driven product migration CLI.

``migrate-product`` never guesses a mapping and never deletes a legacy file.
It executes a reviewed JSON plan produced by ``services.migration`` and treats
``--to``/``--from`` as path-scope assertions around that plan.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def _workspace_root() -> Path:
    from dlstudio.cli import CliError, _find_workspace_root

    root = _find_workspace_root()
    if root is None:
        raise CliError(
            "no workspace root found (no devlog.toml or .git upward from cwd)"
        )
    return root.resolve()


def _resolve_path(raw: str | Path, workspace: Path) -> Path:
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (workspace / path).resolve()


def _inside(path: Path, root: Path) -> bool:
    try:
        path.resolve().relative_to(root.resolve())
    except ValueError:
        return False
    return True


def _product_root_for_destinations(destinations: tuple[Path, ...]) -> Path:
    from dlstudio.cli import CliError

    roots: set[Path] = set()
    for destination in destinations:
        root = next(
            (
                candidate
                for candidate in (destination.parent, *destination.parents)
                if (candidate / "product.toml").is_file()
            ),
            None,
        )
        if root is None:
            raise CliError(
                "cannot infer --to product from migration destination: "
                f"{destination}"
            )
        roots.add(root.resolve())
    if len(roots) != 1:
        raise CliError("migration plan destinations span multiple products")
    return next(iter(roots))


def cmd_migrate_product(args: argparse.Namespace) -> int:
    from dlstudio.cli import CliError
    from dlstudio.production import ProductionError, load_product_manifest
    from dlstudio.services.migration import (
        MigrationError,
        apply_migration_plan,
        load_migration_plan,
    )

    workspace = _workspace_root()
    if not args.plan and not args.to_product:
        raise CliError("--to is required when --plan is omitted")
    initial_plan_path = (
        _resolve_path(args.plan, workspace)
        if args.plan
        else _resolve_path(args.to_product, workspace)
        / "shared"
        / "migration"
        / "plan.json"
    )
    try:
        plan = load_migration_plan(initial_plan_path)
    except MigrationError as exc:
        raise CliError(str(exc)) from exc

    product_root = (
        _resolve_path(args.to_product, workspace)
        if args.to_product
        else _product_root_for_destinations(
            tuple(entry.destination for entry in plan.files)
        )
    )
    try:
        product = load_product_manifest(product_root)
    except ProductionError as exc:
        raise CliError(str(exc)) from exc
    if (
        args.to_product
        and product.id != args.to_product
        and Path(args.to_product).name != product.id
    ):
        raise CliError(
            f"--to {args.to_product!r} resolves to product {product.id!r}"
        )

    plan_path = initial_plan_path
    source_roots = tuple(_resolve_path(raw, workspace) for raw in args.sources)
    missing_roots = [root for root in source_roots if not root.is_dir()]
    if missing_roots:
        raise CliError(f"declared --from root does not exist: {missing_roots[0]}")

    try:
        for entry in plan.files:
            if source_roots and not any(
                _inside(entry.source, root) for root in source_roots
            ):
                raise CliError(
                    "migration source is outside declared --from roots: "
                    f"{entry.source}"
                )
            if not _inside(entry.destination, product.root):
                raise CliError(
                    f"migration destination escapes product {product.id}: "
                    f"{entry.destination}"
                )
        rollback_root = (product.shared_dir / "migration").resolve()
        if not _inside(plan.rollback_manifest_path, rollback_root):
            raise CliError(
                "rollback manifest must stay inside product shared/migration: "
                f"{plan.rollback_manifest_path}"
            )
        result = apply_migration_plan(plan, dry_run=args.dry_run)
    except MigrationError as exc:
        raise CliError(str(exc)) from exc

    mode = "dry-run" if result.dry_run else "applied"
    print(f"[dl2] migrate-product {mode}: {product.id}")
    print(f"[dl2] plan: {plan_path}")
    print(f"[dl2] would copy: {len(result.would_copy)}")
    print(f"[dl2] copied: {len(result.copied)}")
    print(f"[dl2] unchanged: {len(result.skipped)}")
    print(f"[dl2] rollback: {result.rollback_manifest_path}")
    return 0


def add_subparser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "migrate-product",
        help="validate and execute a non-destructive product migration plan",
    )
    parser.add_argument(
        "--to",
        dest="to_product",
        help="destination product id or product path",
    )
    parser.add_argument(
        "--from",
        dest="sources",
        action="append",
        default=[],
        help="allowed legacy source root (repeatable)",
    )
    parser.add_argument(
        "--plan",
        help="plan JSON (default: <product>/shared/migration/plan.json)",
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="verify hashes, collisions, and scopes without writing",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="copy verified files and write an idempotent rollback manifest",
    )
    parser.set_defaults(func=cmd_migrate_product)


__all__ = ["add_subparser", "cmd_migrate_product"]
