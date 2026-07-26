from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


class InventoryError(RuntimeError):
    """Inventory could not prove a complete, unambiguous classification."""


@dataclass(frozen=True)
class ProjectRoot:
    name: str
    path: Path
    disposition: str
    rule_id: str


@dataclass(frozen=True)
class DispositionRules:
    source_path: Path
    payload: dict[str, Any]

    @classmethod
    def load_default(cls) -> "DispositionRules":
        return cls.load(Path(__file__).with_name("disposition_rules.json"))

    @classmethod
    def load(cls, path: Path) -> "DispositionRules":
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise InventoryError(f"cannot parse disposition rules {path}: {exc}") from exc
        if payload.get("schema_version") != 1:
            raise InventoryError("unsupported disposition rules schema")
        for key in ("project_rules", "artifact_rules", "workspace_excludes"):
            if key not in payload:
                raise InventoryError(f"disposition rules missing {key}")
        return cls(source_path=path.resolve(), payload=payload)


def _winning_rule(
    matches: list[dict[str, Any]], fallback: dict[str, Any], subject: str
) -> dict[str, Any]:
    if not matches:
        return fallback
    top_priority = max(int(rule["priority"]) for rule in matches)
    winners = [rule for rule in matches if int(rule["priority"]) == top_priority]
    if len(winners) != 1:
        ids = ", ".join(sorted(str(rule["id"]) for rule in winners))
        raise InventoryError(f"ambiguous disposition for {subject}: {ids}")
    return winners[0]


def classify_project_roots(workspace: Path, rules: DispositionRules) -> list[ProjectRoot]:
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise InventoryError(f"workspace is not a directory: {workspace}")
    excludes = set(rules.payload["workspace_excludes"])
    specs = rules.payload["project_rules"]
    fallbacks = [rule for rule in specs if rule.get("fallback")]
    if len(fallbacks) != 1:
        raise InventoryError("project rules require exactly one safe fallback")
    fallback = fallbacks[0]
    roots: list[ProjectRoot] = []
    for candidate in sorted(workspace.iterdir(), key=lambda item: item.name.casefold()):
        if candidate.name in excludes or not candidate.is_dir():
            continue
        matches: list[dict[str, Any]] = []
        for rule in specs:
            if rule.get("fallback"):
                continue
            if candidate.name in rule.get("names", []):
                matches.append(rule)
                continue
            marker = rule.get("marker")
            if marker:
                marker_path = candidate / marker
                marker_kind = rule.get("marker_kind", "file")
                present = marker_path.is_dir() if marker_kind == "directory" else marker_path.is_file()
                if present:
                    matches.append(rule)
        selected = _winning_rule(matches, fallback, candidate.name)
        disposition = selected["disposition"]
        if disposition not in {"MIGRATE_ACTIVE", "ARCHIVE_READ_ONLY", "DELETE_CONFIRMED"}:
            raise InventoryError(f"invalid project disposition {disposition}")
        roots.append(
            ProjectRoot(
                name=candidate.name,
                path=candidate,
                disposition=disposition,
                rule_id=selected["id"],
            )
        )
    return roots


def project_roots_report(workspace: Path, rules: DispositionRules) -> dict[str, Any]:
    roots = classify_project_roots(workspace, rules)
    by_disposition: dict[str, int] = {}
    for root in roots:
        by_disposition[root.disposition] = by_disposition.get(root.disposition, 0) + 1
    return {
        "schema_version": 1,
        "workspace": str(workspace.resolve()),
        "rules_sha256": hashlib.sha256(rules.source_path.read_bytes()).hexdigest(),
        "roots": [
            {
                "name": root.name,
                "disposition": root.disposition,
                "rule_id": root.rule_id,
            }
            for root in roots
        ],
        "summary": {
            "roots": len(roots),
            "unmatched": 0,
            "ambiguous": 0,
            "by_disposition": dict(sorted(by_disposition.items())),
        },
    }


def _classify_artifact(relative_path: str, rules: DispositionRules) -> dict[str, Any]:
    specs = rules.payload["artifact_rules"]
    fallbacks = [rule for rule in specs if rule.get("fallback")]
    if len(fallbacks) != 1:
        raise InventoryError("artifact rules require exactly one safe fallback")
    matches = [
        rule
        for rule in specs
        if not rule.get("fallback")
        and re.search(str(rule["path_regex"]), relative_path, flags=re.IGNORECASE)
    ]
    return _winning_rule(matches, fallbacks[0], relative_path)


def _parse_file(path: Path, parse_as: str | None) -> None:
    if parse_as == "by_extension":
        parse_as = {
            ".json": "json",
            ".toml": "toml",
            ".py": "python",
        }.get(path.suffix.lower())
    if parse_as is None:
        return
    data = path.read_bytes()
    text = data.decode("utf-8-sig")
    if parse_as == "json":
        json.loads(text)
    elif parse_as == "toml":
        tomllib.loads(text)
    elif parse_as == "python":
        ast.parse(text, filename=str(path))
    else:
        raise InventoryError(f"unknown parser {parse_as!r}")


