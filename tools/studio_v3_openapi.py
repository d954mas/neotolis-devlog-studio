"""Write the deterministic OpenAPI contract for one Studio v3 adapter."""

from __future__ import annotations

import argparse
import json
import tempfile
from pathlib import Path
from typing import Any

from dlstudio.adapters.http import create_app


def openapi_bytes(manifest_path: Path) -> bytes:
    schema: dict[str, Any] = create_app(manifest_path).openapi()
    return (
        json.dumps(
            schema,
            ensure_ascii=False,
            allow_nan=False,
            indent=2,
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _fixture_manifest(root: Path) -> Path:
    (root / "edit.py").write_text("EDIT = object()\n", encoding="utf-8")
    manifest = root / "production.toml"
    manifest.write_text(
        "\n".join(
            (
                'schema = "dlstudio.production"',
                "version = 3",
                'id = "openapi.fixture"',
                'authoring = "edit.py"',
                'delivery_root = "delivery"',
                "",
            )
        ),
        encoding="utf-8",
    )
    return manifest


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="studio-v3-openapi")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.manifest is None:
        with tempfile.TemporaryDirectory(prefix="studio-v3-openapi-") as temporary:
            raw = openapi_bytes(_fixture_manifest(Path(temporary)))
    else:
        raw = openapi_bytes(args.manifest)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    if not args.output.is_file() or args.output.read_bytes() != raw:
        args.output.write_bytes(raw)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
