from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from dlstudio.adapters.http import create_app
from dlstudio.adapters.local import load_local_production
from dlstudio.application.api import (
    IngestAssetCommand,
    advance_production,
    ingest_asset,
)
from dlstudio.assets.api import Approval, License, MediaFacts, Provenance
from dlstudio.persistence.api import open_local_repositories


def _authoring_source(color: str) -> str:
    return "\n".join(
        (
            (
                "from dlstudio.authoring.api import "
                "Edit, PublicationFile, SolidLayer"
            ),
            "EDIT = Edit(",
            "    production_id='fixture.review_agent_loop',",
            "    width=64, height=96, fps_num=30, fps_den=1,",
            "    duration_ns=200_000_000, background='#000000',",
            "    visuals=(",
            "        SolidLayer(",
            "            0, 200_000_000, 0, 0, 0, 64, 96,",
            f"            '{color}',",
            "        ),",
            "    ),",
            "    standalone_story='A synthetic review agent loop.',",
            "    publication=(",
            "        PublicationFile('cover', 'cover.png', 'publish.cover.main'),",
            "        PublicationFile('metadata', 'metadata.md', 'publish.metadata.main'),",
            "    ),",
            "    kind='reel',",
            ")",
            "",
        )
    )


def _production(root: Path) -> tuple[Path, Path]:
    root.mkdir()
    authoring = root / "edit.py"
    authoring.write_text(_authoring_source("#112233"), encoding="utf-8")
    manifest = root / "production.toml"
    manifest.write_text(
        "\n".join(
            (
                'schema = "dlstudio.production"',
                "version = 3",
                'id = "fixture.review_agent_loop"',
                'authoring = "edit.py"',
                'delivery_root = "delivery"',
                "",
            )
        ),
        encoding="utf-8",
    )
    repository, assets, _ = open_local_repositories(
        root, "fixture.review_agent_loop"
    )
    for expected_revision, (asset_id, filename, raw, media) in enumerate((
        (
            "publish.cover.main",
            "cover.png",
            b"fixture cover",
            MediaFacts("image", "png", width=64, height=96),
        ),
        (
            "publish.metadata.main",
            "metadata.md",
            b"fixture metadata",
            MediaFacts("data", "markdown"),
        ),
    )):
        source = root / filename
        source.write_bytes(raw)
        ingest_asset(
            assets,
            IngestAssetCommand(
                source,
                asset_id,
                Provenance("provided", "review_loop_fixture"),
                Approval(
                    "approved",
                    (repository.objects.put_bytes(f"approved:{asset_id}".encode()),),
                ),
                License("owned", False),
                expected_revision,
            ),
            inspect_media=lambda _path, value=media: value,
        )
    return manifest, authoring


def _advance(manifest: Path):
    production = load_local_production(manifest)
    return advance_production(
        production.workflows,
        production.assets,
        production.repository.objects,
        authoring_path=production.authoring_path,
        output_root=(
            production.production_root / "data" / ".studio" / "outputs"
        ),
        cache_root=(
            production.production_root / "data" / ".studio" / "cache"
        ),
    )


def _fresh_process_handoff(manifest: Path) -> dict[str, object]:
    script = """
import json
import sys
from pathlib import Path

from fastapi.testclient import TestClient
from dlstudio.adapters.http import create_app

with TestClient(create_app(Path(sys.argv[1]))) as client:
    task_pack = client.get("/api/v3/review/task-pack")
    task_pack.raise_for_status()
    print(json.dumps(task_pack.json(), sort_keys=True))
"""
    completed = subprocess.run(
        [sys.executable, "-c", script, str(manifest)],
        check=True,
        capture_output=True,
        text=True,
    )
    value = json.loads(completed.stdout)
    assert isinstance(value, dict)
    return value


def test_exact_feedback_drives_a_fresh_process_authoring_revision(
    tmp_path: Path,
) -> None:
    manifest, authoring = _production(tmp_path / "production")

    assert _advance(manifest).current_stage == "draft"
    assert _advance(manifest).current_stage == "final"
    assert _advance(manifest).current_stage == "review"

    with TestClient(create_app(manifest)) as client:
        context_response = client.get("/api/v3/review/context")
        assert context_response.status_code == 200
        context = context_response.json()
        assert context["items"] == [
            {
                "item_id": "visual.000",
                "kind": "visual",
                "lane": "layer.0",
                "label": "solid #112233",
                "start_ns": 0,
                "duration_ns": 200_000_000,
                "z": 0,
            }
        ]

        submitted = client.post(
            "/api/v3/review",
            json={
                    "expected_artifact": context["artifact"],
                    "expected_timeline": context["timeline"],
                    "expected_artifact_report": context["artifact_report"],
                    "expected_publication_manifest": context[
                        "publication_manifest"
                    ],
                    "expected_check_report": context["check_report"],
                "expected_constraints": context["constraints"],
                "outcome": "changes_requested",
                    "scope": ["visual", "publication"],
                "reviewer": "phase0.owner",
                "reviewed_at": "2026-07-30T00:00:00Z",
                "findings": [
                    {
                        "finding_id": "phase0.visual.001",
                        "text": "Изменить цвет этой области.",
                        "requires_change": True,
                        "locator": {
                            "start_frame": 0,
                            "end_frame_exclusive": 1,
                            "region": {
                                "x_milli": 100,
                                "y_milli": 200,
                                "width_milli": 300,
                                "height_milli": 150,
                            },
                            "target_ids": ["visual.000"],
                        },
                    }
                ],
            },
        )
        assert submitted.status_code == 200
        assert submitted.json()["current_stage"] == "review"
        assert submitted.json()["action"] == "review"

    handoff = _fresh_process_handoff(manifest)
    assert handoff["source_mapping"] == {"status": "unavailable"}
    verdict = handoff["verdict"]
    previous_context = handoff
    assert isinstance(verdict, dict)
    assert isinstance(previous_context, dict)
    assert verdict["findings"][0]["locator"]["target_ids"] == [
        "visual.000"
    ]
    assert handoff["target_snapshots"] == [
        {
            "item_id": "visual.000",
            "kind": "visual",
            "lane": "layer.0",
            "label": "solid #112233",
            "start_ns": 0,
            "duration_ns": 200_000_000,
            "z": 0,
        }
    ]

    source = authoring.read_text(encoding="utf-8")
    assert source.count("'#112233'") == 1
    authoring.write_text(
        source.replace("'#112233'", "'#446688'"),
        encoding="utf-8",
    )

    assert _advance(manifest).current_stage == "draft"
    assert _advance(manifest).current_stage == "final"
    assert _advance(manifest).current_stage == "review"

    with TestClient(create_app(manifest)) as client:
        next_response = client.get("/api/v3/review/context")
        assert next_response.status_code == 200
        next_context = next_response.json()

    assert next_context["timeline"] != previous_context["timeline"]
    assert next_context["artifact"] != previous_context["artifact"]
    assert next_context["items"][0]["item_id"] == "visual.000"
    assert next_context["items"][0]["label"] == "solid #446688"