def hash_path(path: Path) -> str:
    if path.is_symlink():
        payload = ("symlink\0" + os.readlink(path)).encode("utf-8")
        return hashlib.sha256(payload).hexdigest()
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


_MEDIA_SUFFIXES = {
    ".aac", ".avi", ".flac", ".gif", ".jpeg", ".jpg", ".m4a", ".mkv",
    ".mov", ".mp3", ".mp4", ".ogg", ".otf", ".png", ".ttf", ".wav",
    ".webm", ".webp", ".woff", ".woff2",
}
_SOURCE_SEGMENTS = {"audio", "fonts", "footage", "images", "infographics", "music", "recordings", "sfx"}


def _is_source_media(relative_path: str) -> bool:
    path = Path(relative_path)
    return path.suffix.lower() in _MEDIA_SUFFIXES and bool(
        set(part.casefold() for part in path.parts) & _SOURCE_SEGMENTS
    ) and "finalize" not in (part.casefold() for part in path.parts)


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for current, directories, names in os.walk(root, followlinks=False):
        symlinked_directories = [
            name for name in directories if (Path(current) / name).is_symlink()
        ]
        files.extend(Path(current) / name for name in sorted(symlinked_directories, key=str.casefold))
        directories[:] = sorted(
            (name for name in directories if not (Path(current) / name).is_symlink()),
            key=str.casefold,
        )
        for name in sorted(names, key=str.casefold):
            files.append(Path(current) / name)
    return files


def build_before_manifest(workspace: Path, rules: DispositionRules) -> dict[str, Any]:
    workspace = workspace.resolve()
    roots = classify_project_roots(workspace, rules)
    entries: list[dict[str, Any]] = []
    parse_failures: list[str] = []
    for root in roots:
        if root.path.is_symlink():
            raise InventoryError(
                f"project root symlink cannot be inventoried safely: {root.name}"
            )
        for path in _iter_files(root.path):
            workspace_relative = path.relative_to(workspace).as_posix()
            project_relative = path.relative_to(root.path).as_posix()
            selected = _classify_artifact(project_relative, rules)
            source_media = _is_source_media(project_relative)
            action = str(selected["action"])
            if source_media and action in {"DROP", "DELETE"}:
                raise InventoryError(f"source media may not be deleted: {workspace_relative}")
            try:
                _parse_file(path, selected.get("parse_as"))
                digest = hash_path(path)
                size = path.lstat().st_size
            except (OSError, UnicodeError, ValueError, SyntaxError, json.JSONDecodeError, tomllib.TOMLDecodeError) as exc:
                parse_failures.append(f"{workspace_relative}: {exc}")
                continue
            entries.append(
                {
                    "path": workspace_relative,
                    "project_root": root.name,
                    "project_disposition": root.disposition,
                    "project_rule_id": root.rule_id,
                    "rule_id": selected["id"],
                    "action": action,
                    "target_owner": selected["target_owner"],
                    "bytes": size,
                    "sha256": digest,
                    "kind": "symlink" if path.is_symlink() else "file",
                    "source_media": source_media,
                }
            )
    if parse_failures:
        details = "\n".join(parse_failures[:20])
        raise InventoryError(f"parse/hash failures ({len(parse_failures)}):\n{details}")
    by_action: dict[str, int] = {}
    by_disposition: dict[str, int] = {}
    for entry in entries:
        by_action[entry["action"]] = by_action.get(entry["action"], 0) + 1
        disposition = entry["project_disposition"]
        by_disposition[disposition] = by_disposition.get(disposition, 0) + 1
    return {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "workspace": str(workspace),
        "rules_sha256": hashlib.sha256(rules.source_path.read_bytes()).hexdigest(),
        "project_roots": [
            {
                "name": root.name,
                "disposition": root.disposition,
                "rule_id": root.rule_id,
            }
            for root in roots
        ],
        "entries": entries,
        "summary": {
            "projects": len(roots),
            "entries": len(entries),
            "bytes": sum(int(entry["bytes"]) for entry in entries),
            "source_media_bytes": sum(
                int(entry["bytes"]) for entry in entries if entry["source_media"]
            ),
            "by_action": dict(sorted(by_action.items())),
            "by_project_disposition": dict(sorted(by_disposition.items())),
            "unmatched": 0,
            "ambiguous": 0,
            "parse_failures": 0,
        },
    }


def load_manifest(path: Path) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"cannot parse manifest {path}: {exc}") from exc
    if manifest.get("schema_version") != 1 or not isinstance(manifest.get("entries"), list):
        raise InventoryError("unsupported or incomplete before-manifest")
    return manifest
