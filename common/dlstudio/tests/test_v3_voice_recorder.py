from __future__ import annotations

import json
import subprocess
from pathlib import Path

from fastapi.testclient import TestClient

from dlstudio.application.api import (
    approve_voice_take,
    compile_production,
    query_voice_recorder,
    record_voice_take,
    start_workflow,
)
from dlstudio.authoring.api import load_edit
from dlstudio.assets.api import MediaFacts
from dlstudio.persistence.api import open_local_repositories
from dlstudio.workflow.api import NamedRef


SCRIPT = """Знаете проблему вагонетки?

Трамвай несётся на пятерых. Можно перевести стрелку — тогда погибнет один.

Как вам такое решение?"""


def _production(root: Path) -> tuple[Path, Path]:
    root.mkdir()
    authoring = root / "edit.py"
    authoring.write_text(
        "\n".join(
            (
                "from dlstudio.authoring.api import Edit, SolidLayer",
                "EDIT = Edit(",
                "    production_id='fixture.voice',",
                "    width=1080, height=1920, fps_num=30, fps_den=1,",
                "    duration_ns=1_000_000_000, background='black',",
                "    visuals=(SolidLayer(0, 1_000_000_000, 0, 0, 0, 1080, 1920, 'black'),),",
                "    standalone_story='A voice-led vertical reel.',",
                f"    voice_script={SCRIPT!r},",
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
                'id = "fixture.voice"',
                'authoring = "edit.py"',
                'delivery_root = "delivery"',
                "",
            )
        ),
        encoding="utf-8",
    )
    return manifest, authoring


def _audio_facts(_path: Path) -> MediaFacts:
    return MediaFacts(
        kind="audio",
        format_name="matroska,webm",
        duration_ns=2_400_000_000,
        sample_rate=48_000,
        channels=1,
        codec="opus",
    )


def test_ffprobe_measures_live_webm_from_audio_packets(
    tmp_path: Path, monkeypatch
) -> None:
    from dlstudio.adapters.providers.media import FfprobeMediaInspector

    probe_results = iter(
        (
            {
                "streams": [
                    {
                        "codec_name": "opus",
                        "codec_type": "audio",
                        "sample_rate": "48000",
                        "channels": 1,
                    }
                ],
                "format": {"format_name": "matroska,webm"},
            },
            {
                "packets": [
                    {"pts_time": "-0.007", "duration_time": "0.020"},
                    {"pts_time": "2.373", "duration_time": "0.020"},
                ]
            },
        )
    )
    calls: list[list[str]] = []

    def run(command, **_kwargs):
        calls.append(command)
        return subprocess.CompletedProcess(
            command,
            0,
            stdout=json.dumps(next(probe_results)),
            stderr="",
        )

    monkeypatch.setattr(subprocess, "run", run)
    facts = FfprobeMediaInspector()(tmp_path / "browser-live.webm")

    assert facts.kind == "audio"
    assert facts.codec == "opus"
    assert facts.duration_ns == 2_400_000_000
    assert len(calls) == 2
    assert "packet=pts_time,duration_time" in calls[1]


def test_voice_take_is_immutable_and_bound_to_exact_authoring_script(
    tmp_path: Path,
) -> None:
    _, authoring = _production(tmp_path / "production")
    repository, assets, _ = open_local_repositories(
        authoring.parent, "fixture.voice"
    )
    source = tmp_path / "take.webm"
    raw = b"fixture-browser-audio"
    source.write_bytes(raw)
    initial = query_voice_recorder(
        assets,
        repository.objects,
        production_id="fixture.voice",
        authoring_path=authoring,
        state_revision=0,
    )

    revision = record_voice_take(
        assets,
        repository.objects,
        production_id="fixture.voice",
        authoring_path=authoring,
        source=source,
        take_id="take001",
        recorded_at="2026-08-04T11:30:00.000Z",
        duration_ms=2400,
        mime_type="audio/webm",
        expected_production_id=initial.production_id,
        expected_script_ref=initial.script_ref,
        expected_revision=0,
        inspect_media=_audio_facts,
    )
    context = query_voice_recorder(
        assets,
        repository.objects,
        production_id="fixture.voice",
        authoring_path=authoring,
        state_revision=revision,
    )

    assert context.script_text == SCRIPT
    assert context.state_revision == 1
    assert len(context.takes) == 1
    assert context.takes[0].take_id == "take001"
    assert context.takes[0].current_script is True
    assert repository.objects.read(context.takes[0].blob) == raw
    assert source.read_bytes() == raw


