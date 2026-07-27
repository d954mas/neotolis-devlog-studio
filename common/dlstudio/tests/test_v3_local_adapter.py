from __future__ import annotations

from pathlib import Path

import pytest

from dlstudio.persistence.api import ProductionRepository
from dlstudio.persistence.assets import AssetRepository
from dlstudio.persistence.workflow import WorkflowRepository


def _write_manifest(
    root: Path,
    *,
    schema: str = "dlstudio.production",
    version: str = "3",
    production_id: str = "fixture.reel",
    authoring: str = "edit.py",
    delivery_root: str = "delivery",
    extra: str = "",
) -> Path:
    root.mkdir(parents=True)
    (root / "edit.py").write_text("EDIT = object()\n", encoding="utf-8")
    manifest = root / "production.toml"
    manifest.write_text(
        "\n".join(
            [
                f'schema = "{schema}"',
                f"version = {version}",
                f'id = "{production_id}"',
                f'authoring = "{authoring}"',
                f'delivery_root = "{delivery_root}"',
                extra,
                "",
            ]
        ),
        encoding="utf-8",
    )
    return manifest


def test_load_local_production_exposes_explicit_paths_and_repositories(
    tmp_path: Path,
) -> None:
    from dlstudio.adapters.local import load_local_production

    manifest = _write_manifest(tmp_path / "production")

    production = load_local_production(manifest)

    assert production.manifest_path == manifest.resolve()
    assert production.production_id == "fixture.reel"
    assert production.production_root == manifest.parent.resolve()
    assert production.authoring_path == (manifest.parent / "edit.py").resolve()
    assert production.delivery_root == (manifest.parent / "delivery").resolve()

    repository = production.repository
    assert isinstance(repository, ProductionRepository)
    assert repository.production_id == "fixture.reel"
    assert repository.object_root == manifest.parent / "data" / ".studio" / "objects"
    assert isinstance(production.workflows, WorkflowRepository)
    assert isinstance(production.assets, AssetRepository)


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"schema": "dlstudio.other"}, "unsupported production schema"),
        ({"version": "2"}, "unsupported production version"),
        ({"production_id": "../escape"}, "invalid domain id"),
        ({"extra": 'unexpected = "field"'}, "fields mismatch"),
    ],
)
def test_load_local_production_rejects_invalid_manifest_contract(
    tmp_path: Path,
    overrides: dict[str, str],
    message: str,
) -> None:
    from dlstudio.adapters.local import load_local_production

    manifest = _write_manifest(tmp_path / "production", **overrides)

    with pytest.raises(ValueError, match=message):
        load_local_production(manifest)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("authoring", "../outside.py", "authoring escapes"),
        ("delivery_root", "../delivery", "delivery_root escapes"),
        ("delivery_root", ".", "must not resolve to the production root"),
    ],
)
def test_load_local_production_rejects_paths_outside_its_root(
    tmp_path: Path,
    field: str,
    value: str,
    message: str,
) -> None:
    from dlstudio.adapters.local import load_local_production

    (tmp_path / "outside.py").write_text("EDIT = object()\n", encoding="utf-8")
    manifest = _write_manifest(tmp_path / "production", **{field: value})

    with pytest.raises(ValueError, match=message):
        load_local_production(manifest)


def test_load_local_production_does_not_treat_authoring_as_a_module(
    tmp_path: Path,
) -> None:
    from dlstudio.adapters.local import load_local_production

    manifest = _write_manifest(
        tmp_path / "production",
        authoring="some.importable.module",
    )

    with pytest.raises(ValueError, match="authoring does not exist"):
        load_local_production(manifest)
