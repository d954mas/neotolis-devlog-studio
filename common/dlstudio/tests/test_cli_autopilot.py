from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from dlstudio import cli
from dlstudio.ir import CheckIssue, CheckReport


def _parse(argv: list[str]) -> argparse.Namespace:
    from dlstudio.cli import autopilot

    parser = argparse.ArgumentParser(prog="dl2")
    sub = parser.add_subparsers(dest="command", required=True)
    autopilot.add_subparsers(sub)
    return parser.parse_args(argv)


def test_parser_exposes_inventory_preflight_and_storyboard_commands():
    from dlstudio.cli import autopilot

    inventory = _parse(["inventory", "product:2026_07_18_reel_01"])
    assert inventory.func is autopilot.cmd_inventory
    assert _parse(["preflight", "production/path"]).func is autopilot.cmd_preflight
    longform = _parse(["longform-check", "product:2026_07_18_devlog_01"])
    assert longform.func is autopilot.cmd_longform_check
    assert longform.strict is False
    assert _parse([
        "longform-check",
        "product:2026_07_18_devlog_01",
        "--strict",
    ]).strict is True
    storyboard = _parse(["storyboard", "some.edit"])
    assert storyboard.func is autopilot.cmd_storyboard
    assert storyboard.jobs == 1
    assert storyboard.keyframes == 8
    run = _parse(["autopilot-run", "some.edit"])
    assert run.func is autopilot.cmd_autopilot_run
    assert run.jobs == 4
    pack = _parse(["review-pack", "some.edit"])
    assert pack.func is autopilot.cmd_review_pack
    assert pack.frames == 16
    approve = _parse([
        "asset-approve",
        "some.edit",
        "capture:day5_station",
        "--sha",
        "a" * 64,
        "--revision",
        "3",
        "--validation-sha",
        "b" * 64,
    ])
    assert approve.func is autopilot.cmd_asset_approve
    assert approve.revision == 3
    assert approve.validation_sha == "b" * 64
    assert approve.approved_by == "author"
    flow = _parse([
        "capture-flow",
        "some.edit",
        "day5_station",
        "--ingest",
        "data/plan/capture_results.json",
    ])
    assert flow.func is autopilot.cmd_capture_flow
    assert flow.request_id == "day5_station"
    assert flow.ingest == "data/plan/capture_results.json"


def test_autopilot_json_write_is_atomic_on_replace_failure(tmp_path, monkeypatch):
    from dlstudio.cli import autopilot

    target = tmp_path / "data" / "review" / "autopilot_run.json"
    target.parent.mkdir(parents=True)
    target.write_text('{"run_id":"old"}\n', encoding="utf-8")

    def fail_replace(_source, _target):
        raise OSError("simulated interruption")

    monkeypatch.setattr(autopilot.os, "replace", fail_replace)
    with pytest.raises(OSError, match="simulated interruption"):
        autopilot._write_json(target, {"run_id": "new"})

    assert json.loads(target.read_text(encoding="utf-8"))["run_id"] == "old"
    assert not list(target.parent.glob(".autopilot_run.json.*.tmp"))


def test_autopilot_run_lock_rejects_concurrent_writer(tmp_path):
    from dlstudio.cli import autopilot

    with autopilot._exclusive_run_lock(tmp_path):
        with pytest.raises(cli.CliError, match="another autopilot-run"):
            with autopilot._exclusive_run_lock(tmp_path):
                pass


