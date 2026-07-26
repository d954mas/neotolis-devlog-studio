from __future__ import annotations

import json
from pathlib import Path


def _write_complete_contract(root: Path) -> tuple[Path, Path]:
    from dlstudio.services.longform_preflight import (
        longform_shot_manifest_template,
        longform_story_map_template,
    )

    plan = root / "data" / "plan"
    footage = root / "data" / "footage"
    plan.mkdir(parents=True)
    footage.mkdir(parents=True)

    story = longform_story_map_template(target_duration_seconds=360)
    story["title"] = "I rebuilt the tram system"
    story["macro_question"] = "Can the prototype carry a complete game loop?"
    story["cold_open"].update({
        "anomaly": "The tram ignores the queue",
        "result_glimpse": "The repaired tram collects the queue",
        "episode_promise": "Rebuild one complete tram loop",
    })
    story["ending"].update({
        "resolved_question": "The loop now works end to end",
        "honest_status": "Balance and art are still provisional",
        "next_open_loop": "Can upgrades make the choice interesting?",
    })

    source_index = 0

    def source(role: str) -> dict[str, str]:
        nonlocal source_index
        source_index += 1
        rel = f"data/footage/source_{source_index:02d}.mp4"
        (root / rel).write_bytes(f"source-{source_index}".encode())
        return {"role": role, "path": rel, "status": "existing"}

    story["cold_open"]["sources"] = [source("failure"), source("payoff")]
    arcs = []
    for index in range(4):
        start = 20 + index * 70
        arcs.append({
            "id": f"arc_{index + 1:02d}",
            "planned_start_seconds": start,
            "planned_end_seconds": start + 60,
            "viewer_question": f"Will part {index + 1} work?",
            "goal": "Make one visible behavior work",
            "failure": "The first version visibly fails",
            "cause": "One concrete system constraint",
            "solution": "One understandable design decision",
            "proof": "The repaired behavior works in gameplay",
            "reaction": "An honest author reaction",
            "sources": [
                source("before"),
                source("failure"),
                source("process"),
                source("payoff"),
            ],
        })
    story["mini_arcs"] = arcs

    montage = longform_shot_manifest_template()
    montage["music_phases"] = [
        {"id": "investigation", "t0": 0, "t1": 170, "purpose": "tension"},
        {"id": "payoff", "t0": 170, "t1": 360, "purpose": "release"},
    ]
    montage["sfx_cues"] = [
        {"id": f"sfx_{index + 1:02d}", "at": 10 + index * 35, "purpose": "story beat"}
        for index in range(8)
    ]
    montage["shots"] = [
        {
            "id": "cold_failure",
            "arc_id": "cold_open",
            "story_role": "failure",
            "visual_mode": "gameplay",
            "purpose": "Show the real opening failure",
            "vo_range": "cold open anomaly",
            "src": story["cold_open"]["sources"][0]["path"],
            "t0": 0,
            "t1": 4,
            "motion": "native",
            "presentation": "full_bleed",
        },
        {
            "id": "cold_payoff",
            "arc_id": "cold_open",
            "story_role": "payoff",
            "visual_mode": "before_after",
            "purpose": "Preview the eventual working result",
            "vo_range": "cold open result glimpse",
            "src": story["cold_open"]["sources"][1]["path"],
            "t0": 4,
            "t1": 8,
            "motion": "native",
            "presentation": "full_bleed",
        },
    ]
    visual_modes = ("gameplay", "editor", "diagram", "face")
    for index, arc in enumerate(arcs):
        start = float(arc["planned_start_seconds"])
        for offset, role in enumerate(("before", "failure", "process", "payoff")):
            montage["shots"].append({
                "id": f"{arc['id']}_{role}",
                "arc_id": arc["id"],
                "story_role": role,
                "visual_mode": visual_modes[(index + offset) % len(visual_modes)],
                "purpose": f"Show {role} evidence for {arc['id']}",
                "vo_range": f"{arc['id']} {role}",
                "src": arc["sources"][offset]["path"],
                "t0": start + offset * 5,
                "t1": start + offset * 5 + 5,
                "motion": "native",
                "presentation": "full_bleed",
            })

    story_path = plan / "story_map.json"
    montage_path = plan / "shot_manifest.json"
    story_path.write_text(json.dumps(story), encoding="utf-8")
    montage_path.write_text(json.dumps(montage), encoding="utf-8")
    return story_path, montage_path


