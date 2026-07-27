from __future__ import annotations

import ast
import hashlib
import json
import os
import re
import tomllib
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath, PureWindowsPath
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
        for key in (
            "project_rules",
            "artifact_rules",
            "workspace_excludes",
            "workspace_exclude_prefixes",
        ):
            if key not in payload:
                raise InventoryError(f"disposition rules missing {key}")
        _validate_workspace_exclusions(payload)
        return cls(source_path=path.resolve(), payload=payload)


def _validate_workspace_exclusions(payload: dict[str, Any]) -> None:
    exact = payload["workspace_excludes"]
    prefixes = payload["workspace_exclude_prefixes"]
    if not isinstance(exact, list) or not isinstance(prefixes, list):
        raise InventoryError("workspace exclusions must be lists")

    def validate_names(values: list[Any], label: str) -> list[str]:
        if any(
            not isinstance(value, str)
            or not value
            or value in {".", ".."}
            or "/" in value
            or "\\" in value
            for value in values
        ):
            raise InventoryError(f"{label} must contain top-level basenames")
        normalized = [value.casefold() for value in values]
        if len(normalized) != len(set(normalized)):
            raise InventoryError(f"{label} contains duplicate values")
        return normalized

    exact_keys = validate_names(exact, "workspace_excludes")
    prefix_keys = validate_names(prefixes, "workspace_exclude_prefixes")
    if any(
        len(prefix) < 6
        or prefix[0] not in {".", "_"}
        or prefix[-1] not in {"-", "_"}
        for prefix in prefixes
    ):
        raise InventoryError(
            "workspace exclusion prefixes must be narrow generated namespaces"
        )
    named_projects = {
        str(name).casefold()
        for rule in payload["project_rules"]
        for name in rule.get("names", [])
    }
    if named_projects & set(exact_keys):
        raise InventoryError("workspace exclusion overlaps a named project")
    if any(
        project.startswith(prefix)
        for project in named_projects
        for prefix in prefix_keys
    ):
        raise InventoryError("workspace exclusion prefix overlaps a named project")


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


def _scan_workspace_roots(
    workspace: Path, rules: DispositionRules
) -> tuple[list[ProjectRoot], list[dict[str, str]]]:
    workspace = workspace.resolve()
    if not workspace.is_dir():
        raise InventoryError(f"workspace is not a directory: {workspace}")
    excludes = {
        value.casefold(): value for value in rules.payload["workspace_excludes"]
    }
    exclude_prefixes = tuple(rules.payload["workspace_exclude_prefixes"])
    specs = rules.payload["project_rules"]
    fallbacks = [rule for rule in specs if rule.get("fallback")]
    if len(fallbacks) != 1:
        raise InventoryError("project rules require exactly one safe fallback")
    fallback = fallbacks[0]
    roots: list[ProjectRoot] = []
    excluded: list[dict[str, str]] = []
    for candidate in sorted(workspace.iterdir(), key=lambda item: item.name.casefold()):
        if not candidate.is_dir():
            continue
        candidate_key = candidate.name.casefold()
        if candidate_key in excludes:
            excluded.append(
                {
                    "name": candidate.name,
                    "rule": "workspace_excludes",
                    "value": excludes[candidate_key],
                }
            )
            continue
        prefix = next(
            (
                value
                for value in exclude_prefixes
                if candidate_key.startswith(value.casefold())
            ),
            None,
        )
        if prefix is not None:
            excluded.append(
                {
                    "name": candidate.name,
                    "rule": "workspace_exclude_prefixes",
                    "value": prefix,
                }
            )
            continue
        matches: list[dict[str, Any]] = []
        for rule in specs:
            if rule.get("fallback"):
                continue
            if candidate_key in {
                str(name).casefold() for name in rule.get("names", [])
            }:
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
    return roots, excluded


def classify_project_roots(workspace: Path, rules: DispositionRules) -> list[ProjectRoot]:
    return _scan_workspace_roots(workspace, rules)[0]