def test_capture_flow_prepares_once_and_names_the_external_recording_boundary(
    tmp_path,
    monkeypatch,
    capsys,
):
    from dlstudio.cli import autopilot
    from dlstudio.services import asset_registry, capture_batch

    production = tmp_path / "production"
    requests = production / "data" / "plan" / "capture_requests.json"
    requests.parent.mkdir(parents=True)
    requests.write_text('{"version":2,"requests":[]}', encoding="utf-8")
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, "product:production"),
    )

    def fake_prepare(root, requests_path, *, out_path, request_ids=None):
        assert request_ids == {"day5_station"}
        Path(out_path).write_text(json.dumps({
            "version": 2,
            "requests_sha256": __import__("hashlib").sha256(
                requests.read_bytes()
            ).hexdigest(),
            "requests": [{"id": "day5_station"}],
        }), encoding="utf-8")
        return SimpleNamespace(requests=[SimpleNamespace(id="day5_station")])

    monkeypatch.setattr(capture_batch, "prepare_capture_batch", fake_prepare)
    monkeypatch.setattr(
        capture_batch,
        "capture_request_sha256",
        lambda path, ids: "a" * 64,
    )
    monkeypatch.setattr(
        asset_registry,
        "load_asset_registry",
        lambda root: SimpleNamespace(assets=[]),
    )

    assert autopilot.cmd_capture_flow(_parse([
        "capture-flow", "product:production", "day5_station",
    ])) == 0

    output = capsys.readouterr().out
    assert "$devlog-record-media" in output
    assert "data/plan/capture_results/day5_station.json" in output


def test_capture_flow_writes_identity_complete_gameplay_snippet(
    tmp_path,
    monkeypatch,
):
    from dlstudio.cli import autopilot
    from dlstudio.services import asset_registry, capture_batch

    production = tmp_path / "production"
    batch = (
        production
        / "data"
        / "plan"
        / "capture_batches"
        / "day5_station.json"
    )
    batch.parent.mkdir(parents=True)
    requests = production / "data" / "plan" / "capture_requests.json"
    requests.write_text(
        '{"version":2,"requests":[{"id":"day5_station"}]}',
        encoding="utf-8",
    )
    batch.write_text(json.dumps({
        "version": 2,
        "requests_sha256": "a" * 64,
        "requests": [{"id": "day5_station"}],
    }), encoding="utf-8")
    monkeypatch.setattr(
        capture_batch,
        "capture_request_sha256",
        lambda path, ids: "a" * 64,
    )
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, "product:production"),
    )
    asset = SimpleNamespace(
        asset_id="capture:day5_station",
        status="approved",
        artifact_path="data/footage/day5_station.mp4",
        artifact_sha256="a" * 64,
        validation_sha256="b" * 64,
        revision=3,
        editorial_role="gameplay",
        state_id="day5.station.new_visual",
        build_id="exe-sha256:" + "c" * 64,
        action_id="station_queue_and_tram_pass",
        head_handle_seconds=5.0,
        presentation={
            "output_width": 1920,
            "output_height": 1080,
            "fit": "contain",
        },
    )
    monkeypatch.setattr(
        asset_registry,
        "load_asset_registry",
        lambda root: SimpleNamespace(assets=[asset]),
    )
    monkeypatch.setattr(
        asset_registry,
        "resolve_approved_asset",
        lambda root, asset_id: production / asset.artifact_path,
    )

    assert autopilot.cmd_capture_flow(_parse([
        "capture-flow", "product:production", "day5_station",
    ])) == 0

    snippet = (
        production
        / "data"
        / "plan"
        / "capture_snippets"
        / "day5_station.py"
    ).read_text(encoding="utf-8")
    assert 'asset_id="capture:day5_station"' in snippet
    assert 'expected_state_id="day5.station.new_visual"' in snippet
    assert 'expected_action_id="station_queue_and_tram_pass"' in snippet
    assert "offset=5.000" in snippet
    assert 'fit="contain"' in snippet
    assert "loop=" not in snippet


def test_capture_flow_refuses_stale_approved_take(tmp_path, monkeypatch):
    from dlstudio.cli import CliError, autopilot
    from dlstudio.services import asset_registry, capture_batch

    production = tmp_path / "production"
    batch = (
        production / "data" / "plan" / "capture_batches" / "day5_station.json"
    )
    batch.parent.mkdir(parents=True)
    requests = production / "data" / "plan" / "capture_requests.json"
    requests.write_text(
        '{"version":2,"requests":[{"id":"day5_station"}]}',
        encoding="utf-8",
    )
    batch.write_text(json.dumps({
        "version": 2,
        "requests_sha256": "a" * 64,
        "requests": [{"id": "day5_station"}],
    }), encoding="utf-8")
    monkeypatch.setattr(
        capture_batch,
        "capture_request_sha256",
        lambda path, ids: "a" * 64,
    )
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, "product:production"),
    )
    asset = SimpleNamespace(
        asset_id="capture:day5_station",
        status="approved",
        artifact_path="data/footage/day5_station.mp4",
        artifact_sha256="a" * 64,
        validation_sha256="b" * 64,
        revision=3,
        editorial_role="gameplay",
    )
    monkeypatch.setattr(
        asset_registry,
        "load_asset_registry",
        lambda root: SimpleNamespace(assets=[asset]),
    )

    def stale(*args, **kwargs):
        raise asset_registry.AssetRegistryError(
            "asset capture ingest proof is stale"
        )

    monkeypatch.setattr(asset_registry, "resolve_approved_asset", stale)

    with pytest.raises(CliError, match="re-record and ingest"):
        autopilot.cmd_capture_flow(_parse([
            "capture-flow", "product:production", "day5_station",
        ]))


