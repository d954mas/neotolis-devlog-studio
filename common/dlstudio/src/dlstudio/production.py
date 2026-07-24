"""Filesystem production manifests and path-based edit loading.

The legacy Studio address is an importable dotted module.  Product work needs
human-readable date folders such as ``2026_07_18_reel_01`` without forcing the
folder tree to be a Python package.  This module keeps both worlds: it validates
the small TOML contracts and imports only the production's ``edit/`` package
under a deterministic private module name.
"""
from __future__ import annotations

import hashlib
import importlib
import importlib.util
import re
import sys
import threading
import tomllib
from dataclasses import dataclass
from datetime import date as calendar_date
from pathlib import Path
from types import ModuleType


class ProductionError(ValueError):
    """A product/production manifest or filesystem reference is invalid."""


_PRODUCTION_ID_RE = re.compile(
    r"^(?P<date>\d{4}_\d{2}_\d{2})_(?P<kind>devlog|reel)_(?P<number>\d{2})$"
)
_IMPORT_LOCK = threading.RLock()


def _mapping(value: object, label: str) -> dict:
    if not isinstance(value, dict):
        raise ProductionError(f"{label} must be a TOML table")
    return value


def _relative_child(root: Path, value: object, label: str) -> Path:
    if not isinstance(value, str) or not value.strip():
        raise ProductionError(f"{label} must be a non-empty relative path")
    rel = Path(value)
    if rel.is_absolute() or rel.drive or ".." in rel.parts:
        raise ProductionError(f"{label} must stay inside {root}")
    result = (root / rel).resolve()
    try:
        result.relative_to(root.resolve())
    except ValueError as exc:
        raise ProductionError(f"{label} escapes {root}") from exc
    return result


@dataclass(frozen=True)
class ProductManifest:
    root: Path
    id: str
    title: str
    version: int
    game_root: Path
    sources: dict[str, str]
    devlogs_dir: Path
    reels_dir: Path
    shared_dir: Path
    delivery_dir: Path


@dataclass(frozen=True)
class ProductionManifest:
    root: Path
    id: str
    kind: str
    date: str
    orientation: str
    version: int
    edit_dir: Path
    data_dir: Path
    delivery_dir: Path
    product: ProductManifest

    @property
    def finalize_dir(self) -> Path:
        return self.data_dir / "finalize"

    @property
    def review_dir(self) -> Path:
        return self.data_dir / "review"

    @property
    def publish_dir(self) -> Path:
        return self.data_dir / "publish"


def _read_toml(path: Path) -> dict:
    try:
        return tomllib.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ProductionError(f"manifest not found: {path}") from exc
    except tomllib.TOMLDecodeError as exc:
        raise ProductionError(f"invalid TOML in {path}: {exc}") from exc


def load_product_manifest(root_or_file: str | Path) -> ProductManifest:
    value = Path(root_or_file)
    path = value if value.name == "product.toml" else value / "product.toml"
    path = path.resolve()
    data = _read_toml(path)
    root = path.parent
    product_id = data.get("id")
    title = data.get("title")
    version = data.get("version", 1)
    if not isinstance(product_id, str) or not product_id.isidentifier():
        raise ProductionError("product id must be a valid identifier")
    if not isinstance(title, str) or not title.strip():
        raise ProductionError("product title must be non-empty")
    if version != 1:
        raise ProductionError(f"unsupported product manifest version: {version!r}")
    game_root_value = data.get("game_root")
    if not isinstance(game_root_value, str) or not game_root_value.strip():
        raise ProductionError("game_root must be a non-empty path")
    game_root = Path(game_root_value)
    if not game_root.is_absolute():
        game_root = (root / game_root).resolve()
    sources_raw = _mapping(data.get("sources", {}), "[sources]")
    sources: dict[str, str] = {}
    for key, value in sources_raw.items():
        if not isinstance(key, str) or not isinstance(value, str) or not value.strip():
            raise ProductionError("every [sources] value must be a non-empty string")
        sources[key] = value.strip()
    paths = _mapping(data.get("paths", {}), "[paths]")
    return ProductManifest(
        root=root,
        id=product_id,
        title=title.strip(),
        version=version,
        game_root=game_root,
        sources=sources,
        devlogs_dir=_relative_child(root, paths.get("devlogs", "devlogs"), "paths.devlogs"),
        reels_dir=_relative_child(root, paths.get("reels", "reels"), "paths.reels"),
        shared_dir=_relative_child(root, paths.get("shared", "shared"), "paths.shared"),
        delivery_dir=_relative_child(root, paths.get("delivery", "delivery"), "paths.delivery"),
    )