def test_voice_take_approval_creates_revision_and_timeline_selection_is_explicit(
    tmp_path: Path,
) -> None:
    _, authoring = _production(tmp_path / "production")
    repository, assets, workflows = open_local_repositories(
        authoring.parent, "fixture.voice"
    )
    source = tmp_path / "take.webm"
    source.write_bytes(b"approved-browser-audio")
    initial = query_voice_recorder(
        assets,
        repository.objects,
        production_id="fixture.voice",
        authoring_path=authoring,
        state_revision=0,
    )
    revision = record_voice_take(
        assets,
        repository.objects,
        production_id="fixture.voice",
        authoring_path=authoring,
        source=source,
        take_id="take002",
        recorded_at="2026-08-04T11:32:00.000Z",
        duration_ms=2400,
        mime_type="audio/webm",
        expected_production_id=initial.production_id,
        expected_script_ref=initial.script_ref,
        expected_revision=0,
        inspect_media=_audio_facts,
    )

    approved_revision = approve_voice_take(
        assets,
        repository.objects,
        production_id="fixture.voice",
        authoring_path=authoring,
        asset_id="voice.take.take002",
        approved_at="2026-08-04T11:33:00.000Z",
        expected_production_id=initial.production_id,
        expected_script_ref=initial.script_ref,
        expected_revision=revision,
        inspect_media=_audio_facts,
    )

    context = query_voice_recorder(
        assets,
        repository.objects,
        production_id="fixture.voice",
        authoring_path=authoring,
        state_revision=approved_revision,
    )
    assert approved_revision == 2
    assert context.takes[0].approval_status == "approved"
    assert context.takes[0].referenced_by_timeline is False
    assert context.takes[0].asset_id == "voice.take.take002"
    authoring.write_text(
        authoring.read_text(encoding="utf-8").replace(
            "from dlstudio.authoring.api import Edit, SolidLayer",
            "from dlstudio.authoring.api import AudioClip, Edit, SolidLayer",
        ).replace(
            "    standalone_story='A voice-led vertical reel.',",
            "    standalone_story='A voice-led vertical reel.',\n"
            "    audio=(AudioClip('voice.take.take002', 0, "
            "1_000_000_000, role='voice'),),",
        ),
        encoding="utf-8",
    )
    timeline = compile_production(load_edit(authoring), assets)
    timeline_ref = repository.objects.put_bytes(timeline.canonical_bytes())
    run = start_workflow(workflows, run_id="run.voice", kind="reel")
    running = run.start("prepare", (), contract="fixture.prepare.v1")
    workflows.save(
        running,
        expected_workflow_revision=run.revision,
        expected_head_revision=workflows.head_revision(),
    )
    prepared = running.succeed(
        running.attempts[-1].operation_id,
        (NamedRef("timeline", timeline_ref),),
    )
    workflows.save(
        prepared,
        expected_workflow_revision=running.revision,
        expected_head_revision=workflows.head_revision(),
    )
    selected = query_voice_recorder(
        assets,
        repository.objects,
        production_id="fixture.voice",
        authoring_path=authoring,
        state_revision=approved_revision,
        workflows=workflows,
    )
    assert selected.takes[0].referenced_by_timeline is True