def test_autopilot_run_stops_at_checkpoint_and_resumes_to_exact_review(
    tmp_path, monkeypatch
):
    from dlstudio.cli import autopilot

    production = tmp_path / "production"
    production.mkdir()
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, "product:production"),
    )
    calls = []

    def stage(name):
        def run(args):
            calls.append(name)
            return 0
        return run

    monkeypatch.setattr(autopilot, "cmd_inventory", stage("inventory"))
    monkeypatch.setattr(autopilot, "cmd_preflight", stage("preflight"))
    monkeypatch.setattr(autopilot, "cmd_storyboard", stage("storyboard"))
    monkeypatch.setattr(autopilot, "cmd_review_pack", stage("review_pack"))

    assert autopilot.cmd_autopilot_run(
        _parse(["autopilot-run", "product:production"])
    ) == 0
    state_path = production / "data/review/autopilot_run.json"
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "awaiting_checkpoint"
    assert calls == ["inventory", "preflight", "storyboard", "review_pack"]

    import dlstudio.cli as cli_root
    from dlstudio.services import autopilot_checkpoint

    monkeypatch.setattr(
        autopilot_checkpoint, "require_current_approval", lambda root: {}
    )
    monkeypatch.setattr(cli_root, "cmd_final", stage("final"))
    assert autopilot.cmd_autopilot_run(
        _parse([
            "autopilot-run", "product:production", "--resume",
            "--human-minutes", "7.5",
        ])
    ) == 0
    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "awaiting_exact_review"
    assert state["human_active_ms"] == 450000
    assert calls[-4:] == ["preflight", "final", "preflight", "review_pack"]


def test_autopilot_resume_refuses_final_without_current_author_approval(
    tmp_path, monkeypatch
):
    from dlstudio.cli import CliError, autopilot
    import dlstudio.cli as cli_root

    production = tmp_path / "production"
    state_path = production / "data/review/autopilot_run.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "version": 1,
        "run_id": "run_20260718_unapproved",
        "production": "product:production",
        "status": "awaiting_checkpoint",
        "phase": "author_checkpoint",
        "started_at": "2026-07-18T00:00:00Z",
        "updated_at": "2026-07-18T00:00:00Z",
        "human_active_ms": 0,
        "stages": [],
        "next_action": None,
    }), encoding="utf-8")
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, "product:production"),
    )
    monkeypatch.setattr(
        cli_root,
        "cmd_final",
        lambda args: pytest.fail("final render must not run without approval"),
    )

    with pytest.raises(CliError, match="author checkpoint is not current"):
        autopilot.cmd_autopilot_run(
            _parse(["autopilot-run", "product:production", "--resume"])
        )

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "awaiting_checkpoint"
    assert state["phase"] == "author_checkpoint"


def test_autopilot_third_invocation_stops_at_explicit_package_checkpoint(
    tmp_path, monkeypatch, capsys
):
    from dlstudio.cli import autopilot

    production = tmp_path / "production"
    state_path = production / "data/review/autopilot_run.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "version": 1,
        "run_id": "run_20260718_package",
        "production": "product:production",
        "status": "awaiting_exact_review",
        "phase": "exact_review",
        "started_at": "2026-07-18T00:00:00Z",
        "updated_at": "2026-07-18T00:00:00Z",
        "human_active_ms": 0,
        "stages": [],
        "next_action": None,
    }), encoding="utf-8")
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, "product:production"),
    )
    monkeypatch.setattr(autopilot, "_require_current_exact_review", lambda root: None)

    assert autopilot.cmd_autopilot_run(
        _parse(["autopilot-run", "product:production", "--resume"])
    ) == 0

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "awaiting_package"
    assert state["phase"] == "package"
    assert "data/publish/publish.json" in state["next_action"]
    assert "awaiting publish package" in capsys.readouterr().out