def test_longform_preflight_requires_story_and_montage_contracts(tmp_path):
    from dlstudio.services.longform_preflight import run_longform_preflight

    report = run_longform_preflight(tmp_path, strict=False)

    assert {issue.code for issue in report.errors} == {
        "VQ-LONGFORM-STORY",
        "VQ-LONGFORM-MONTAGE",
    }


def test_longform_preflight_accepts_complete_evidence_first_plan(tmp_path):
    from dlstudio.services.longform_preflight import run_longform_preflight

    _write_complete_contract(tmp_path)

    report = run_longform_preflight(tmp_path, strict=True)

    assert report.ok, report.issues


def test_longform_strict_gate_blocks_unresolved_capture(tmp_path):
    from dlstudio.services.longform_preflight import run_longform_preflight

    story_path, _montage_path = _write_complete_contract(tmp_path)
    story = json.loads(story_path.read_text(encoding="utf-8"))
    story["mini_arcs"][0]["sources"][1]["status"] = "needs_capture"
    story_path.write_text(json.dumps(story), encoding="utf-8")

    planning = run_longform_preflight(tmp_path, strict=False)
    strict = run_longform_preflight(tmp_path, strict=True)

    assert not [
        issue for issue in planning.errors
        if issue.code == "VQ-LONGFORM-SOURCE"
    ]
    assert any(
        issue.code == "VQ-LONGFORM-SOURCE"
        and issue.severity == "warn"
        for issue in planning.issues
    )
    assert any(
        issue.code == "VQ-LONGFORM-SOURCE"
        and issue.severity == "error"
        for issue in strict.issues
    )


def test_longform_strict_gate_requires_payoff_coverage_for_every_arc(tmp_path):
    from dlstudio.services.longform_preflight import run_longform_preflight

    _story_path, montage_path = _write_complete_contract(tmp_path)
    montage = json.loads(montage_path.read_text(encoding="utf-8"))
    montage["shots"] = [
        shot for shot in montage["shots"]
        if not (
            shot.get("arc_id") == "arc_02"
            and shot.get("story_role") == "payoff"
        )
    ]
    montage_path.write_text(json.dumps(montage), encoding="utf-8")

    report = run_longform_preflight(tmp_path, strict=True)

    assert any(
        issue.code == "VQ-LONGFORM-PROOF"
        and issue.where == "arc_02"
        for issue in report.errors
    )


def test_longform_strict_gate_rejects_unplanned_long_master_shot(tmp_path):
    from dlstudio.services.longform_preflight import run_longform_preflight

    _story_path, montage_path = _write_complete_contract(tmp_path)
    montage = json.loads(montage_path.read_text(encoding="utf-8"))
    montage["shots"][2]["t1"] = montage["shots"][2]["t0"] + 12
    montage_path.write_text(json.dumps(montage), encoding="utf-8")

    report = run_longform_preflight(tmp_path, strict=True)

    assert any(
        issue.code == "VQ-LONGFORM-CADENCE"
        and issue.where == montage["shots"][2]["id"]
        for issue in report.errors
    )


def test_longform_gate_requires_editorial_purpose_and_vo_range(tmp_path):
    from dlstudio.services.longform_preflight import run_longform_preflight

    _story_path, montage_path = _write_complete_contract(tmp_path)
    montage = json.loads(montage_path.read_text(encoding="utf-8"))
    montage["shots"][2].pop("purpose")
    montage["shots"][2].pop("vo_range")
    montage_path.write_text(json.dumps(montage), encoding="utf-8")

    report = run_longform_preflight(tmp_path, strict=False)

    messages = [
        issue.message
        for issue in report.errors
        if issue.where == montage["shots"][2]["id"]
    ]
    assert "purpose is required" in messages
    assert "vo_range is required" in messages
