from __future__ import annotations

import json


def _write_contract(root, *, complete: bool = True, allow=()) -> None:
    plan = root / "data" / "plan"
    plan.mkdir(parents=True, exist_ok=True)
    story = {
        "premise": "I am rebuilding my game in 3D" if complete else "",
        "causal_turn": "2D made every new angle expensive",
        "payoff": "3D gives the tram more upgrade freedom",
    }
    (plan / "story_contract.json").write_text(json.dumps({
        "version": 1,
        "standalone_story": story,
        "allow_editorial_labels": list(allow),
    }), encoding="utf-8")
    (plan / "shot_manifest.json").write_text(json.dumps({
        "shots": [{"id": "s01", "src": "data/infographics/master.mp4"}]
    }), encoding="utf-8")


def test_editorial_preflight_rejects_incomplete_story_and_visible_reel_label(tmp_path):
    from dlstudio.services.editorial_preflight import run_editorial_preflight

    _write_contract(tmp_path, complete=False)
    source = tmp_path / "data" / "hyperframes" / "master"
    source.mkdir(parents=True)
    (source / "index.html").write_text(
        "<html><body><span>REEL 02</span><script>'REEL 99'</script></body></html>",
        encoding="utf-8",
    )

    report = run_editorial_preflight(tmp_path, require_story_contract=True)

    assert [issue.code for issue in report.issues].count("VQ-STANDALONE") == 1
    labels = [issue.message for issue in report.issues if issue.code == "VQ-EDITORIAL-LABEL"]
    assert labels == ["internal production label is viewer-visible: 'REEL 02'"]


def test_editorial_preflight_accepts_complete_story_and_explicit_label_allowlist(tmp_path):
    from dlstudio.services.editorial_preflight import run_editorial_preflight

    _write_contract(tmp_path, allow=("Part 3",))
    source = tmp_path / "data" / "hyperframes" / "master"
    source.mkdir(parents=True)
    (source / "index.html").write_text(
        "<html><body><h1>Part 3</h1><p>A complete story</p></body></html>",
        encoding="utf-8",
    )

    report = run_editorial_preflight(tmp_path, require_story_contract=True)

    assert report.ok