def test_autopilot_package_resume_runs_evidence_and_delivery(
    tmp_path, monkeypatch
):
    from dlstudio.cli import autopilot
    from dlstudio.cli import delivery

    production = tmp_path / "production"
    state_path = production / "data/review/autopilot_run.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "version": 1,
        "run_id": "run_20260718_delivery",
        "production": "product:production",
        "status": "awaiting_package",
        "phase": "package",
        "started_at": "2026-07-18T00:00:00Z",
        "updated_at": "2026-07-18T00:00:00Z",
        "human_active_ms": 0,
        "stages": [],
        "next_action": "create package",
    }), encoding="utf-8")
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, "product:production"),
    )
    calls = []
    delivery_args = []
    monkeypatch.setattr(
        delivery, "cmd_publish_evidence", lambda args: calls.append("evidence") or 0
    )
    monkeypatch.setattr(
        delivery,
        "cmd_deliver",
        lambda args: delivery_args.append(args) or calls.append("delivery") or 0,
    )

    assert autopilot.cmd_autopilot_run(
        _parse(["autopilot-run", "product:production", "--resume"])
    ) == 0

    state = json.loads(state_path.read_text(encoding="utf-8"))
    assert state["status"] == "completed"
    assert calls == ["evidence", "delivery"]
    assert delivery_args[0].overwrite is True


def test_autopilot_resume_retries_failed_finalize_without_rebuilding_storyboard(
    tmp_path, monkeypatch
):
    from dlstudio.cli import autopilot
    import dlstudio.cli as cli_root

    production = tmp_path / "production"
    state_path = production / "data/review/autopilot_run.json"
    state_path.parent.mkdir(parents=True)
    state_path.write_text(json.dumps({
        "version": 1,
        "run_id": "run_20260718_retry",
        "production": "product:production",
        "status": "awaiting_checkpoint",
        "phase": "author_checkpoint",
        "started_at": "2026-07-18T00:00:00Z",
        "updated_at": "2026-07-18T00:00:00Z",
        "human_active_ms": 0,
        "stages": [],
        "next_action": None,
    }), encoding="utf-8")
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, "product:production"),
    )
    from dlstudio.services import autopilot_checkpoint
    monkeypatch.setattr(
        autopilot_checkpoint, "require_current_approval", lambda root: {}
    )
    calls = []
    failures = iter((1, 0))
    monkeypatch.setattr(autopilot, "cmd_preflight", lambda args: calls.append("preflight") or 0)
    monkeypatch.setattr(autopilot, "cmd_review_pack", lambda args: calls.append("review_pack") or 0)
    monkeypatch.setattr(
        cli_root, "cmd_final",
        lambda args: calls.append("final") or next(failures),
    )

    resume = _parse(["autopilot-run", "product:production", "--resume"])
    assert autopilot.cmd_autopilot_run(resume) == 1
    blocked = json.loads(state_path.read_text(encoding="utf-8"))
    assert blocked["status"] == "blocked"
    assert blocked["phase"] == "finalize"

    assert autopilot.cmd_autopilot_run(resume) == 0
    completed = json.loads(state_path.read_text(encoding="utf-8"))
    assert completed["status"] == "awaiting_exact_review"
    assert calls == ["preflight", "final", "preflight", "final", "preflight", "review_pack"]


