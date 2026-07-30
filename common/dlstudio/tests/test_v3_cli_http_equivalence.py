from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from dlstudio.application.api import start_workflow
from dlstudio.foundation.api import CasConflict
from dlstudio.persistence.api import open_local_repositories


def _production(root: Path, *, prestart: bool = True) -> Path:
    root.mkdir()
    (root / "edit.py").write_text(
        "\n".join(
            (
                "from dlstudio.authoring.api import Edit, SolidLayer",
                "EDIT = Edit(",
                "    production_id='fixture.reel',",
                "    width=64, height=96, fps_num=30, fps_den=1,",
                "    duration_ns=200_000_000, background='black',",
                "    visuals=(SolidLayer(0, 200_000_000, 0, 0, 0, 64, 96, 'black'),),",
                "    standalone_story='A complete synthetic release.',",
                ")",
                "",
            )
        ),
        encoding="utf-8",
    )
    manifest = root / "production.toml"
    manifest.write_text(
        "\n".join(
            (
                'schema = "dlstudio.production"',
                "version = 3",
                'id = "fixture.reel"',
                'authoring = "edit.py"',
                'delivery_root = "delivery"',
                "",
            )
        ),
        encoding="utf-8",
    )
    if prestart:
        _, _, workflows = open_local_repositories(root, "fixture.reel")
        start_workflow(workflows, run_id="run.main", kind="reel")
    return manifest


def _cli_json(manifest: Path, command: str, capsys) -> dict[str, object]:
    from dlstudio.adapters.cli import main

    assert main(["--manifest", str(manifest), command]) == 0
    return json.loads(capsys.readouterr().out)


def test_cli_and_http_status_are_the_same_workflow_projection(
    tmp_path: Path, capsys
) -> None:
    from dlstudio.adapters.http import create_app

    manifest = _production(tmp_path / "production", prestart=False)
    cli = _cli_json(manifest, "status", capsys)
    response = TestClient(create_app(manifest)).get("/api/v3/status")

    assert response.status_code == 200
    assert response.json() == cli


def test_cli_and_http_advance_call_the_same_application_flow(
    tmp_path: Path, capsys
) -> None:
    from dlstudio.adapters.http import create_app

    cli_manifest = _production(tmp_path / "cli", prestart=False)
    http_manifest = _production(tmp_path / "http", prestart=False)

    cli = _cli_json(cli_manifest, "advance", capsys)
    response = TestClient(create_app(http_manifest)).post("/api/v3/advance")

    assert response.status_code == 200
    assert response.json() == cli


def test_cli_and_http_review_share_round_semantics(
    tmp_path: Path,
    capsys,
) -> None:
    from dlstudio.adapters.cli import main
    from dlstudio.adapters.http import create_app

    cli_manifest = _production(tmp_path / "cli", prestart=False)
    http_manifest = _production(tmp_path / "http", prestart=False)
    http_client = TestClient(create_app(http_manifest))

    for _ in range(3):
        assert main(["--manifest", str(cli_manifest), "advance"]) == 0
        capsys.readouterr()
        assert http_client.post("/api/v3/advance").status_code == 200

    cli_context = TestClient(create_app(cli_manifest)).get(
        "/api/v3/review/context"
    ).json()
    http_context = http_client.get("/api/v3/review/context").json()
    finding = {
        "finding_id": "review.transport.001",
        "text": "Move the title.",
        "requires_change": True,
        "locator": {
            "start_frame": 0,
            "end_frame_exclusive": 1,
            "region": None,
            "target_ids": ["visual.000"],
        },
    }
    verdict_path = tmp_path / "verdict.json"
    verdict_path.write_text(
        json.dumps(
            {
                "outcome": "changes_requested",
                "scope": ["visual"],
                "reviewer": "video.reviewer",
                "reviewed_at": "2026-07-30T00:00:00Z",
                "findings": [finding],
                "expected_latest_round": None,
                "resolutions": [],
            }
        ),
        encoding="utf-8",
    )

    assert main(
        [
            "--manifest",
            str(cli_manifest),
            "review",
            "--verdict",
            str(verdict_path),
        ]
    ) == 0
    cli_status = json.loads(capsys.readouterr().out)
    http_response = http_client.post(
        "/api/v3/review",
        json={
            "expected_artifact": http_context["artifact"],
            "expected_timeline": http_context["timeline"],
            "expected_check_report": http_context["check_report"],
            "expected_constraints": http_context["constraints"],
            "outcome": "changes_requested",
            "scope": ["visual"],
            "reviewer": "video.reviewer",
            "reviewed_at": "2026-07-30T00:00:00Z",
            "findings": [finding],
            "expected_latest_round": None,
            "resolutions": [],
        },
    )

    assert http_response.status_code == 200
    assert cli_context["items"] == http_context["items"]
    assert cli_status["current_stage"] == "review"
    assert cli_status["action"] == "review"
    assert http_response.json()["current_stage"] == "review"
    assert http_response.json()["action"] == "review"


