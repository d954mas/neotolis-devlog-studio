from __future__ import annotations

import json
from pathlib import Path

import pytest

from tools.studio_v3_migrate.inventory import (
    DispositionRules,
    InventoryError,
    build_before_manifest,
    classify_project_roots,
)


def _rules() -> DispositionRules:
    return DispositionRules.load_default()


def test_unknown_project_root_is_preserved_read_only(tmp_path: Path) -> None:
    (tmp_path / "mystery_project").mkdir()
    (tmp_path / "mystery_project" / "opaque.bin").write_bytes(b"unknown")

    roots = classify_project_roots(tmp_path, _rules())

    assert [(root.name, root.disposition) for root in roots] == [
        ("mystery_project", "ARCHIVE_READ_ONLY")
    ]


def test_product_marker_classifies_project_as_active(tmp_path: Path) -> None:
    project = tmp_path / "video_product"
    project.mkdir()
    (project / "product.toml").write_text("[product]\nid='video'\n", encoding="utf-8")

    roots = classify_project_roots(tmp_path, _rules())

    assert [(root.name, root.disposition) for root in roots] == [
        ("video_product", "MIGRATE_ACTIVE")
    ]


def test_manifest_assigns_exactly_one_rule_and_preserves_media(tmp_path: Path) -> None:
    project = tmp_path / "video_product"
    (project / "data" / "footage").mkdir(parents=True)
    (project / "product.toml").write_text("[product]\nid='video'\n", encoding="utf-8")
    (project / "data" / "footage" / "take.mp4").write_bytes(b"media-bytes")

    manifest = build_before_manifest(tmp_path, _rules())

    entries = {entry["path"]: entry for entry in manifest["entries"]}
    media = entries["video_product/data/footage/take.mp4"]
    assert media["rule_id"] == "source_media"
    assert media["action"] == "MIGRATE"
    assert media["source_media"] is True
    assert manifest["summary"]["unmatched"] == 0
    assert manifest["summary"]["ambiguous"] == 0
    assert manifest["summary"]["parse_failures"] == 0


def test_manifest_fails_closed_on_malformed_known_record(tmp_path: Path) -> None:
    project = tmp_path / "video_product"
    (project / "data" / "plan").mkdir(parents=True)
    (project / "product.toml").write_text("[product]\nid='video'\n", encoding="utf-8")
    (project / "data" / "plan" / "shot_manifest.json").write_text(
        "{not valid json", encoding="utf-8"
    )

    with pytest.raises(InventoryError, match="parse"):
        build_before_manifest(tmp_path, _rules())


def test_utf8_bom_is_accepted_for_legacy_json_and_python(tmp_path: Path) -> None:
    project = tmp_path / "video_product"
    (project / "edits" / "main").mkdir(parents=True)
    (project / "product.toml").write_text("[product]\nid='video'\n", encoding="utf-8")
    (project / "edits" / "main" / "beats.py").write_text(
        "VALUE = 1\n", encoding="utf-8-sig"
    )
    (project / "state.json").write_text('{"ok": true}\n', encoding="utf-8-sig")

    manifest = build_before_manifest(tmp_path, _rules())

    assert manifest["summary"]["parse_failures"] == 0


def test_equal_priority_rule_matches_fail_as_ambiguous(tmp_path: Path) -> None:
    project = tmp_path / "video_product"
    project.mkdir()
    (project / "product.toml").write_text("[product]\nid='video'\n", encoding="utf-8")
    rules_payload = json.loads(_rules().source_path.read_text(encoding="utf-8"))
    rules_payload["artifact_rules"].extend(
        [
            {
                "id": "collision_a",
                "priority": 999,
                "path_regex": "product[.]toml$",
                "action": "ARCHIVE",
                "target_owner": "archive",
                "parse_as": "toml",
            },
            {
                "id": "collision_b",
                "priority": 999,
                "path_regex": "product[.]toml$",
                "action": "MIGRATE",
                "target_owner": "constraints",
                "parse_as": "toml",
            },
        ]
    )
    custom_path = tmp_path / "ambiguous_rules.json"
    custom_path.write_text(json.dumps(rules_payload), encoding="utf-8")

    with pytest.raises(InventoryError, match="ambiguous"):
        build_before_manifest(tmp_path, DispositionRules.load(custom_path))


def test_workspace_infrastructure_is_not_discovered_as_project(tmp_path: Path) -> None:
    for name in ("common", "docs", "tools", ".git", "tmp"):
        (tmp_path / name).mkdir()
        (tmp_path / name / "file.txt").write_text(name, encoding="utf-8")
    project = tmp_path / "actual_project"
    project.mkdir()
    (project / "product.toml").write_text("[product]\nid='actual'\n", encoding="utf-8")

    roots = classify_project_roots(tmp_path, _rules())

    assert [root.name for root in roots] == ["actual_project"]