def test_inventory_loads_edit_and_writes_production_catalog(tmp_path, monkeypatch):
    from dlstudio.cli import autopilot
    from dlstudio.services import autopilot as service

    production = tmp_path / "production"
    production.mkdir()
    calls: dict[str, object] = {}

    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, str(production)),
    )

    def fake_build(root, *, out_path):
        calls["root"] = Path(root)
        calls["out"] = Path(out_path)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text('{"version": 1, "assets": []}\n', encoding="utf-8")
        return SimpleNamespace(assets=[])

    monkeypatch.setattr(service, "build_asset_catalog", fake_build)

    assert autopilot.cmd_inventory(_parse(["inventory", "production/path"])) == 0
    assert calls == {
        "root": production,
        "out": production / "data" / "assets" / "catalog.json",
    }
    assert (production / "data" / "assets" / "catalog.json").is_file()


def test_preflight_combines_ir_and_shot_manifest_issues(tmp_path, monkeypatch):
    from dlstudio.cli import autopilot
    from dlstudio.services import autopilot as service

    production = tmp_path / "production"
    (production / "data" / "plan").mkdir(parents=True)
    (production / "data" / "assets").mkdir(parents=True)
    (production / "data" / "plan" / "shot_manifest.json").write_text(
        json.dumps({"shots": [{"id": "s01", "src": "data/images/a.png"}]}),
        encoding="utf-8",
    )
    (production / "data" / "plan" / "story_contract.json").write_text(
        json.dumps({
            "version": 1,
            "standalone_story": {
                "premise": "A complete premise",
                "causal_turn": "A causal turn",
                "payoff": "A resolved payoff",
            },
            "allow_editorial_labels": [],
        }),
        encoding="utf-8",
    )
    (production / "data" / "assets" / "catalog.json").write_text(
        json.dumps({"version": 1, "root": str(production), "assets": []}),
        encoding="utf-8",
    )
    timeline = SimpleNamespace(design=SimpleNamespace(resolution=(1080, 1920)))

    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, str(production)),
    )
    import dlstudio.compile as compile_mod
    import dlstudio.check as check_mod

    monkeypatch.setattr(compile_mod, "build_timeline", lambda edit: timeline)
    monkeypatch.setattr(
        check_mod,
        "run_checks",
        lambda value, **kwargs: CheckReport(
            issues=[
                CheckIssue(
                    severity="warn",
                    code="VQ-SYNC",
                    message="mechanical warning",
                    where="b01",
                )
            ]
        ),
    )

    def fake_validate(shots, catalog, *, orientation, final):
        assert shots == [{"id": "s01", "src": "data/images/a.png"}]
        assert orientation == "vertical"
        assert final is False
        return CheckReport(
            issues=[
                CheckIssue(
                    severity="error",
                    code="VQ-SOURCE",
                    message="missing source",
                    where="s01",
                )
            ]
        )

    monkeypatch.setattr(service, "validate_shot_manifest", fake_validate)

    assert autopilot.cmd_preflight(_parse(["preflight", "production/path"])) == 1
    payload = json.loads(
        (production / "data" / "review" / "preflight.json").read_text(encoding="utf-8")
    )
    assert payload["ok"] is False
    assert payload["errors"] == 1
    assert payload["warnings"] == 2
    assert [issue["code"] for issue in payload["issues"]] == [
        "VQ-SYNC",
        "VQ-SOURCE",
        "VQ-FRAME",
    ]
    assert payload["inputs"] == {
        "shot_manifest": "data/plan/shot_manifest.json",
        "shot_manifest_sha256": __import__(
            "dlstudio.services.autopilot_checkpoint",
            fromlist=["preflight_manifest_sha256"],
        ).preflight_manifest_sha256(
            production / "data" / "plan" / "shot_manifest.json"
        ),
        "asset_catalog": "data/assets/catalog.json",
        "asset_catalog_sha256": hashlib.sha256(
            (production / "data" / "assets" / "catalog.json").read_bytes()
        ).hexdigest(),
        "script_approval": None,
        "creator_profile": None,
        "render_artifact": None,
        "render_artifact_sha256": None,
        "compiled_ir_sha256": None,
    }