@pytest.mark.performance_smoke
def test_cli_api_no_heavy_provider_import() -> None:
    command = (
        "import sys; "
        "import dlstudio.adapters.cli, dlstudio.adapters.http; "
        "assert 'dlstudio.adapters.providers.media' not in sys.modules"
    )
    result = subprocess.run(
        [sys.executable, "-c", command],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_openapi_has_no_path_file_or_job_queue_surface(tmp_path: Path) -> None:
    from dlstudio.adapters.http import create_app

    paths = create_app(_production(tmp_path / "production")).openapi()["paths"]

    assert set(paths) == {
        "/api/v3/status",
        "/api/v3/advance",
        "/api/v3/review",
        "/api/v3/review/context",
            "/api/v3/review/current",
            "/api/v3/review/task-pack",
            "/api/v3/review/artifacts/{sha256}",
            "/api/v3/review/artifacts/{sha256}/evidence",
            "/api/v3/review/artifacts/{sha256}/waveform",
            "/api/v3/deliver",
            "/api/v3/blobs/{sha256}",
        }
    assert all("job" not in path and "file" not in path for path in paths)


def test_openapi_generation_is_deterministic(tmp_path: Path) -> None:
    from tools.studio_v3_openapi import openapi_bytes

    manifest = _production(tmp_path / "production")
    checked_in = (
        Path(__file__).parents[1]
        / "webui"
        / "src"
        / "api"
        / "openapi.v3.json"
    ).read_bytes()

    assert openapi_bytes(manifest) == checked_in
    assert openapi_bytes(manifest) == openapi_bytes(manifest)


def test_studio_server_is_loopback_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from dlstudio.adapters.cli import main

    manifest = _production(tmp_path / "production")
    called: dict[str, object] = {}

    def run(_app: object, **kwargs: object) -> None:
        called.update(kwargs)

    monkeypatch.setattr("uvicorn.run", run)
    assert main(["--manifest", str(manifest), "serve", "--port", "8799"]) == 0
    assert called == {"host": "127.0.0.1", "port": 8799}

    with pytest.raises(SystemExit):
        main(
            [
                "--manifest",
                str(manifest),
                "serve",
                "--host",
                "0.0.0.0",
            ]
        )


def test_expected_studio_errors_are_structured(
    tmp_path: Path,
    capsys,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from dlstudio.adapters import cli as cli_adapter
    from dlstudio.adapters import http as http_adapter

    manifest = _production(tmp_path / "production")

    def conflict(_repository: object) -> object:
        raise CasConflict("head changed")

    monkeypatch.setattr(cli_adapter, "query_status", conflict)
    assert cli_adapter.main(["--manifest", str(manifest), "status"]) == 2
    assert capsys.readouterr().err == "BLOCKED: head changed\n"

    monkeypatch.setattr(http_adapter, "query_status", conflict)
    response = TestClient(http_adapter.create_app(manifest)).get("/api/v3/status")
    assert response.status_code == 409
    assert response.json() == {"detail": "head changed"}


def test_http_control_plane_rejects_cross_origin_and_rebound_hosts(
    tmp_path: Path,
) -> None:
    from dlstudio.adapters.http import create_app

    manifest = _production(tmp_path / "production", prestart=False)
    app = create_app(manifest)
    client = TestClient(app, base_url="http://127.0.0.1")

    cross_origin = client.post(
        "/api/v3/advance",
        headers={
            "Origin": "https://attacker.example",
            "Sec-Fetch-Site": "cross-site",
        },
    )
    assert cross_origin.status_code == 403
    assert cross_origin.json() == {"detail": "cross-origin request blocked"}

    rebound = client.get(
        "/api/v3/status",
        headers={"Host": "attacker.example"},
    )
    assert rebound.status_code == 400

    _, _, workflows = open_local_repositories(
        manifest.parent, "fixture.reel"
    )
    assert workflows.read_current() is None
