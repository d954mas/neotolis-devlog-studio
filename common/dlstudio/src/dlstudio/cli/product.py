"""Product-first scaffolding commands from PLAN_STUDIO_AUTOPILOT_60 section 10.

The commands are deliberately additive: they create new product/production
trees and refuse to replace anything that already exists.
"""
from __future__ import annotations

import argparse
import importlib
import json
import re
from datetime import date as calendar_date
from pathlib import Path

from dlstudio.cli.newvideo import FORMAT_RESOLUTIONS, rewrite_resolution

TEMPLATE_FILES: tuple[str, ...] = ("__init__.py", "beats.py", "design.py")

SHARED_ASSET_SUBDIRS: tuple[str, ...] = (
    "gameplay",
    "steam",
    "diary",
    "canvas",
    "fonts",
    "music",
    "sfx",
)

PRODUCTION_DATA_SUBDIRS: tuple[str, ...] = (
    "audio",
    "recordings",
    "scratch",
    "footage",
    "images",
    "hyperframes",
    "infographics",
    "plan",
    "review",
    "finalize",
    "publish",
)

_COLLECTION_FOR_KIND = {"devlog": "devlogs", "reel": "reels"}
_DEFAULT_ORIENTATION = {"devlog": "landscape", "reel": "vertical"}
_TITLE_SMALL_WORDS = {"a", "an", "and", "at", "by", "for", "in", "of", "on", "or", "the", "to"}


def _toml_string(value: str) -> str:
    """Encode a TOML basic string using JSON's compatible string syntax."""
    return json.dumps(value, ensure_ascii=False)


def _default_title(product_id: str) -> str:
    words = product_id.split("_")
    return " ".join(
        word.lower() if index and word.lower() in _TITLE_SMALL_WORDS else word.capitalize()
        for index, word in enumerate(words)
    )


def _workspace_root() -> Path:
    # Lazy import avoids relying on cli.__init__ having finished initialization.
    from dlstudio.cli import CliError, _find_workspace_root

    root = _find_workspace_root()
    if root is None:
        raise CliError(
            "no workspace root found (no devlog.toml or .git upward from cwd) "
            "-- run inside the devlogs workspace"
        )
    return root


def _product_root(product_id: str) -> Path:
    from dlstudio.cli import CliError

    if not product_id.isidentifier():
        raise CliError(f"product {product_id!r} must be a valid identifier")
    return _workspace_root() / product_id


def _template_sources(orientation: str | None = None) -> dict[str, str]:
    template_dir = Path(importlib.import_module("dlstudio.template").__file__).parent
    sources = {
        name: (template_dir / name).read_text(encoding="utf-8")
        for name in TEMPLATE_FILES
    }
    if orientation is not None:
        sources["design.py"] = rewrite_resolution(
            sources["design.py"], FORMAT_RESOLUTIONS[orientation]
        )
    return sources


def _product_manifest_text(product_id: str, title: str, game_root: str) -> str:
    return "\n".join(
        (
            f"id = {_toml_string(product_id)}",
            f"title = {_toml_string(title)}",
            f"game_root = {_toml_string(game_root)}",
            "",
            "[sources]",
            "",
        )
    )


def cmd_new_product(args: argparse.Namespace) -> int:
    from dlstudio.cli import CliError

    root = _product_root(args.product)
    if root.exists():
        raise CliError(f"product path already exists: {root}")

    title = args.title.strip() if args.title is not None else _default_title(args.product)
    if not title:
        raise CliError("--title must be non-empty")
    game_root = args.game_root.strip()
    if not game_root:
        raise CliError("--game-root must be non-empty")

    try:
        root.mkdir()
    except FileExistsError as exc:
        raise CliError(f"product path already exists: {root}") from exc

    (root / "product.toml").write_text(
        _product_manifest_text(args.product, title, game_root), encoding="utf-8"
    )
    (root / "shared").mkdir()
    (root / "shared" / "preferences.toml").write_text("", encoding="utf-8")
    for subdir in SHARED_ASSET_SUBDIRS:
        (root / "shared" / "assets" / subdir).mkdir(parents=True)
    for collection in _COLLECTION_FOR_KIND.values():
        (root / collection).mkdir()
        (root / "delivery" / collection).mkdir(parents=True)

    print(f"[dl2] created product {args.product}: {root}")
    print(f"[dl2] next: dl2 new-production {args.product} --kind devlog")
    return 0


def _parse_date(value: str) -> calendar_date:
    from dlstudio.cli import CliError

    try:
        parsed = calendar_date.fromisoformat(value)
    except ValueError as exc:
        raise CliError(f"date {value!r} must use YYYY-MM-DD") from exc
    if parsed.isoformat() != value:
        raise CliError(f"date {value!r} must use YYYY-MM-DD")
    return parsed


def _load_product(product_id: str):
    from dlstudio.cli import CliError
    from dlstudio.production import ProductionError, load_product_manifest

    root = _product_root(product_id)
    try:
        return load_product_manifest(root)
    except ProductionError as exc:
        raise CliError(str(exc)) from exc


def _next_production_id(collection_dir: Path, day: calendar_date, kind: str) -> str:
    from dlstudio.cli import CliError

    prefix = f"{day.strftime('%Y_%m_%d')}_{kind}_"
    pattern = re.compile(rf"^{re.escape(prefix)}(?P<number>\d{{2}})$")
    numbers = [
        int(match.group("number"))
        for child in collection_dir.iterdir()
        if child.is_dir() and (match := pattern.fullmatch(child.name)) is not None
    ]
    number = max(numbers, default=0) + 1
    if number > 99:
        raise CliError(f"no production id available for {day.isoformat()} {kind}")
    return f"{prefix}{number:02d}"