def test_preflight_without_optional_shot_files_reports_ir_only(tmp_path, monkeypatch):
    from dlstudio.cli import autopilot

    production = tmp_path / "production"
    production.mkdir()
    timeline = SimpleNamespace(design=SimpleNamespace(resolution=(1920, 1080)))
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, str(production)),
    )
    import dlstudio.compile as compile_mod
    import dlstudio.check as check_mod

    monkeypatch.setattr(compile_mod, "build_timeline", lambda edit: timeline)
    monkeypatch.setattr(
        check_mod,
        "run_checks",
        lambda value, **kwargs: CheckReport(),
    )

    assert autopilot.cmd_preflight(_parse(["preflight", "some.edit"])) == 0
    payload = json.loads(
        (production / "data" / "review" / "preflight.json").read_text(encoding="utf-8")
    )
    assert payload["ok"] is True
    assert payload["issues"] == []
    assert payload["inputs"] == {
        "shot_manifest": None,
        "shot_manifest_sha256": None,
        "asset_catalog": None,
        "asset_catalog_sha256": None,
        "script_approval": None,
        "creator_profile": None,
        "render_artifact": None,
        "render_artifact_sha256": None,
        "compiled_ir_sha256": None,
    }


def test_preflight_includes_longform_gate_for_product_devlog(tmp_path, monkeypatch):
    from dlstudio.cli import autopilot
    from dlstudio.services import longform_preflight

    production = tmp_path / "product" / "devlogs" / "2026_07_26_devlog_01"
    plan = production / "data" / "plan"
    plan.mkdir(parents=True)
    (production / "production.toml").write_text("kind = 'devlog'\n", encoding="utf-8")
    story_path = plan / "story_map.json"
    story_path.write_text('{"schema":"devlog.longform_story_map/v1"}', encoding="utf-8")
    timeline = SimpleNamespace(design=SimpleNamespace(resolution=(1920, 1080)))
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, str(production)),
    )

    import dlstudio.check as check_mod
    import dlstudio.compile as compile_mod
    import dlstudio.production as production_mod
    import dlstudio.cli.telemetry as telemetry_mod
    import dlstudio.services.editorial_preflight as editorial_mod
    import dlstudio.services.visual_preflight as visual_mod

    monkeypatch.setattr(compile_mod, "build_timeline", lambda edit: timeline)
    monkeypatch.setattr(check_mod, "run_checks", lambda value, **kwargs: CheckReport())
    monkeypatch.setattr(
        production_mod,
        "load_production_manifest",
        lambda root: SimpleNamespace(kind="devlog"),
    )
    monkeypatch.setattr(
        telemetry_mod,
        "record_automatic_stage",
        lambda *args, **kwargs: None,
    )
    monkeypatch.setattr(
        visual_mod,
        "run_visual_preflight",
        lambda *args, **kwargs: CheckReport(),
    )
    monkeypatch.setattr(
        editorial_mod,
        "run_editorial_preflight",
        lambda *args, **kwargs: CheckReport(),
    )
    monkeypatch.setattr(
        longform_preflight,
        "run_longform_preflight",
        lambda root, *, strict: CheckReport(issues=[
            CheckIssue(
                severity="error",
                code="VQ-LONGFORM-PROOF",
                message="arc has no payoff",
                where="arc_01",
            )
        ]),
    )

    assert autopilot.cmd_preflight(_parse(["preflight", str(production)])) == 1

    payload = json.loads(
        (production / "data" / "review" / "preflight.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["issues"][0]["code"] == "VQ-LONGFORM-PROOF"
    assert payload["inputs"]["story_map"] == "data/plan/story_map.json"
    assert payload["inputs"]["story_map_sha256"] == hashlib.sha256(
        story_path.read_bytes()
    ).hexdigest()


def test_longform_check_persists_hash_bound_report(tmp_path, monkeypatch):
    from dlstudio.cli import autopilot
    from dlstudio.services import longform_preflight

    production = tmp_path / "product" / "devlogs" / "2026_07_26_devlog_01"
    plan = production / "data" / "plan"
    plan.mkdir(parents=True)
    story_path = plan / "story_map.json"
    shot_path = plan / "shot_manifest.json"
    story_path.write_text("{}", encoding="utf-8")
    shot_path.write_text('{"shots":[]}', encoding="utf-8")
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (SimpleNamespace(), production, "product:production"),
    )

    import dlstudio.production as production_mod

    monkeypatch.setattr(
        production_mod,
        "load_production_manifest",
        lambda root: SimpleNamespace(kind="devlog"),
    )
    monkeypatch.setattr(
        longform_preflight,
        "run_longform_preflight",
        lambda root, *, strict: CheckReport(),
    )

    assert autopilot.cmd_longform_check(
        _parse(["longform-check", "product:production", "--strict"])
    ) == 0

    payload = json.loads(
        (production / "data" / "review" / "longform_preflight.json").read_text(
            encoding="utf-8"
        )
    )
    assert payload["strict"] is True
    assert payload["ok"] is True
    assert payload["inputs"]["story_map_sha256"] == hashlib.sha256(
        story_path.read_bytes()
    ).hexdigest()
    assert payload["inputs"]["shot_manifest_sha256"] == hashlib.sha256(
        shot_path.read_bytes()
    ).hexdigest()


def test_script_vo_preflight_requires_hash_bound_approval(tmp_path):
    from dlstudio.cli import autopilot

    production = tmp_path / "product" / "reels" / "2026_07_18_reel_01"
    production.mkdir(parents=True)
    edit = SimpleNamespace(
        name="reel-01",
        order=["b01"],
        beats={
            "b01": SimpleNamespace(
                vo="Я начал новую игру.",
                audio="data/audio/voice.wav",
                words="data/scratch/words.json",
            )
        },
    )

    issues, inputs = autopilot._script_vo_issues(edit, production)

    assert [issue.code for issue in issues] == ["VQ-SCRIPT-APPROVAL"]
    assert inputs == {"script_approval": None, "creator_profile": None}


def test_storyboard_requires_shot_manifest_before_preview(tmp_path, monkeypatch):
    from dlstudio.cli import autopilot
    from dlstudio.cli import preview

    production = tmp_path / "production"
    production.mkdir()
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (
            SimpleNamespace(output="data/finalize/draft.mp4"),
            production,
            str(production),
        ),
    )
    monkeypatch.setattr(
        preview,
        "cmd_preview",
        lambda args: pytest.fail("preview must not run"),
    )

    with pytest.raises(cli.CliError, match="shot manifest is required"):
        autopilot.cmd_storyboard(_parse(["storyboard", "production/path"]))


