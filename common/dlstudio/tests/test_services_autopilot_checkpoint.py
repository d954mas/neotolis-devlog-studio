from __future__ import annotations

import json
from types import SimpleNamespace


def _write_inputs(root, *, blocker: bool = False):
    plan = root / "data" / "plan"
    assets = root / "data" / "assets"
    review = root / "data" / "review"
    plan.mkdir(parents=True)
    assets.mkdir(parents=True)
    review.mkdir(parents=True)
    footage = root / "data" / "footage"
    footage.mkdir(parents=True)
    source = footage / "game.mp4"
    source.write_bytes(b"reviewed-gameplay")
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
            "sha256": __import__("hashlib").sha256(source.read_bytes()).hexdigest(),
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
    manifest_path = plan / "shot_manifest.json"
    catalog_path = assets / "catalog.json"
    (review / "preflight.json").write_text(json.dumps({
        "wall_time": {"budget_minutes": 60, "elapsed_minutes": 17.5, "stage": "checkpoint"},
        "issues": issues,
        "inputs": {
            "shot_manifest_sha256": __import__(
                "dlstudio.services.autopilot_checkpoint",
                fromlist=["preflight_manifest_sha256"],
            ).preflight_manifest_sha256(manifest_path),
            "asset_catalog_sha256": __import__("hashlib").sha256(
                catalog_path.read_bytes()
            ).hexdigest(),
        },
    }), encoding="utf-8")
    return manifest_path


def _approve(root, *, approved_by: str = "author"):
    from dlstudio.services.autopilot_checkpoint import approve_all, load_checkpoint

    return approve_all(
        root,
        approved_by=approved_by,
        expected_checkpoint_digest=load_checkpoint(root)["checkpoint_digest"],
    )


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
    assert data["can_resume"] is False


def test_approve_all_only_changes_approved_flags_and_writes_audit(tmp_path):
    from dlstudio.services.autopilot_checkpoint import approve_all

    manifest_path = _write_inputs(tmp_path)
    before = json.loads(manifest_path.read_text(encoding="utf-8"))
    preflight_path = tmp_path / "data" / "review" / "preflight.json"
    preflight_before = preflight_path.read_bytes()

    result = _approve(tmp_path)

    after = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert result["approved_count"] == 1
    assert after["shots"][0]["approved"] is True
    expected = before
    expected["shots"][0]["approved"] = True
    assert after == expected
    assert preflight_path.read_bytes() == preflight_before
    assert result["checkpoint"]["approval_valid"] is True
    assert result["checkpoint"]["can_resume"] is True
    approval = json.loads(
        (tmp_path / "data" / "plan" / "autopilot_approval.json").read_text(
            encoding="utf-8"
        )
    )
    assert approval["source_sha256"]["data/footage/game.mp4"]
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
        _approve(tmp_path)
    except ValueError as exc:
        assert "blocker" in str(exc).casefold()
    else:
        raise AssertionError("approval must fail while a blocker is present")
    assert manifest_path.read_bytes() == before


def test_approve_all_rejects_checkpoint_changed_after_display(tmp_path):
    from dlstudio.services.autopilot_checkpoint import approve_all, load_checkpoint

    manifest_path = _write_inputs(tmp_path)
    displayed = load_checkpoint(tmp_path)["checkpoint_digest"]
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["shots"][0]["vo_thesis"] = "changed after display"
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")

    try:
        approve_all(
            tmp_path,
            approved_by="author",
            expected_checkpoint_digest=displayed,
        )
    except ValueError as exc:
        assert "changed after it was displayed" in str(exc)
    else:
        raise AssertionError("stale displayed checkpoint must not be approved")


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


def test_changed_reviewed_source_bytes_invalidate_approval(tmp_path):
    from dlstudio.services.autopilot_checkpoint import approve_all, load_checkpoint

    _write_inputs(tmp_path)
    _approve(tmp_path)
    (tmp_path / "data" / "footage" / "game.mp4").write_bytes(b"changed-after-review")

    checkpoint = load_checkpoint(tmp_path)

    assert checkpoint["approval_valid"] is False
    assert checkpoint["can_resume"] is False
    assert "reviewed source bytes changed" in " ".join(checkpoint["approval_errors"])


