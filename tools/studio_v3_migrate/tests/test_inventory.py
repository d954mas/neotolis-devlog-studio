from __future__ import annotations

import json
from copy import deepcopy
from pathlib import Path

import pytest

from tools.studio_v3_migrate.inventory import (
    DispositionRules,
    InventoryError,
    build_before_manifest,
    classify_project_roots,
    load_manifest,
    validate_manifest,
)


def _rules() -> DispositionRules:
    return DispositionRules.load_default()


def _manifest(tmp_path: Path) -> dict:
    project = tmp_path / "video_product"
    (project / "data").mkdir(parents=True)
    (project / "product.toml").write_text(
        "[product]\nid='video'\n", encoding="utf-8"
    )
    (project / "data" / "payload.bin").write_bytes(b"payload")
    return build_before_manifest(tmp_path, _rules())


def _write_manifest(tmp_path: Path, manifest: dict) -> Path:
    path = tmp_path / "before-manifest.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return path


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


def test_generated_test_and_review_roots_are_not_projects(tmp_path: Path) -> None:
    generated = (
        ".test-tmp-intentional-corruption",
        ".phase4-review-repro-loader",
        "_codex_tmp_workflow",
    )
    for name in generated:
        path = tmp_path / name
        path.mkdir()
        (path / "broken.json").write_text("{intentional", encoding="utf-8")
    project = tmp_path / "actual_project"
    project.mkdir()
    (project / "product.toml").write_text("[product]\nid='actual'\n", encoding="utf-8")

    manifest = build_before_manifest(tmp_path, _rules())

    assert [root["name"] for root in manifest["project_roots"]] == ["actual_project"]
    assert {root["name"] for root in manifest["excluded_roots"]} == set(generated)
    assert manifest["summary"]["excluded"] == len(generated)


@pytest.mark.parametrize("prefix", ["", ".", "x", "project"])
def test_broad_workspace_exclusion_prefix_is_rejected(
    tmp_path: Path, prefix: str
) -> None:
    payload = json.loads(_rules().source_path.read_text(encoding="utf-8"))
    payload["workspace_exclude_prefixes"] = [prefix]
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InventoryError, match="prefix"):
        DispositionRules.load(rules_path)


def test_workspace_exclusion_cannot_overlap_named_project(tmp_path: Path) -> None:
    payload = json.loads(_rules().source_path.read_text(encoding="utf-8"))
    payload["workspace_excludes"].append("trolley")
    rules_path = tmp_path / "rules.json"
    rules_path.write_text(json.dumps(payload), encoding="utf-8")

    with pytest.raises(InventoryError, match="overlaps"):
        DispositionRules.load(rules_path)


def test_manifest_rejects_selected_excluded_root_overlap(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    manifest["excluded_roots"] = [
        {
            "name": "video_product",
            "rule": "workspace_excludes",
            "value": "video_product",
        }
    ]
    manifest["summary"]["excluded"] = 1

    with pytest.raises(InventoryError, match="duplicate manifest root"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    "unsafe_path",
    [
        "",
        "/absolute/file.bin",
        "C:/absolute/file.bin",
        "//server/share/file.bin",
        r"video_product\data\file.bin",
        "video_product/./file.bin",
        "video_product/../file.bin",
        "video_product//file.bin",
        "video_product/data/",
    ],
)
def test_manifest_rejects_nonportable_or_noncanonical_paths(
    tmp_path: Path, unsafe_path: str
) -> None:
    manifest = _manifest(tmp_path)
    manifest["entries"][0]["path"] = unsafe_path

    with pytest.raises(InventoryError, match="path"):
        validate_manifest(manifest)


@pytest.mark.parametrize("case_variant", [False, True])
def test_manifest_rejects_exact_and_casefold_duplicate_paths(
    tmp_path: Path, case_variant: bool
) -> None:
    manifest = _manifest(tmp_path)
    duplicate = deepcopy(manifest["entries"][0])
    if case_variant:
        duplicate["path"] = duplicate["path"].upper()
        duplicate["project_root"] = duplicate["project_root"].upper()
    manifest["entries"].append(duplicate)

    with pytest.raises(InventoryError, match="duplicate"):
        validate_manifest(manifest)


def test_manifest_rejects_child_below_symlink_entry(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    parent = deepcopy(manifest["entries"][0])
    parent["path"] = "video_product/data/link"
    parent["kind"] = "symlink"
    child = deepcopy(manifest["entries"][0])
    child["path"] = "video_product/data/link/escaped.bin"
    manifest["entries"] = [parent, child]

    with pytest.raises(InventoryError, match="symlink"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("kind", "directory"),
        ("sha256", "not-a-hash"),
        ("bytes", -1),
        ("bytes", True),
        ("source_media", "false"),
        ("action", ""),
    ],
)
def test_manifest_rejects_invalid_entry_fields(
    tmp_path: Path, field: str, value: object
) -> None:
    manifest = _manifest(tmp_path)
    manifest["entries"][0][field] = value

    with pytest.raises(InventoryError, match=field):
        validate_manifest(manifest)


def test_manifest_rejects_missing_required_entry_field(tmp_path: Path) -> None:
    manifest = _manifest(tmp_path)
    del manifest["entries"][0]["target_owner"]

    with pytest.raises(InventoryError, match="target_owner"):
        validate_manifest(manifest)


@pytest.mark.parametrize(
    ("summary_field", "value"),
    [
        ("projects", True),
        ("entries", 999),
        ("bytes", 0),
        ("source_media_bytes", 999),
        ("by_action", {}),
        ("by_project_disposition", {}),
        ("unmatched", 1),
    ],
)
def test_manifest_rejects_summary_that_differs_from_entries(
    tmp_path: Path, summary_field: str, value: object
) -> None:
    manifest = _manifest(tmp_path)
    manifest["summary"][summary_field] = value

    with pytest.raises(InventoryError, match="summary"):
        validate_manifest(manifest)


def test_load_manifest_optionally_binds_declared_workspace(tmp_path: Path) -> None:
    workspace = tmp_path / "workspace"
    workspace.mkdir()
    manifest = _manifest(workspace)
    manifest_path = _write_manifest(tmp_path, manifest)

    assert load_manifest(
        manifest_path, expected_workspace=workspace
    )["workspace"] == str(workspace.resolve())
    with pytest.raises(InventoryError, match="workspace"):
        load_manifest(
            manifest_path,
            expected_workspace=tmp_path / "different-workspace",
        )