def test_storyboard_uses_540p_preview_and_writes_boundary_summary(tmp_path, monkeypatch):
    from dlstudio.cli import autopilot
    from dlstudio.cli import preview

    production = tmp_path / "production"
    (production / "data" / "plan").mkdir(parents=True)
    shots = [
        {"id": "s01", "src": "data/footage/a.mp4", "t0": 0.0, "t1": 2.5},
        {"id": "s02", "src": "data/images/b.png", "t0": 2.5, "t1": 5.0},
    ]
    (production / "data" / "plan" / "shot_manifest.json").write_text(
        json.dumps(shots), encoding="utf-8"
    )
    edit = SimpleNamespace(output="data/finalize/draft.mp4")
    monkeypatch.setattr(
        autopilot,
        "_load_target",
        lambda ref: (edit, production, str(production.resolve())),
    )
    calls: dict[str, object] = {}

    def fake_preview(args):
        calls.update(vars(args))
        sheet = production / "data" / "review" / "contact_sheet.jpg"
        sheet.parent.mkdir(parents=True, exist_ok=True)
        sheet.write_bytes(b"jpg")
        return 0

    monkeypatch.setattr(preview, "cmd_preview", fake_preview)

    args = _parse(["storyboard", "production/path", "-j", "3", "--keyframes", "4"])
    assert autopilot.cmd_storyboard(args) == 0
    assert calls["edit"] == str(production.resolve())
    assert calls["width"] == "540p"
    assert calls["quality"] == "draft"
    assert calls["jobs"] == 3
    assert calls["keyframes"] == 4

    summary = json.loads(
        (production / "data" / "review" / "storyboard_boundaries.json").read_text(
            encoding="utf-8"
        )
    )
    assert summary["version"] == 1
    assert summary["preview"] == "data/finalize/draft.mp4"
    assert summary["contact_sheet"] == "data/review/contact_sheet.jpg"
    assert summary["boundaries"] == shots