def test_changed_manifest_or_catalog_bytes_invalidate_approval(tmp_path):
    from dlstudio.services.autopilot_checkpoint import approve_all, load_checkpoint

    manifest = _write_inputs(tmp_path)
    _approve(tmp_path)
    manifest.write_text(
        manifest.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    assert load_checkpoint(tmp_path)["approval_valid"] is False

    catalog_root = tmp_path / "catalog-case"
    _write_inputs(catalog_root)
    _approve(catalog_root)
    catalog = catalog_root / "data" / "assets" / "catalog.json"
    catalog.write_text(
        catalog.read_text(encoding="utf-8") + "\n",
        encoding="utf-8",
    )
    assert load_checkpoint(catalog_root)["approval_valid"] is False


def test_pending_change_request_blocks_current_approval_and_resume(tmp_path):
    from dlstudio.services.autopilot_checkpoint import (
        approve_all,
        load_checkpoint,
        request_change,
    )

    _write_inputs(tmp_path)
    _approve(tmp_path)
    request_change(
        tmp_path,
        action="replace_shot",
        shot_id="b01_s01",
        reason="Use a newer take",
        requested_by="author",
    )

    checkpoint = load_checkpoint(tmp_path)

    assert checkpoint["can_resume"] is False
    assert checkpoint["open_requests"][0]["status"] == "requested"
    assert any(item["code"] == "AUTOPILOT-REQUEST" for item in checkpoint["blockers"])


def test_edit_or_design_change_invalidates_author_approval(tmp_path):
    from dlstudio.services.autopilot_checkpoint import load_checkpoint

    _write_inputs(tmp_path)
    edit = tmp_path / "edit"
    edit.mkdir()
    design = edit / "design.py"
    design.write_text("SAFE_MARGIN = 80\n", encoding="utf-8")
    _approve(tmp_path)
    assert load_checkpoint(tmp_path)["approval_valid"] is True

    design.write_text("SAFE_MARGIN = 12\n", encoding="utf-8")

    checkpoint = load_checkpoint(tmp_path)
    assert checkpoint["approval_valid"] is False
    assert "edit, design, or reviewed artifact changed" in " ".join(
        checkpoint["approval_errors"]
    )


def test_checkpoint_rejects_preflight_for_different_compiled_ir(
    tmp_path, monkeypatch
):
    from dlstudio.services.autopilot_checkpoint import (
        compiled_timeline_sha256,
        load_checkpoint,
    )
    import dlstudio.compile as compile_mod
    import dlstudio.production as production_mod

    _write_inputs(tmp_path)
    edit = tmp_path / "edit"
    edit.mkdir()
    (edit / "__init__.py").write_text("EDIT = object()\n", encoding="utf-8")

    class Timeline:
        def __init__(self, revision):
            self.revision = revision

        def model_dump(self, *, mode):
            assert mode == "json"
            return {"revision": self.revision}

    preflight_path = tmp_path / "data" / "review" / "preflight.json"
    preflight = json.loads(preflight_path.read_text(encoding="utf-8"))
    preflight["inputs"]["compiled_ir_sha256"] = compiled_timeline_sha256(
        Timeline("A")
    )
    preflight_path.write_text(json.dumps(preflight), encoding="utf-8")
    monkeypatch.setattr(
        production_mod,
        "load_production_edit_module",
        lambda *_args, **_kwargs: (
            SimpleNamespace(EDIT=object()),
            object(),
            "test.edit",
        ),
    )
    monkeypatch.setattr(
        compile_mod,
        "build_timeline",
        lambda _edit: Timeline("B"),
    )

    checkpoint = load_checkpoint(tmp_path)
    assert checkpoint["can_approve_all"] is False
    assert any(
        issue["code"] == "AUTOPILOT-STALE-PREFLIGHT"
        and "compiled IR digest" in issue["message"]
        for issue in checkpoint["blockers"]
    )
