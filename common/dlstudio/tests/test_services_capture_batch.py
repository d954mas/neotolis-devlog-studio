from __future__ import annotations

import importlib.util
import hashlib
import json
from pathlib import Path
import shutil
import subprocess

import pytest


def _record_script_module():
    path = (
        Path(__file__).resolve().parents[3]
        / ".agents"
        / "skills"
        / "devlog-record-media"
        / "scripts"
        / "record_window_realtime.py"
    )
    spec = importlib.util.spec_from_file_location("record_window_realtime", path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _production(tmp_path: Path) -> Path:
    product = tmp_path / "not_a_trolley_problem"
    production = product / "reels" / "2026_07_18_reel_01"
    (production / "edit").mkdir(parents=True)
    (production / "edit" / "__init__.py").write_text("", encoding="utf-8")
    (product / "product.toml").write_text(
        '\n'.join((
            'id = "not_a_trolley_problem"',
            'title = "Not a Trolley Problem"',
            'game_root = "."',
            '[sources]',
        )),
        encoding="utf-8",
    )
    (production / "production.toml").write_text(
        '\n'.join((
            'id = "2026_07_18_reel_01"',
            'kind = "reel"',
            'date = "2026-07-18"',
            'orientation = "vertical"',
            'edit_path = "edit"',
            'data_root = "data"',
            'delivery_root = "../../delivery/reels/2026_07_18_reel_01"',
        )),
        encoding="utf-8",
    )
    return production


def test_prepare_capture_batch_normalizes_all_missing_captures_in_one_file(tmp_path):
    production = _production(tmp_path)
    requests = production / "data" / "plan" / "capture_requests.json"
    requests.parent.mkdir(parents=True)
    requests.write_text(json.dumps({
        "version": 1,
        "requests": [
            {"id": "game", "source": "gameplay", "target": "data/footage/game.mp4", "orientation": "vertical", "min_width": 1080, "min_height": 1920},
            {"id": "diary", "source": "diary", "target": "data/images/diary.png", "orientation": "landscape", "min_width": 1920, "min_height": 1080},
        ],
    }), encoding="utf-8")

    from dlstudio.services.capture_batch import prepare_capture_batch

    batch = prepare_capture_batch(production, requests)

    assert batch.product_id == "not_a_trolley_problem"
    assert batch.production_id == "2026_07_18_reel_01"
    assert [item.id for item in batch.requests] == ["game", "diary"]
    assert all(Path(item.target_absolute).is_absolute() for item in batch.requests)
    assert (production / "data" / "plan" / "capture_batch.json").is_file()


def test_capture_ingest_verifies_hash_and_refreshes_asset_catalog(tmp_path):
    production = _production(tmp_path)
    requests = production / "data" / "plan" / "capture_requests.json"
    requests.parent.mkdir(parents=True)
    requests.write_text(json.dumps({
        "version": 1,
        "requests": [{
            "id": "diary", "source": "diary",
            "target": "data/images/diary.png", "orientation": "landscape",
            "min_width": 1, "min_height": 1,
        }],
    }), encoding="utf-8")

    from PIL import Image
    from dlstudio.services.capture_batch import ingest_capture_results, prepare_capture_batch

    prepare_capture_batch(production, requests)
    captured = production / "data" / "images" / "diary.png"
    captured.parent.mkdir(parents=True)
    Image.new("RGB", (2, 2), "red").save(captured)
    digest = hashlib.sha256(captured.read_bytes()).hexdigest()
    result_path = production / "data" / "plan" / "capture_results.json"
    result_path.write_text(json.dumps({
        "version": 1,
        "production_id": "2026_07_18_reel_01",
        "results": [{"request_id": "diary", "status": "captured", "path": "data/images/diary.png", "sha256": digest}],
    }), encoding="utf-8")

    receipt = ingest_capture_results(production, result_path)

    assert receipt.ingested == ("diary",)
    catalog = json.loads((production / "data" / "assets" / "catalog.json").read_text(encoding="utf-8"))
    assert any(item["path"] == "data/images/diary.png" for item in catalog["assets"])


def test_capture_batch_rejects_target_traversal(tmp_path):
    production = _production(tmp_path)
    requests = production / "requests.json"
    requests.write_text(json.dumps({
        "version": 1,
        "requests": [{"id": "bad", "source": "gameplay", "target": "../escape.mp4", "orientation": "vertical", "min_width": 1080, "min_height": 1920}],
    }), encoding="utf-8")

    from dlstudio.services.capture_batch import CaptureBatchError, prepare_capture_batch

    with pytest.raises(CaptureBatchError, match="target must stay inside production data"):
        prepare_capture_batch(production, requests)


def _gameplay_request_v2(**overrides) -> dict:
    request = {
        "id": "day5_station",
        "source": "gameplay",
        "target": "data/footage/day5_station.mp4",
        "editorial_role": "gameplay",
        "capture_method": "realtime_window",
        "state_id": "day5.station.new_visual",
        "scene": "day5.station.new_visual",
        "build_id": "exe-sha256:" + "a" * 64,
        "orientation": "landscape",
        "min_width": 1920,
        "min_height": 1080,
        "min_fps": 30,
        "simulation_rate": 1.0,
        "content_seconds": 20,
        "head_handle_seconds": 5,
        "tail_handle_seconds": 5,
        "continuous": True,
        "clean_ui": True,
        "action_id": "station_queue_and_tram_pass",
    }
    request.update(overrides)
    return request


def test_prepare_capture_batch_v2_accepts_strict_realtime_gameplay(tmp_path):
    production = _production(tmp_path)
    requests = production / "data" / "plan" / "capture_requests.json"
    requests.parent.mkdir(parents=True)
    requests.write_text(json.dumps({
        "version": 2,
        "requests": [_gameplay_request_v2()],
    }), encoding="utf-8")

    from dlstudio.services.capture_batch import prepare_capture_batch

    batch = prepare_capture_batch(production, requests)

    assert batch.version == 2
    assert batch.requests[0].capture_method == "realtime_window"
    assert batch.requests[0].state_id == "day5.station.new_visual"
    assert batch.requests[0].head_handle_seconds == 5


def test_realtime_recorder_hydrates_exact_task_and_writes_ingest_result(tmp_path):
    production = _production(tmp_path)
    request = _gameplay_request_v2(
        target="data/footage/day5.mp4",
        min_width=192,
        min_height=108,
        min_fps=30,
        content_seconds=1,
    )
    request["target_absolute"] = str(production / request["target"])
    batch_path = production / "data" / "plan" / "capture_batch.json"
    batch_path.parent.mkdir(parents=True, exist_ok=True)
    batch_path.write_text(json.dumps({
        "version": 2,
        "product_id": "not_a_trolley_problem",
        "production_id": "2026_07_18_reel_01",
        "game_root": str(production.parent.parent),
        "production_root": str(production),
        "requested_at": "2026-07-24T00:00:00Z",
        "requests": [request],
    }), encoding="utf-8")
    recorder = _record_script_module()
    args = recorder._parser().parse_args([
        "--pid", "123",
        "--batch", str(batch_path),
        "--request-id", request["id"],
    ])

    production_id = recorder._hydrate_from_batch(args)

    assert production_id == "2026_07_18_reel_01"
    assert args.output == Path(request["target_absolute"])
    assert args.state_id == request["scene"]
    assert args.action_id == request["action_id"]
    assert args.results == production / "data" / "plan" / "capture_results.json"

    output = Path(request["target_absolute"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(b"video")
    metadata = output.with_suffix(".mp4.capture.json")
    metadata.write_bytes(b"metadata")
    game_report = output.with_suffix(".mp4.game.json")
    game_report.write_bytes(b"game")
    recorder._write_result(
        args.results,
        production_id=production_id,
        request_id=request["id"],
        production_root=production,
        output=output,
        artifact_sha=hashlib.sha256(output.read_bytes()).hexdigest(),
        metadata_path=metadata,
        metadata_sha=hashlib.sha256(metadata.read_bytes()).hexdigest(),
        game_report_path=game_report,
        game_report_sha=hashlib.sha256(game_report.read_bytes()).hexdigest(),
        state_id=args.state_id,
        build_id=args.build_id,
        captured_at="2026-07-24T00:00:11Z",
    )

    results = json.loads(args.results.read_text(encoding="utf-8"))
    saved = results["results"][0]
    assert saved["path"] == "data/footage/day5.mp4"
    assert saved["game_report_path"] == "data/footage/day5.mp4.game.json"


def test_prepare_capture_batch_v2_rejects_frame_stepped_gameplay(tmp_path):
    production = _production(tmp_path)
    requests = production / "data" / "plan" / "capture_requests.json"
    requests.parent.mkdir(parents=True)
    requests.write_text(json.dumps({
        "version": 2,
        "requests": [
            _gameplay_request_v2(capture_method="deterministic_devapi"),
        ],
    }), encoding="utf-8")

    from dlstudio.services.capture_batch import CaptureBatchError, prepare_capture_batch

    with pytest.raises(CaptureBatchError, match="gameplay requires capture_method=realtime_window"):
        prepare_capture_batch(production, requests)


@pytest.mark.parametrize(
    ("field", "value", "message"),
    [
        ("state_id", "", "state_id"),
        ("scene", None, "game-owned capture scene"),
        ("build_id", "", "build_id"),
        ("action_id", "", "action_id"),
        ("head_handle_seconds", 4.9, "head_handle_seconds"),
        ("tail_handle_seconds", 0, "tail_handle_seconds"),
        ("simulation_rate", 2.0, "simulation_rate"),
        ("continuous", False, "continuous"),
        ("clean_ui", False, "clean_ui"),
    ],
)
def test_prepare_capture_batch_v2_rejects_unsafe_gameplay_contract(
    tmp_path,
    field,
    value,
    message,
):
    production = _production(tmp_path)
    requests = production / "data" / "plan" / "capture_requests.json"
    requests.parent.mkdir(parents=True)
    requests.write_text(json.dumps({
        "version": 2,
        "requests": [_gameplay_request_v2(**{field: value})],
    }), encoding="utf-8")

    from dlstudio.services.capture_batch import CaptureBatchError, prepare_capture_batch

    with pytest.raises(CaptureBatchError, match=message):
        prepare_capture_batch(production, requests)


def _prepare_v2_gameplay_capture(
    production: Path,
    *,
    actual_state: str | None = None,
    game_elapsed_seconds: float = 11.0,
):
    requests = production / "data" / "plan" / "capture_requests.json"
    requests.parent.mkdir(parents=True, exist_ok=True)
    request = _gameplay_request_v2(
        min_width=192,
        min_height=108,
        content_seconds=1,
    )
    requests.write_text(json.dumps({
        "version": 2,
        "requests": [request],
    }), encoding="utf-8")

    from dlstudio.services.capture_batch import prepare_capture_batch

    prepare_capture_batch(production, requests)
    captured = production / request["target"]
    captured.parent.mkdir(parents=True, exist_ok=True)
    captured.write_bytes(b"fake-video-for-contract-test")
    artifact_sha = hashlib.sha256(captured.read_bytes()).hexdigest()
    metadata = {
        "schema": "devlog.realtime_window_capture",
        "version": 1,
        "capture_method": "realtime_window",
        "editorial_role": "gameplay",
        "state_id": actual_state or request["state_id"],
        "build_id": request["build_id"],
        "action_id": request["action_id"],
        "executable_path": "C:/game/game.exe",
        "executable_sha256": "a" * 64,
        "artifact": str(captured),
        "sha256": artifact_sha,
        "client_area": True,
        "cursor_visible": False,
        "client_rect": {"x": 0, "y": 0, "width": 192, "height": 108},
        "fps": 30,
        "simulation_rate": 1.0,
        "continuous": True,
        "clean_ui": True,
        "content_seconds": 1,
        "head_handle_seconds": 5,
        "tail_handle_seconds": 5,
        "started_at": "2026-07-24T00:00:00Z",
        "ended_at": "2026-07-24T00:00:11Z",
    }
    report = {
        "schema": "devlog.game_capture_report",
        "version": 1,
        "status_endpoint": "game.capture_scene.status",
        "describe_endpoint": "game.capture_scene.describe",
        "action_endpoint": "game.capture_scene.trigger_action",
        "scene_id": actual_state or request["state_id"],
        "action_id": request["action_id"],
        "build_id": request["build_id"],
        "monotonic_started_seconds": 100.0,
        "monotonic_ended_seconds": 100.0 + game_elapsed_seconds,
        "descriptor": {
            "apiVersion": 1,
            "gameId": "game-not-a-trolley-problem",
            "scene": {
                "actions": [{
                    "arguments": [],
                    "description": "Run the requested gameplay action.",
                    "id": request["action_id"],
                }],
                "capabilities": {
                    "hidesGameUi": True,
                    "semanticHash": True,
                },
                "contractVersion": 1,
                "id": actual_state or request["state_id"],
                "parameters": [],
                "title": "Day 5 station",
            },
        },
        "before": {
            "activeScene": actual_state or request["state_id"],
            "apiVersion": 1,
            "contractVersion": 1,
            "gameId": "game-not-a-trolley-problem",
            "generation": 7,
            "ready": True,
            "semanticHash": "00000001",
            "tick": 10,
        },
        "action_result": {
            "activeScene": actual_state or request["state_id"],
            "apiVersion": 1,
            "contractVersion": 1,
            "gameId": "game-not-a-trolley-problem",
            "generation": 7,
            "ready": True,
            "semanticHash": "00000002",
            "tick": 11,
        },
        "after": {
            "activeScene": actual_state or request["state_id"],
            "apiVersion": 1,
            "contractVersion": 1,
            "gameId": "game-not-a-trolley-problem",
            "generation": 7,
            "ready": True,
            "semanticHash": "00000003",
            "tick": 670,
        },
    }
    report_path = captured.with_suffix(captured.suffix + ".game.json")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    report_sha = hashlib.sha256(report_path.read_bytes()).hexdigest()
    metadata["game_report_path"] = report_path.relative_to(production).as_posix()
    metadata["game_report_sha256"] = report_sha
    metadata_path = captured.with_suffix(captured.suffix + ".capture.json")
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    metadata_sha = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    result_path = production / "data" / "plan" / "capture_results.json"
    result_path.write_text(json.dumps({
        "version": 2,
        "production_id": "2026_07_18_reel_01",
        "results": [{
            "request_id": request["id"],
            "status": "captured",
            "path": request["target"],
            "sha256": artifact_sha,
            "capture_method": "realtime_window",
            "state_id": request["state_id"],
            "build_id": request["build_id"],
            "recorder_metadata_path": metadata_path.relative_to(production).as_posix(),
            "recorder_metadata_sha256": metadata_sha,
            "game_report_path": report_path.relative_to(production).as_posix(),
            "game_report_sha256": report_sha,
        }],
    }), encoding="utf-8")
    return result_path


def _fake_gameplay_catalog(production: Path):
    from dlstudio.services.autopilot import AssetCatalog, AssetRecord

    return AssetCatalog(
        root=str(production),
        assets=[AssetRecord(
            path="data/footage/day5_station.mp4",
            sha256=hashlib.sha256(b"fake-video-for-contract-test").hexdigest(),
            size=len(b"fake-video-for-contract-test"),
            modified_at="2026-07-24T00:00:11Z",
            kind="video",
            width=192,
            height=108,
            duration=11,
            fps=30,
            orientation="landscape",
            intended_for="landscape",
            provenance="game_capture",
            source_role="real_product",
        )],
    )


def test_capture_ingest_v2_validates_hash_bound_recorder_metadata(
    tmp_path,
    monkeypatch,
):
    production = _production(tmp_path)
    result_path = _prepare_v2_gameplay_capture(production)
    monkeypatch.setattr(
        "dlstudio.services.capture_batch.build_asset_catalog",
        lambda root: _fake_gameplay_catalog(production),
    )
    from dlstudio.ir import CheckReport

    monkeypatch.setattr(
        "dlstudio.services.capture_batch.analyze_rendered_video",
        lambda *args, **kwargs: CheckReport(),
    )

    from dlstudio.services.capture_batch import ingest_capture_results

    receipt = ingest_capture_results(production, result_path)

    assert receipt.ingested == ("day5_station",)
    saved = json.loads(receipt.receipt_path.read_text(encoding="utf-8"))
    assert saved["version"] == 2
    assert saved["validated"]["day5_station"]["state_id"] == "day5.station.new_visual"
    assert saved["validated"]["day5_station"]["capture_method"] == "realtime_window"
    assert saved["validated"]["day5_station"]["actual_fps"] == 30
    assert saved["validated"]["day5_station"]["actual_duration"] == 11
    assert saved["validated"]["day5_station"]["measured_playback_rate"] == 1.0
    registry = json.loads(receipt.registry_path.read_text(encoding="utf-8"))
    assert registry["assets"][0]["asset_id"] == "capture:day5_station"
    assert registry["assets"][0]["status"] == "validated"
    assert registry["assets"][0]["game_report_sha256"]


def test_capture_ingest_v2_blocks_stepped_cadence_before_registry(
    tmp_path,
    monkeypatch,
):
    production = _production(tmp_path)
    result_path = _prepare_v2_gameplay_capture(production)
    monkeypatch.setattr(
        "dlstudio.services.capture_batch.build_asset_catalog",
        lambda root: _fake_gameplay_catalog(production),
    )
    from dlstudio.ir import CheckIssue, CheckReport

    monkeypatch.setattr(
        "dlstudio.services.capture_batch.analyze_rendered_video",
        lambda *args, **kwargs: CheckReport(issues=[CheckIssue(
            severity="error",
            code="VQ-CADENCE",
            message="alternating duplicate frames",
            where="capture:day5_station",
        )]),
    )

    from dlstudio.services.capture_batch import CaptureBatchError, ingest_capture_results

    with pytest.raises(CaptureBatchError, match="VQ-CADENCE"):
        ingest_capture_results(production, result_path)

    assert not (production / "data" / "assets" / "registry.json").exists()


def test_capture_ingest_v2_blocks_retimed_gameplay_before_registry(
    tmp_path,
    monkeypatch,
):
    production = _production(tmp_path)
    result_path = _prepare_v2_gameplay_capture(
        production,
        game_elapsed_seconds=110.0,
    )
    monkeypatch.setattr(
        "dlstudio.services.capture_batch.build_asset_catalog",
        lambda root: _fake_gameplay_catalog(production),
    )

    from dlstudio.services.capture_batch import CaptureBatchError, ingest_capture_results

    with pytest.raises(
        CaptureBatchError,
        match="media duration differs from real-time capture",
    ):
        ingest_capture_results(production, result_path)

    assert not (production / "data" / "assets" / "registry.json").exists()


def test_capture_ingest_v2_rejects_tampered_game_report_before_catalog(
    tmp_path,
    monkeypatch,
):
    production = _production(tmp_path)
    result_path = _prepare_v2_gameplay_capture(production)
    results = json.loads(result_path.read_text(encoding="utf-8"))
    report_path = production / results["results"][0]["game_report_path"]
    report_path.write_text('{"tampered":true}', encoding="utf-8")
    catalog_called = False

    def unexpected_catalog(root):
        nonlocal catalog_called
        catalog_called = True
        return _fake_gameplay_catalog(production)

    monkeypatch.setattr(
        "dlstudio.services.capture_batch.build_asset_catalog",
        unexpected_catalog,
    )

    from dlstudio.services.capture_batch import CaptureBatchError, ingest_capture_results

    with pytest.raises(CaptureBatchError, match="game capture report hash mismatch"):
        ingest_capture_results(production, result_path)

    assert catalog_called is False


def test_capture_ingest_v2_rejects_sidecar_state_mismatch_before_catalog(
    tmp_path,
    monkeypatch,
):
    production = _production(tmp_path)
    result_path = _prepare_v2_gameplay_capture(
        production,
        actual_state="day4.station.old_visual",
    )
    catalog_called = False

    def unexpected_catalog(root):
        nonlocal catalog_called
        catalog_called = True
        return _fake_gameplay_catalog(production)

    monkeypatch.setattr(
        "dlstudio.services.capture_batch.build_asset_catalog",
        unexpected_catalog,
    )

    from dlstudio.services.capture_batch import CaptureBatchError, ingest_capture_results

    with pytest.raises(CaptureBatchError, match="recorder state_id mismatch"):
        ingest_capture_results(production, result_path)

    assert catalog_called is False


def test_capture_ingest_v2_accepts_failed_result_without_fake_artifact(
    tmp_path,
    monkeypatch,
):
    production = _production(tmp_path)
    requests = production / "data" / "plan" / "capture_requests.json"
    requests.parent.mkdir(parents=True)
    requests.write_text(json.dumps({
        "version": 2,
        "requests": [_gameplay_request_v2()],
    }), encoding="utf-8")

    from dlstudio.services.capture_batch import ingest_capture_results, prepare_capture_batch
    from dlstudio.services.autopilot import AssetCatalog

    prepare_capture_batch(production, requests)
    results = production / "data" / "plan" / "capture_results.json"
    results.write_text(json.dumps({
        "version": 2,
        "production_id": "2026_07_18_reel_01",
        "results": [{
            "request_id": "day5_station",
            "status": "failed",
            "note": "window was occluded",
        }],
    }), encoding="utf-8")
    monkeypatch.setattr(
        "dlstudio.services.capture_batch.build_asset_catalog",
        lambda root: AssetCatalog(root=str(production)),
    )

    receipt = ingest_capture_results(production, results)

    assert receipt.ingested == ()
    assert receipt.failed == ("day5_station",)


def test_capture_ingest_v2_requires_one_result_per_request(tmp_path, monkeypatch):
    production = _production(tmp_path)
    requests = production / "data" / "plan" / "capture_requests.json"
    requests.parent.mkdir(parents=True)
    requests.write_text(json.dumps({
        "version": 2,
        "requests": [_gameplay_request_v2()],
    }), encoding="utf-8")

    from dlstudio.services.capture_batch import (
        CaptureBatchError,
        ingest_capture_results,
        prepare_capture_batch,
    )
    from dlstudio.services.autopilot import AssetCatalog

    prepare_capture_batch(production, requests)
    results = production / "data" / "plan" / "capture_results.json"
    results.write_text(json.dumps({
        "version": 2,
        "production_id": "2026_07_18_reel_01",
        "results": [],
    }), encoding="utf-8")
    monkeypatch.setattr(
        "dlstudio.services.capture_batch.build_asset_catalog",
        lambda root: AssetCatalog(root=str(production)),
    )

    with pytest.raises(CaptureBatchError, match="missing capture results"):
        ingest_capture_results(production, results)


def test_capture_ingest_v2_real_ffmpeg_fixture_passes_frame_audit(tmp_path):
    ffmpeg = shutil.which("ffmpeg")
    if ffmpeg is None:
        pytest.skip("ffmpeg is required for the real capture ingest fixture")
    production = _production(tmp_path)
    result_path = _prepare_v2_gameplay_capture(production)
    artifact = production / "data" / "footage" / "day5_station.mp4"
    subprocess.run(
        [
            ffmpeg,
            "-hide_banner",
            "-loglevel",
            "error",
            "-f",
            "lavfi",
            "-i",
            "testsrc2=size=192x108:rate=30",
            "-t",
            "11",
            "-c:v",
            "libx264",
            "-preset",
            "ultrafast",
            "-pix_fmt",
            "yuv420p",
            "-y",
            str(artifact),
        ],
        check=True,
    )
    artifact_sha = hashlib.sha256(artifact.read_bytes()).hexdigest()
    metadata_path = artifact.with_suffix(".mp4.capture.json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    metadata["sha256"] = artifact_sha
    metadata_path.write_text(json.dumps(metadata), encoding="utf-8")
    metadata_sha = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    results = json.loads(result_path.read_text(encoding="utf-8"))
    results["results"][0]["sha256"] = artifact_sha
    results["results"][0]["recorder_metadata_sha256"] = metadata_sha
    result_path.write_text(json.dumps(results), encoding="utf-8")

    from dlstudio.services.capture_batch import ingest_capture_results

    receipt = ingest_capture_results(production, result_path)

    saved = json.loads(receipt.receipt_path.read_text(encoding="utf-8"))
    assert saved["validated"]["day5_station"]["frame_audit"]["verdict"] == "pass"
    assert saved["validated"]["day5_station"]["actual_fps"] == 30