def _production_manifest_text(
    production_id: str,
    kind: str,
    day: calendar_date,
    orientation: str,
    collection: str,
) -> str:
    return "\n".join(
        (
            f"id = {_toml_string(production_id)}",
            f"kind = {_toml_string(kind)}",
            f"date = {_toml_string(day.isoformat())}",
            f"orientation = {_toml_string(orientation)}",
            'edit_path = "edit"',
            'data_root = "data"',
            f'delivery_root = "../../delivery/{collection}/{production_id}"',
            "",
        )
    )


def cmd_new_production(args: argparse.Namespace) -> int:
    from dlstudio.cli import CliError

    product_manifest = _load_product(args.product)
    day = _parse_date(args.date)
    collection = _COLLECTION_FOR_KIND[args.kind]
    orientation = args.orientation or _DEFAULT_ORIENTATION[args.kind]
    sources = _template_sources(orientation)

    collection_dir = getattr(product_manifest, f"{collection}_dir")
    production_id = _next_production_id(collection_dir, day, args.kind)
    root = collection_dir / production_id
    try:
        root.mkdir()
    except FileExistsError as exc:
        raise CliError(f"production path already exists: {root}") from exc

    (root / "production.toml").write_text(
        _production_manifest_text(
            production_id, args.kind, day, orientation, collection
        ),
        encoding="utf-8",
    )
    edit_dir = root / "edit"
    edit_dir.mkdir()
    for name, source in sources.items():
        (edit_dir / name).write_text(source, encoding="utf-8")
    for subdir in PRODUCTION_DATA_SUBDIRS:
        (root / "data" / subdir).mkdir(parents=True)
    if args.kind == "reel":
        story_contract = {
            "version": 1,
            "standalone_story": {
                "premise": "",
                "causal_turn": "",
                "payoff": "",
            },
            "allow_editorial_labels": [],
        }
        (root / "data" / "plan" / "story_contract.json").write_text(
            json.dumps(story_contract, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )

    print(f"[dl2] created production {args.product}:{production_id}")
    print(f"[dl2] path: {root}")
    return 0


def cmd_list_productions(args: argparse.Namespace) -> int:
    from dlstudio.cli import CliError
    from dlstudio.production import ProductionError, load_production_manifest

    product_manifest = _load_product(args.product)
    manifests = []
    try:
        for collection_dir in (
            product_manifest.devlogs_dir,
            product_manifest.reels_dir,
        ):
            for path in collection_dir.glob("*/production.toml"):
                manifests.append(load_production_manifest(path))
    except ProductionError as exc:
        raise CliError(str(exc)) from exc

    for manifest in sorted(manifests, key=lambda item: item.id):
        print(
            f"{manifest.id}\t{manifest.kind}\t{manifest.date}\t"
            f"{manifest.orientation}"
        )
    return 0


def cmd_dedupe_assets(args: argparse.Namespace) -> int:
    """Plan or apply exact-hash shared-asset hardlinking for one product."""
    from dlstudio.services.migration import deduplicate_product_assets

    product_manifest = _load_product(args.product)
    result = deduplicate_product_assets(
        product_manifest.root,
        dry_run=not args.apply,
        report_path=args.report,
    )
    mode = "applied" if args.apply else "dry-run"
    print(
        f"[dl2] dedupe-assets {mode}: {len(result.canonical_files)} groups, "
        f"{len(result.relinked)} relinked, {len(result.skipped)} unchanged"
    )
    print(f"[dl2] report: {result.report_path}")
    return 0


def add_subparsers(sub: argparse._SubParsersAction) -> None:
    new_product = sub.add_parser(
        "new-product", help="create a product-first Studio workspace"
    )
    new_product.add_argument("product", help="product id created under the workspace")
    new_product.add_argument(
        "--title", help="display title (default: product id humanized)"
    )
    new_product.add_argument(
        "--game-root",
        default=".",
        help="game source root stored in product.toml (default: product root)",
    )
    new_product.set_defaults(func=cmd_new_product)

    new_production = sub.add_parser(
        "new-production", help="create a dated production inside a product"
    )
    new_production.add_argument("product", help="existing product id")
    new_production.add_argument("--kind", required=True, choices=sorted(_COLLECTION_FOR_KIND))
    new_production.add_argument(
        "--date",
        default=calendar_date.today().isoformat(),
        help="production date as YYYY-MM-DD (default: today)",
    )
    new_production.add_argument(
        "--orientation",
        choices=sorted(FORMAT_RESOLUTIONS),
        help="default: landscape for devlog, vertical for reel",
    )
    new_production.set_defaults(func=cmd_new_production)

    list_productions = sub.add_parser(
        "list-productions", help="list product productions in id order"
    )
    list_productions.add_argument("product", help="existing product id")
    list_productions.set_defaults(func=cmd_list_productions)

    dedupe_assets = sub.add_parser(
        "dedupe-assets",
        help="deduplicate exact shared assets while preserving production paths",
    )
    dedupe_assets.add_argument("product", help="existing product id")
    dedupe_assets.add_argument(
        "--apply",
        action="store_true",
        help="create verified shared hardlinks (default: read-only dry run)",
    )
    dedupe_assets.add_argument(
        "--report",
        help="dedup report path (default: shared/migration/dedup_report.json)",
    )
    dedupe_assets.set_defaults(func=cmd_dedupe_assets)