def test_http_voice_recorder_saves_and_streams_a_take(
    tmp_path: Path, monkeypatch
) -> None:
    from dlstudio.adapters.http import create_app
    from dlstudio.adapters.providers.media import FfprobeMediaInspector

    manifest, _ = _production(tmp_path / "production")
    monkeypatch.setattr(
        FfprobeMediaInspector,
        "__call__",
        lambda _self, path: _audio_facts(path),
    )
    client = TestClient(create_app(manifest))

    initial = client.get("/api/v3/voice")
    assert initial.status_code == 200
    assert initial.json()["script_text"] == SCRIPT
    assert initial.json()["takes"] == []

    raw = b"browser-media-recorder-audio"
    saved = client.post(
        "/api/v3/voice/takes",
        params={"expected_revision": 0},
        headers={
            "Content-Type": "audio/webm",
            "X-Recorded-At": "2026-08-04T11:31:00.000Z",
            "X-Duration-Ms": "2400",
            "X-Production-Id": initial.json()["production_id"],
            "X-Script-Sha256": initial.json()["script_ref"]["sha256"],
            "X-Script-Size": str(initial.json()["script_ref"]["size"]),
        },
        content=raw,
    )

    assert saved.status_code == 200, saved.text
    payload = saved.json()
    assert payload["state_revision"] == 1
    assert payload["takes"][0]["current_script"] is True
    assert payload["takes"][0]["approval_status"] == "pending"
    assert payload["takes"][0]["referenced_by_timeline"] is False
    blob = payload["takes"][0]["blob"]
    streamed = client.get(
        f"/api/v3/blobs/{blob['sha256']}", params={"size": blob["size"]}
    )
    assert streamed.status_code == 200
    assert streamed.content == raw

    wrong_production = client.post(
        f"/api/v3/voice/takes/{payload['takes'][0]['asset_id']}/approve",
        json={
            "expected_revision": payload["state_revision"],
            "approved_at": "2026-08-04T11:33:00.000Z",
            "expected_production_id": "fixture.foreign",
            "expected_script_ref": payload["script_ref"],
        },
    )
    assert wrong_production.status_code == 409
    assert "another production" in wrong_production.json()["detail"]
    assert client.get("/api/v3/voice").json()["state_revision"] == 1

    approved = client.post(
        f"/api/v3/voice/takes/{payload['takes'][0]['asset_id']}/approve",
        json={
            "expected_revision": payload["state_revision"],
            "approved_at": "2026-08-04T11:34:00.000Z",
            "expected_production_id": payload["production_id"],
            "expected_script_ref": payload["script_ref"],
        },
    )
    assert approved.status_code == 200, approved.text
    assert approved.json()["state_revision"] == 2
    assert approved.json()["takes"][0]["approval_status"] == "approved"


def test_voice_api_rejects_authoring_from_another_manifest_production(
    tmp_path: Path,
) -> None:
    from dlstudio.adapters.http import create_app

    manifest, authoring = _production(tmp_path / "production")
    authoring.write_text(
        authoring.read_text(encoding="utf-8").replace(
            "production_id='fixture.voice'",
            "production_id='fixture.foreign'",
        ),
        encoding="utf-8",
    )

    response = TestClient(create_app(manifest)).get("/api/v3/voice")

    assert response.status_code == 409
    assert "production identity mismatch" in response.json()["detail"]


def test_http_voice_recorder_rejects_non_audio_before_asset_commit(
    tmp_path: Path,
) -> None:
    from dlstudio.adapters.http import create_app

    manifest, _ = _production(tmp_path / "production")
    client = TestClient(create_app(manifest))
    context = client.get("/api/v3/voice").json()
    response = client.post(
        "/api/v3/voice/takes",
        params={"expected_revision": 0},
        headers={
            "Content-Type": "video/webm",
            "X-Recorded-At": "2026-08-04T11:31:00.000Z",
            "X-Duration-Ms": "2400",
            "X-Production-Id": context["production_id"],
            "X-Script-Sha256": context["script_ref"]["sha256"],
            "X-Script-Size": str(context["script_ref"]["size"]),
        },
        content=b"not-a-voice-take",
    )
    assert response.status_code == 415
    assert client.get("/api/v3/voice").json()["takes"] == []


def test_http_voice_recorder_rejects_draft_from_previous_script(
    tmp_path: Path,
    monkeypatch,
) -> None:
    from dlstudio.adapters.http import create_app
    from dlstudio.adapters.providers.media import FfprobeMediaInspector

    manifest, authoring = _production(tmp_path / "production")
    monkeypatch.setattr(
        FfprobeMediaInspector,
        "__call__",
        lambda _self, path: _audio_facts(path),
    )
    client = TestClient(create_app(manifest))
    old = client.get("/api/v3/voice").json()
    authoring.write_text(
        authoring.read_text(encoding="utf-8").replace(
            f"voice_script={SCRIPT!r}",
            "voice_script='A changed exact script.'",
        ),
        encoding="utf-8",
    )

    response = client.post(
        "/api/v3/voice/takes",
        params={"expected_revision": 0},
        headers={
            "Content-Type": "audio/webm",
            "X-Recorded-At": "2026-08-04T11:35:00.000Z",
            "X-Duration-Ms": "2400",
            "X-Production-Id": old["production_id"],
            "X-Script-Sha256": old["script_ref"]["sha256"],
            "X-Script-Size": str(old["script_ref"]["size"]),
        },
        content=b"draft-for-old-script",
    )

    assert response.status_code == 409
    assert "another script" in response.json()["detail"]
    assert client.get("/api/v3/voice").json()["takes"] == []
