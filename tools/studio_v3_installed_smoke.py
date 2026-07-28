"""Smoke-test the installed Studio v3 wheel, not the source checkout."""

from __future__ import annotations

import re
import shutil
import subprocess
import tempfile
from pathlib import Path

import dlstudio
from fastapi.testclient import TestClient

from dlstudio.adapters.http import create_app


def main() -> int:
    repo_root = Path(__file__).resolve().parents[1]
    package_root = Path(dlstudio.__file__).resolve().parent
    source_root = (repo_root / "common" / "dlstudio" / "src").resolve()
    if package_root.is_relative_to(source_root):
        raise RuntimeError(f"source checkout imported instead of wheel: {package_root}")

    command = shutil.which("dl2")
    if command is None:
        raise RuntimeError("installed dl2 entrypoint is missing")
    help_result = subprocess.run(
        [command, "--help"],
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if help_result.returncode != 0 or "advance" not in help_result.stdout:
        raise RuntimeError(f"installed dl2 entrypoint failed: {help_result.stderr}")

    with tempfile.TemporaryDirectory(prefix="studio-v3-wheel-smoke-") as raw:
        production = Path(raw)
        (production / "authoring.py").write_text(
            "EDIT = object()\n", encoding="utf-8"
        )
        manifest = production / "production.toml"
        manifest.write_text(
            "\n".join(
                (
                    'schema = "dlstudio.production"',
                    "version = 3",
                    'id = "wheel.smoke"',
                    'authoring = "authoring.py"',
                    'delivery_root = "delivery"',
                    "",
                )
            ),
            encoding="utf-8",
        )
        client = TestClient(create_app(manifest))
        dashboard = client.get("/")
        if dashboard.status_code != 200:
            raise RuntimeError("installed wheel does not serve the dashboard")
        match = re.search(r'src="[./]*(assets/[^"]+\.js)"', dashboard.text)
        asset_path = f"/{match.group(1)}" if match is not None else ""
        if not asset_path or client.get(asset_path).status_code != 200:
            raise RuntimeError("installed wheel is missing dashboard assets")
        if client.get("/api/v3/status").status_code != 200:
            raise RuntimeError("installed wheel status endpoint failed")

    forbidden = {"api", "cache", "check", "cli", "compile", "model", "render", "services"}
    present = forbidden.intersection(path.name for path in package_root.iterdir())
    if present or (package_root / "authoring" / "loader.py").exists():
        raise RuntimeError(f"legacy or duplicate modules in wheel: {sorted(present)}")
    print(f"installed-wheel-smoke: PASS ({package_root})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