def _production_manifest_path(root_or_file: str | Path) -> Path:
    value = Path(root_or_file)
    if value.name == "production.toml":
        return value.resolve()
    return (value / "production.toml").resolve()


def _find_product_root(start: Path) -> Path:
    for candidate in (start, *start.parents):
        if (candidate / "product.toml").is_file():
            return candidate
    raise ProductionError(f"no product.toml found above production {start}")


def resolve_production_reference(ref: str | Path, workspace_root: Path | None = None) -> Path:
    """Resolve a path or ``product_id:production_id`` to a production root."""
    raw = str(ref)
    if ":" not in raw or Path(raw).drive:
        path = _production_manifest_path(ref)
        return path.parent
    product_id, production_id = raw.split(":", 1)
    if not product_id.isidentifier() or _PRODUCTION_ID_RE.fullmatch(production_id) is None:
        raise ProductionError(
            "production reference must use product_id:YYYY_MM_DD_<devlog|reel>_<NN>"
        )
    base = (workspace_root or Path.cwd()).resolve()
    product = load_product_manifest(base / product_id)
    candidates = [product.devlogs_dir / production_id, product.reels_dir / production_id]
    found = [path for path in candidates if (path / "production.toml").is_file()]
    if len(found) != 1:
        raise ProductionError(
            f"production {production_id!r} not found uniquely under {product.root}"
        )
    return found[0].resolve()


def load_production_manifest(root_or_file: str | Path) -> ProductionManifest:
    path = _production_manifest_path(root_or_file)
    data = _read_toml(path)
    root = path.parent
    production_id = data.get("id")
    match = _PRODUCTION_ID_RE.fullmatch(production_id or "")
    if match is None:
        raise ProductionError(
            "production id must use YYYY_MM_DD_<devlog|reel>_<NN>"
        )
    kind = data.get("kind")
    if kind != match.group("kind"):
        raise ProductionError(
            f"production kind {kind!r} does not match id {production_id!r}"
        )
    version = data.get("version", 1)
    if version != 1:
        raise ProductionError(f"unsupported production manifest version: {version!r}")
    declared_date = data.get("date")
    if not isinstance(declared_date, str):
        raise ProductionError("production date must use YYYY-MM-DD")
    try:
        calendar_date.fromisoformat(declared_date)
    except ValueError as exc:
        raise ProductionError("production date must use YYYY-MM-DD") from exc
    if declared_date.replace("-", "_") != match.group("date"):
        raise ProductionError("production date does not match its id prefix")
    orientation = data.get("orientation")
    if orientation not in {"landscape", "vertical"}:
        raise ProductionError("orientation must be 'landscape' or 'vertical'")

    product = load_product_manifest(_find_product_root(root))
    if root.name != production_id:
        raise ProductionError(
            f"production folder name {root.name!r} must equal manifest id {production_id!r}"
        )
    expected_parent = product.devlogs_dir if kind == "devlog" else product.reels_dir
    if root.parent.resolve() != expected_parent:
        raise ProductionError(
            f"{kind} production must live directly under {expected_parent}"
        )
    edit_dir = _relative_child(root, data.get("edit_path", "edit"), "edit_path")
    if not (edit_dir / "__init__.py").is_file():
        raise ProductionError(f"edit package is missing __init__.py: {edit_dir}")
    data_root_value = data.get("data_root", "data")
    if data_root_value != "data":
        raise ProductionError(
            "manifest v1 data_root must be literal 'data' because render, cache, "
            "review, publish, and Studio API paths are production-relative"
        )
    data_dir = _relative_child(root, data_root_value, "data_root")
    delivery_value = data.get("delivery_root")
    if not isinstance(delivery_value, str) or not delivery_value.strip():
        raise ProductionError("delivery_root must be a non-empty relative path")
    delivery_path = Path(delivery_value)
    if delivery_path.is_absolute() or delivery_path.drive:
        raise ProductionError("delivery_root must be relative to the production")
    delivery_dir = (root / delivery_path).resolve()
    kind_delivery = "devlogs" if kind == "devlog" else "reels"
    expected_delivery = (product.delivery_dir / kind_delivery / production_id).resolve()
    if delivery_dir != expected_delivery:
        raise ProductionError(
            f"delivery_root must resolve exactly to {expected_delivery}"
        )
    return ProductionManifest(
        root=root,
        id=production_id,
        kind=kind,
        date=declared_date,
        orientation=orientation,
        version=version,
        edit_dir=edit_dir,
        data_dir=data_dir,
        delivery_dir=delivery_dir,
        product=product,
    )