def project_roots_report(workspace: Path, rules: DispositionRules) -> dict[str, Any]:
    roots, excluded = _scan_workspace_roots(workspace, rules)
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
        "excluded_roots": excluded,
        "summary": {
            "roots": len(roots),
            "excluded": len(excluded),
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


def iter_files(root: Path) -> list[Path]:
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
    roots, excluded = _scan_workspace_roots(workspace, rules)
    entries: list[dict[str, Any]] = []
    parse_failures: list[str] = []
    for root in roots:
        if root.path.is_symlink():
            raise InventoryError(
                f"project root symlink cannot be inventoried safely: {root.name}"
            )
        for path in iter_files(root.path):
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
        "excluded_roots": excluded,
        "entries": entries,
        "summary": {
            "projects": len(roots),
            "excluded": len(excluded),
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


_MANIFEST_ENTRY_FIELDS = {
    "path",
    "project_root",
    "project_disposition",
    "project_rule_id",
    "rule_id",
    "action",
    "target_owner",
    "bytes",
    "sha256",
    "kind",
    "source_media",
}
_MANIFEST_ENTRY_STRING_FIELDS = {
    "project_root",
    "project_disposition",
    "project_rule_id",
    "rule_id",
    "action",
    "target_owner",
}
_PORTABLE_INVALID_CHARS = frozenset('<>:"|?*')


def _portable_manifest_path(value: Any) -> PurePosixPath:
    if not isinstance(value, str) or not value or "\x00" in value:
        raise InventoryError("manifest entry path must be a non-empty string")
    if "\\" in value:
        raise InventoryError(f"manifest entry path is not portable: {value!r}")
    components = value.split("/")
    if any(component in {"", ".", ".."} for component in components):
        raise InventoryError(f"manifest entry path is not normalized: {value!r}")
    if any(
        component.endswith((" ", "."))
        or any(character in _PORTABLE_INVALID_CHARS for character in component)
        for component in components
    ):
        raise InventoryError(f"manifest entry path is not portable: {value!r}")
    posix = PurePosixPath(value)
    windows = PureWindowsPath(value)
    if (
        posix.is_absolute()
        or windows.is_absolute()
        or bool(windows.drive)
        or posix.as_posix() != value
    ):
        raise InventoryError(
            f"manifest entry path must be normalized and relative: {value!r}"
        )
    return posix


def _required_nonempty_string(
    value: dict[str, Any], field: str, subject: str
) -> str:
    selected = value.get(field)
    if not isinstance(selected, str) or not selected:
        raise InventoryError(f"{subject} requires non-empty {field}")
    return selected


def validate_manifest(
    manifest: dict[str, Any], *, expected_workspace: Path | None = None
) -> dict[str, Any]:
    if not isinstance(manifest, dict) or manifest.get("schema_version") != 1:
        raise InventoryError("unsupported or incomplete before-manifest")
    if (
        not isinstance(manifest.get("generated_at"), str)
        or not manifest["generated_at"]
    ):
        raise InventoryError("before-manifest requires generated_at")
    rules_sha256 = manifest.get("rules_sha256")
    if (
        not isinstance(rules_sha256, str)
        or re.fullmatch(r"[0-9a-f]{64}", rules_sha256) is None
    ):
        raise InventoryError("before-manifest requires a valid rules_sha256")

    workspace_value = manifest.get("workspace")
    if not isinstance(workspace_value, str) or not workspace_value:
        raise InventoryError("before-manifest requires workspace")
    declared_workspace = Path(workspace_value)
    if not declared_workspace.is_absolute():
        raise InventoryError("manifest workspace must be absolute")
    declared_workspace = declared_workspace.resolve()
    if expected_workspace is not None and (
        declared_workspace != expected_workspace.resolve()
    ):
        raise InventoryError(
            "manifest workspace does not match the requested workspace"
        )

    project_roots_value = manifest.get("project_roots")
    if not isinstance(project_roots_value, list):
        raise InventoryError("before-manifest requires project_roots")
    project_roots: dict[str, dict[str, Any]] = {}
    project_root_keys: set[str] = set()
    for index, value in enumerate(project_roots_value):
        subject = f"manifest project root {index}"
        if not isinstance(value, dict):
            raise InventoryError(f"{subject} must be an object")
        name = _required_nonempty_string(value, "name", subject)
        try:
            root_path = _portable_manifest_path(name)
        except InventoryError as exc:
            raise InventoryError(f"{subject} has invalid name") from exc
        if len(root_path.parts) != 1:
            raise InventoryError(f"{subject} has invalid name")
        key = name.casefold()
        if key in project_root_keys:
            raise InventoryError(f"duplicate manifest project root: {name}")
        project_root_keys.add(key)
        _required_nonempty_string(value, "disposition", subject)
        _required_nonempty_string(value, "rule_id", subject)
        project_roots[name] = value

    excluded_roots_value = manifest.get("excluded_roots")
    if not isinstance(excluded_roots_value, list):
        raise InventoryError("before-manifest requires excluded_roots")
    excluded_root_keys: set[str] = set()
    for index, value in enumerate(excluded_roots_value):
        subject = f"manifest excluded root {index}"
        if not isinstance(value, dict):
            raise InventoryError(f"{subject} must be an object")
        if set(value) != {"name", "rule", "value"}:
            raise InventoryError(f"{subject} has invalid fields")
        name = _required_nonempty_string(value, "name", subject)
        excluded_by = _required_nonempty_string(value, "rule", subject)
        excluded_value = _required_nonempty_string(value, "value", subject)
        if excluded_by not in {
            "workspace_excludes",
            "workspace_exclude_prefixes",
        }:
            raise InventoryError(f"{subject} has invalid rule")
        try:
            root_path = _portable_manifest_path(name)
        except InventoryError as exc:
            raise InventoryError(f"{subject} has invalid name") from exc
        if len(root_path.parts) != 1:
            raise InventoryError(f"{subject} has invalid name")
        if (
            excluded_value in {".", ".."}
            or "/" in excluded_value
            or "\\" in excluded_value
        ):
            raise InventoryError(f"{subject} has invalid value")
        if excluded_by == "workspace_excludes":
            if name.casefold() != excluded_value.casefold():
                raise InventoryError(f"{subject} exact value does not match name")
        elif (
            len(excluded_value) < 6
            or excluded_value[0] not in {".", "_"}
            or excluded_value[-1] not in {"-", "_"}
            or not name.casefold().startswith(excluded_value.casefold())
        ):
            raise InventoryError(f"{subject} prefix value does not match name")
        key = name.casefold()
        if key in project_root_keys or key in excluded_root_keys:
            raise InventoryError(f"duplicate manifest root: {name}")
        excluded_root_keys.add(key)

    entries_value = manifest.get("entries")
    if not isinstance(entries_value, list):
        raise InventoryError("before-manifest requires entries")
    entries: list[tuple[dict[str, Any], PurePosixPath]] = []
    exact_paths: set[str] = set()
    casefold_paths: set[str] = set()
    for index, value in enumerate(entries_value):
        subject = f"manifest entry {index}"
        if not isinstance(value, dict):
            raise InventoryError(f"{subject} must be an object")
        missing = sorted(_MANIFEST_ENTRY_FIELDS - value.keys())
        if missing:
            raise InventoryError(
                f"{subject} missing required field {missing[0]}"
            )
        relative = _portable_manifest_path(value["path"])
        raw_path = relative.as_posix()
        casefold_path = raw_path.casefold()
        if raw_path in exact_paths or casefold_path in casefold_paths:
            raise InventoryError(f"duplicate manifest entry path: {raw_path}")
        exact_paths.add(raw_path)
        casefold_paths.add(casefold_path)

        for field in _MANIFEST_ENTRY_STRING_FIELDS:
            _required_nonempty_string(value, field, subject)
        if value["kind"] not in {"file", "symlink"}:
            raise InventoryError(f"{subject} has invalid kind")
        digest = value["sha256"]
        if (
            not isinstance(digest, str)
            or re.fullmatch(r"[0-9a-f]{64}", digest) is None
        ):
            raise InventoryError(f"{subject} has invalid sha256")
        size = value["bytes"]
        if (
            not isinstance(size, int)
            or isinstance(size, bool)
            or size < 0
        ):
            raise InventoryError(f"{subject} has invalid bytes")
        if not isinstance(value["source_media"], bool):
            raise InventoryError(f"{subject} has invalid source_media")
        entries.append((value, relative))

    symlink_paths = {
        tuple(part.casefold() for part in relative.parts)
        for entry, relative in entries
        if entry["kind"] == "symlink"
    }
    for _entry, relative in entries:
        parts = tuple(part.casefold() for part in relative.parts)
        if any(parts[:depth] in symlink_paths for depth in range(1, len(parts))):
            raise InventoryError(
                f"manifest entry is below a symlink: {relative.as_posix()}"
            )

    for entry, relative in entries:
        project_root = entry["project_root"]
        root = project_roots.get(project_root)
        if root is None or relative.parts[0] != project_root:
            raise InventoryError(
                f"manifest entry project_root mismatch: {relative.as_posix()}"
            )
        if (
            entry["project_disposition"] != root["disposition"]
            or entry["project_rule_id"] != root["rule_id"]
        ):
            raise InventoryError(
                f"manifest entry project metadata mismatch: {relative.as_posix()}"
            )

    by_action: dict[str, int] = {}
    by_disposition: dict[str, int] = {}
    for entry, _relative in entries:
        action = entry["action"]
        disposition = entry["project_disposition"]
        by_action[action] = by_action.get(action, 0) + 1
        by_disposition[disposition] = by_disposition.get(disposition, 0) + 1
    expected_summary = {
        "projects": len(project_roots),
        "excluded": len(excluded_root_keys),
        "entries": len(entries),
        "bytes": sum(entry["bytes"] for entry, _relative in entries),
        "source_media_bytes": sum(
            entry["bytes"]
            for entry, _relative in entries
            if entry["source_media"]
        ),
        "by_action": dict(sorted(by_action.items())),
        "by_project_disposition": dict(sorted(by_disposition.items())),
        "unmatched": 0,
        "ambiguous": 0,
        "parse_failures": 0,
    }
    summary = manifest.get("summary")
    if not isinstance(summary, dict):
        raise InventoryError("before-manifest requires summary")
    for field, expected in expected_summary.items():
        if json.dumps(
            summary.get(field), sort_keys=True, separators=(",", ":")
        ) != json.dumps(expected, sort_keys=True, separators=(",", ":")):
            raise InventoryError(f"manifest summary mismatch for {field}")
    return manifest


def load_manifest(
    path: Path, *, expected_workspace: Path | None = None
) -> dict[str, Any]:
    try:
        manifest = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise InventoryError(f"cannot parse manifest {path}: {exc}") from exc
    return validate_manifest(
        manifest, expected_workspace=expected_workspace
    )
