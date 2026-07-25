from __future__ import annotations

import json


def _write_inputs(root, *, blocker: bool = False):
    plan = root / "data" / "plan"
    assets = root / "data" / "assets"
    review = root / "data" / "review"
    plan.mkdir(parents=True)
    assets.mkdir(parents=True)
    review.mkdir(parents=True)
    (plan / "shot_manifest.json").write_text(json.dumps({
        "version": 1,
        "shots": [{
            "id": "b01_s01",
            "vo_thesis": "Я начал игру заново в 3D",
            "src": "data/footage/game.mp4",
            "source_role": "real_product",
            "t0": 1.0,
            "t1": 4.5,
            "quality_flags": ["manual-review"],
            "proposed_fix": "Keep the real capture",
            "approved": False,
            "untouched": {"meaning": "locked"},
        }],
    }, ensure_ascii=False), encoding="utf-8")
    (assets / "catalog.json").write_text(json.dumps({
        "version": 1,
        "assets": [{
            "path": "data/footage/game.mp4",
            "provenance": "game_capture",
            "source_role": "real_product",
            "quality_flags": ["portrait-native"],
        }],
    }), encoding="utf-8")
    issues = ([{
        "severity": "error",
        "code": "VQ-SOURCE",
        "message": "capture is stale",
        "where": "b01_s01",
    }] if blocker else [{
        "severity": "warn",
        "code": "VQ-PACE",
        "message": "check pacing",
        "where": "b01_s01",
    }])
    (review / "preflight.json").write_text(json.dumps({
        "wall_time": {"budget_minutes": 60, "elapsed_minutes": 17.5, "stage": "checkpoint"},
        "issues": issues,
    }), encoding="utf-8")
    return plan / "shot_manifest.json"


def test_load_checkpoint_combines_thesis_provenance_duration_flags_and_budget(tmp_path):
    from dlstudio.services.autopilot_checkpoint import load_checkpoint

    _write_inputs(tmp_path)
    data = load_checkpoint(tmp_path)

    assert data["wall_time"] == {
        "budget_minutes": 60.0,
        "elapsed_minutes": 17.5,
        "remaining_minutes": 42.5,
        "stage": "checkpoint",
    }
    assert data["blockers"] == []
    row = data["rows"][0]
    assert row["vo_thesis"] == "Я начал игру заново в 3D"
    assert row["shot"]["src"] == "data/footage/game.mp4"
    assert row["shot"]["provenance"] == "game_capture"
    assert row["duration_seconds"] == 3.5
    assert row["quality_flags"] == ["VQ-PACE", "manual-review", "portrait-native"]
    assert row["proposed_fix"] == "Keep the real capture"
    assert data["can_approve_all"] is True


def test_approve_all_only_changes_approved_flags_and_writes_audit(tmp_path):
    from dlstudio.services.autopilot_checkpoint import approve_all

    manifest_path = _write_inputs(tmp_path)
    before = json.loads(manifest_path.read_text(encoding="utf-8"))

    result = approve_all(tmp_path, approved_by="author")

    after = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["approved_count"] == 1
    assert after["shots"][0]["approved"] is True
    expected = before
    expected["shots"][0]["approved"] = True
    assert after == expected
    audit = (tmp_path / "data" / "review" / "autopilot_checkpoint_audit.jsonl").read_text(
        encoding="utf-8"
    )
    assert '"action": "approve_all"' in audit
    assert '"approved_by": "author"' in audit


def test_approve_all_rejects_blockers_without_mutating_manifest(tmp_path):
    from dlstudio.services.autopilot_checkpoint import approve_all

    manifest_path = _write_inputs(tmp_path, blocker=True)
    before = manifest_path.read_bytes()

    try:
        approve_all(tmp_path, approved_by="author")
    except ValueError as exc:
        assert "blocker" in str(exc).casefold()
    else:
        raise AssertionError("approval must fail while a blocker is present")
    assert manifest_path.read_bytes() == before


def test_request_change_is_structured_and_never_changes_shot_meaning(tmp_path):
    from dlstudio.services.autopilot_checkpoint import request_change

    manifest_path = _write_inputs(tmp_path)
    before = manifest_path.read_bytes()

    result = request_change(
        tmp_path,
        action="change_text",
        shot_id="b01_s01",
        reason="Shorten the sentence",
        requested_by="author",
    )

    assert result["status"] == "requested"
    assert result["request"]["action"] == "change_text"
    assert result["request"]["shot_id"] == "b01_s01"
    assert manifest_path.read_bytes() == before
    requests = json.loads(
        (tmp_path / "data" / "plan" / "autopilot_requests.json").read_text(encoding="utf-8")
    )
    assert requests["requests"][0]["reason"] == "Shorten the sentence"