def is_filesystem_edit_ref(ref: str) -> bool:
    """True when ``ref`` is intended as a production path, not a module."""
    value = Path(ref)
    product_ref = ":" in ref and not value.drive
    return product_ref or value.exists() or value.name == "production.toml" or any(
        sep in ref for sep in ("/", "\\")
    )


def load_production_edit_module(
    root_or_file: str | Path,
    *,
    workspace_root: Path | None = None,
    force_reload: bool = False,
) -> tuple[ModuleType, ProductionManifest, str]:
    production_root = resolve_production_reference(root_or_file, workspace_root)
    manifest = load_production_manifest(production_root)
    digest = hashlib.sha256(str(manifest.root).casefold().encode("utf-8")).hexdigest()[:16]
    module_name = f"_dlstudio_production_{digest}"
    with _IMPORT_LOCK:
        existing = sys.modules.get(module_name)
        if existing is not None and not force_reload:
            return existing, manifest, module_name

        owned_names = [
            key for key in sys.modules
            if key == module_name or key.startswith(module_name + ".")
        ]
        snapshot = {key: sys.modules[key] for key in owned_names}
        for name in sorted(owned_names, reverse=True):
            sys.modules.pop(name, None)
        importlib.invalidate_caches()
        # A production can be edited and reloaded within one filesystem clock
        # tick.  CPython's timestamp+size pyc validation can then serve stale
        # code even after sys.modules eviction.  These are disposable caches
        # owned by the production; removing only their exact cache files makes
        # hot reload content-correct without touching source or unrelated pyc.
        for source in manifest.edit_dir.rglob("*.py"):
            try:
                Path(importlib.util.cache_from_source(str(source))).unlink(missing_ok=True)
            except (OSError, NotImplementedError):
                pass

        init_path = manifest.edit_dir / "__init__.py"
        spec = importlib.util.spec_from_file_location(
            module_name,
            init_path,
            submodule_search_locations=[str(manifest.edit_dir)],
        )
        if spec is None or spec.loader is None:
            for key, value in snapshot.items():
                sys.modules[key] = value
            raise ProductionError(f"cannot create import spec for {init_path}")
        module = importlib.util.module_from_spec(spec)
        module.__dlstudio_production_ref__ = str(manifest.root)
        module.__dlstudio_edit_dir__ = str(manifest.edit_dir)
        sys.modules[module_name] = module
        try:
            spec.loader.exec_module(module)
        except Exception:
            for key in [
                key for key in sys.modules
                if key == module_name or key.startswith(module_name + ".")
            ]:
                sys.modules.pop(key, None)
            sys.modules.update(snapshot)
            raise
        return module, manifest, module_name


def production_module_files(module_name: str) -> list[Path]:
    module = sys.modules.get(module_name)
    edit_dir = getattr(module, "__dlstudio_edit_dir__", None)
    if not edit_dir:
        return []
    return sorted(Path(edit_dir).rglob("*.py"))


def reload_production_edit_module(module_name: str) -> ModuleType:
    module = sys.modules.get(module_name)
    production_ref = getattr(module, "__dlstudio_production_ref__", None)
    if not production_ref:
        raise ProductionError(f"{module_name!r} is not a loaded production module")
    fresh, _manifest, _name = load_production_edit_module(
        production_ref, force_reload=True
    )
    return fresh
