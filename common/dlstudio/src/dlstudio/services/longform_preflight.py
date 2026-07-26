"""Deterministic long-form devlog planning and montage gates.

The service makes the evidence-first story contract executable before a render
exists. It validates two production-owned files:

* ``data/plan/story_map.json`` — why each mini-arc is worth watching;
* ``data/plan/shot_manifest.json`` — how those arcs are proved and paced.

It deliberately does not score taste. A blind review of the exact MP4 still
owns delivery judgment.
"""
from __future__ import annotations

import json
import math
from pathlib import Path
from typing import Any

from dlstudio.ir import CheckIssue, CheckReport


STORY_MAP_PATH = Path("data/plan/story_map.json")
SHOT_MANIFEST_PATH = Path("data/plan/shot_manifest.json")

SOURCE_ROLES = {"before", "failure", "process", "payoff"}
SOURCE_STATUSES = {"existing", "needs_capture", "placeholder"}
STORY_ROLES = {
    "before",
    "failure",
    "cause",
    "process",
    "solution",
    "payoff",
    "reaction",
    "bridge",
    "context",
}
VISUAL_MODES = {
    "gameplay",
    "editor",
    "code",
    "diagram",
    "reference",
    "physical_metaphor",
    "meme",
    "kinetic_text",
    "before_after",
    "face",
    "title",
    "other",
}
REQUIRED_ARC_FIELDS = (
    "id",
    "viewer_question",
    "goal",
    "failure",
    "cause",
    "solution",
    "proof",
    "reaction",
)


def _nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def _issue(
    issues: list[CheckIssue],
    code: str,
    message: str,
    where: str,
    *,
    error: bool = True,
) -> None:
    issues.append(CheckIssue(
        severity="error" if error else "warn",
        code=code,
        message=message,
        where=where,
    ))


def _read_object(path: Path, code: str, issues: list[CheckIssue]) -> dict[str, Any] | None:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        _issue(issues, code, f"required long-form contract is missing: {path}", path.as_posix())
        return None
    except (OSError, json.JSONDecodeError) as exc:
        _issue(issues, code, f"invalid JSON: {exc}", path.as_posix())
        return None
    if not isinstance(payload, dict):
        _issue(issues, code, "contract root must be a JSON object", path.as_posix())
        return None
    return payload


def longform_story_map_template(
    *,
    target_duration_seconds: int = 480,
) -> dict[str, Any]:
    arc_count = max(4, math.ceil(target_duration_seconds / 90))
    available = max(arc_count * 45, target_duration_seconds - 40)
    arc_span = available / arc_count
    arcs = []
    for index in range(arc_count):
        start = round(20 + index * arc_span, 1)
        end = round(min(target_duration_seconds - 20, start + arc_span - 5), 1)
        arcs.append({
            "id": f"arc_{index + 1:02d}",
            "planned_start_seconds": start,
            "planned_end_seconds": end,
            "viewer_question": "",
            "goal": "",
            "failure": "",
            "cause": "",
            "solution": "",
            "proof": "",
            "reaction": "",
            "sources": [],
        })
    return {
        "schema": "devlog.longform_story_map/v1",
        "title": "",
        "macro_question": "",
        "target_duration_seconds": target_duration_seconds,
        "cold_open": {
            "anomaly": "",
            "result_glimpse": "",
            "episode_promise": "",
            "sources": [],
        },
        "mini_arcs": arcs,
        "ending": {
            "resolved_question": "",
            "honest_status": "",
            "next_open_loop": "",
        },
    }


def longform_shot_manifest_template() -> dict[str, Any]:
    return {
        "version": 2,
        "profile": "longform_devlog",
        "target_semantic_change_seconds": [3, 6],
        "master_shot_max_seconds": 8,
        "target_vo_wpm": [150, 165],
        "author_reaction_interval_seconds": [45, 75],
        "music_phases": [],
        "sfx_cues": [],
        "shots": [],
    }


def _validate_source(
    source: Any,
    *,
    root: Path,
    where: str,
    strict: bool,
    issues: list[CheckIssue],
) -> None:
    if not isinstance(source, dict):
        _issue(issues, "VQ-LONGFORM-SOURCE", "source must be an object", where)
        return
    role = source.get("role")
    path = source.get("path")
    status = source.get("status")
    if role not in SOURCE_ROLES:
        _issue(
            issues,
            "VQ-LONGFORM-SOURCE",
            f"role must be one of {sorted(SOURCE_ROLES)}, got {role!r}",
            where,
        )
    if not _nonempty(path):
        _issue(issues, "VQ-LONGFORM-SOURCE", "source path is required", where)
    if status not in SOURCE_STATUSES:
        _issue(
            issues,
            "VQ-LONGFORM-SOURCE",
            f"status must be one of {sorted(SOURCE_STATUSES)}, got {status!r}",
            where,
        )
        return
    if _nonempty(path) and status == "existing":
        resolved = (root / str(path)).resolve()
        try:
            resolved.relative_to(root)
        except ValueError:
            _issue(
                issues,
                "VQ-LONGFORM-SOURCE",
                "source must stay inside the production root",
                where,
            )
        else:
            if not resolved.is_file():
                _issue(
                    issues,
                    "VQ-LONGFORM-SOURCE",
                    f"declared existing source is missing: {path}",
                    where,
                )
    elif status in {"needs_capture", "placeholder"}:
        _issue(
            issues,
            "VQ-LONGFORM-SOURCE",
            f"unresolved source ({status}): {path}",
            where,
            error=strict,
        )


def _validate_story_map(
    root: Path,
    story: dict[str, Any],
    *,
    strict: bool,
    issues: list[CheckIssue],
) -> tuple[set[str], dict[str, set[str]], float]:
    if story.get("schema") != "devlog.longform_story_map/v1":
        _issue(
            issues,
            "VQ-LONGFORM-STORY",
            "schema must be 'devlog.longform_story_map/v1'",
            STORY_MAP_PATH.as_posix(),
        )
    for field in ("title", "macro_question"):
        if not _nonempty(story.get(field)):
            _issue(
                issues,
                "VQ-LONGFORM-STORY",
                f"{field} must be non-empty",
                f"{STORY_MAP_PATH.as_posix()}:{field}",
            )

    duration = story.get("target_duration_seconds")
    if not isinstance(duration, (int, float)) or duration <= 0:
        _issue(
            issues,
            "VQ-LONGFORM-STORY",
            "target_duration_seconds must be a positive number",
            STORY_MAP_PATH.as_posix(),
        )
        duration = 0.0
    else:
        duration = float(duration)
        if not 360 <= duration <= 720:
            _issue(
                issues,
                "VQ-LONGFORM-STORY",
                f"target {duration:g}s is outside the 6–12 minute working range",
                STORY_MAP_PATH.as_posix(),
                error=False,
            )

    cold = story.get("cold_open")
    if not isinstance(cold, dict):
        cold = {}
        _issue(
            issues,
            "VQ-LONGFORM-HOOK",
            "cold_open must be an object",
            f"{STORY_MAP_PATH.as_posix()}:cold_open",
        )
    for field in ("anomaly", "result_glimpse", "episode_promise"):
        if not _nonempty(cold.get(field)):
            _issue(
                issues,
                "VQ-LONGFORM-HOOK",
                f"cold_open.{field} must be non-empty",
                f"{STORY_MAP_PATH.as_posix()}:cold_open.{field}",
            )
    cold_sources = cold.get("sources")
    if not isinstance(cold_sources, list) or not cold_sources:
        _issue(
            issues,
            "VQ-LONGFORM-HOOK",
            "cold open needs real failure and payoff sources",
            f"{STORY_MAP_PATH.as_posix()}:cold_open.sources",
        )
        cold_sources = []
    cold_roles = {
        str(item.get("role"))
        for item in cold_sources
        if isinstance(item, dict)
    }
    for role in ("failure", "payoff"):
        if role not in cold_roles:
            _issue(
                issues,
                "VQ-LONGFORM-HOOK",
                f"cold open source role is missing: {role}",
                f"{STORY_MAP_PATH.as_posix()}:cold_open.sources",
            )
    for index, source in enumerate(cold_sources):
        _validate_source(
            source,
            root=root,
            where=f"{STORY_MAP_PATH.as_posix()}:cold_open.sources[{index}]",
            strict=strict,
            issues=issues,
        )

    raw_arcs = story.get("mini_arcs")
    if not isinstance(raw_arcs, list):
        _issue(
            issues,
            "VQ-LONGFORM-STORY",
            "mini_arcs must be an array",
            f"{STORY_MAP_PATH.as_posix()}:mini_arcs",
        )
        raw_arcs = []
    minimum = max(4, math.ceil(duration / 90)) if duration else 4
    if len(raw_arcs) < minimum:
        _issue(
            issues,
            "VQ-LONGFORM-STORY",
            f"{len(raw_arcs)} mini-arcs supplied; {duration:g}s needs at least {minimum}",
            f"{STORY_MAP_PATH.as_posix()}:mini_arcs",
            error=strict,
        )

    arc_ids: set[str] = set()
    arc_sources: dict[str, set[str]] = {}
    prior_end = 0.0
    for index, arc in enumerate(raw_arcs):
        where = f"{STORY_MAP_PATH.as_posix()}:mini_arcs[{index}]"
        if not isinstance(arc, dict):
            _issue(issues, "VQ-LONGFORM-STORY", "mini-arc must be an object", where)
            continue
        for field in REQUIRED_ARC_FIELDS:
            if not _nonempty(arc.get(field)):
                _issue(
                    issues,
                    "VQ-LONGFORM-STORY",
                    f"{field} must be non-empty",
                    f"{where}.{field}",
                )
        arc_id = str(arc.get("id") or "")
        if arc_id in arc_ids:
            _issue(issues, "VQ-LONGFORM-STORY", "duplicate mini-arc id", arc_id)
        if arc_id:
            arc_ids.add(arc_id)

        start = arc.get("planned_start_seconds")
        end = arc.get("planned_end_seconds")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            _issue(
                issues,
                "VQ-LONGFORM-STORY",
                "planned start/end must be numeric",
                where,
            )
        elif float(end) <= float(start):
            _issue(issues, "VQ-LONGFORM-STORY", "arc end must follow start", where)
        elif float(start) < prior_end:
            _issue(
                issues,
                "VQ-LONGFORM-STORY",
                f"arc starts at {start}, before prior arc ends at {prior_end:g}",
                where,
            )
        else:
            prior_end = float(end)
            if float(end) - float(start) > 100:
                _issue(
                    issues,
                    "VQ-LONGFORM-STORY",
                    "mini-arc exceeds 100s; split it or add an internal payoff",
                    where,
                    error=False,
                )

        raw_sources = arc.get("sources")
        if not isinstance(raw_sources, list) or not raw_sources:
            _issue(
                issues,
                "VQ-LONGFORM-SOURCE",
                "mini-arc evidence sources are required",
                f"{where}.sources",
            )
            raw_sources = []
        roles = {
            str(item.get("role"))
            for item in raw_sources
            if isinstance(item, dict)
        }
        for role in ("before", "payoff"):
            if role not in roles:
                _issue(
                    issues,
                    "VQ-LONGFORM-PROOF",
                    f"story source role is missing: {role}",
                    arc_id or where,
                )
        if not roles.intersection({"failure", "process"}):
            _issue(
                issues,
                "VQ-LONGFORM-PROOF",
                "add failure or process evidence; result-only is a status report",
                arc_id or where,
            )
        paths: set[str] = set()
        for source_index, source in enumerate(raw_sources):
            _validate_source(
                source,
                root=root,
                where=f"{where}.sources[{source_index}]",
                strict=strict,
                issues=issues,
            )
            if isinstance(source, dict) and _nonempty(source.get("path")):
                paths.add(str(source["path"]).replace("\\", "/"))
        if arc_id:
            arc_sources[arc_id] = paths

    ending = story.get("ending")
    if not isinstance(ending, dict):
        ending = {}
        _issue(
            issues,
            "VQ-LONGFORM-END",
            "ending must be an object",
            f"{STORY_MAP_PATH.as_posix()}:ending",
        )
    for field in ("resolved_question", "honest_status", "next_open_loop"):
        if not _nonempty(ending.get(field)):
            _issue(
                issues,
                "VQ-LONGFORM-END",
                f"ending.{field} must be non-empty",
                f"{STORY_MAP_PATH.as_posix()}:ending.{field}",
            )
    return arc_ids, arc_sources, duration


def _float(value: Any) -> float | None:
    if not isinstance(value, (int, float)):
        return None
    return float(value)


def _validate_montage(
    montage: dict[str, Any],
    *,
    arc_ids: set[str],
    arc_sources: dict[str, set[str]],
    strict: bool,
    issues: list[CheckIssue],
) -> None:
    if montage.get("profile") != "longform_devlog":
        _issue(
            issues,
            "VQ-LONGFORM-MONTAGE",
            "profile must be 'longform_devlog'",
            SHOT_MANIFEST_PATH.as_posix(),
        )
    shots = montage.get("shots")
    if not isinstance(shots, list):
        _issue(
            issues,
            "VQ-LONGFORM-MONTAGE",
            "shots must be an array",
            f"{SHOT_MANIFEST_PATH.as_posix()}:shots",
        )
        shots = []
    if not shots:
        _issue(
            issues,
            "VQ-LONGFORM-MONTAGE",
            "montage has no shots",
            f"{SHOT_MANIFEST_PATH.as_posix()}:shots",
        )

    roles_by_arc: dict[str, set[str]] = {}
    sources_by_arc: dict[str, set[str]] = {}
    visual_modes: set[str] = set()
    ordered: list[tuple[float, float, str, str]] = []
    ids: set[str] = set()
    for index, shot in enumerate(shots):
        where = f"{SHOT_MANIFEST_PATH.as_posix()}:shots[{index}]"
        if not isinstance(shot, dict):
            _issue(issues, "VQ-LONGFORM-MONTAGE", "shot must be an object", where)
            continue
        shot_id = str(shot.get("id") or "")
        if not shot_id:
            _issue(issues, "VQ-LONGFORM-MONTAGE", "shot id is required", where)
            shot_id = where
        elif shot_id in ids:
            _issue(issues, "VQ-LONGFORM-MONTAGE", "duplicate shot id", shot_id)
        ids.add(shot_id)

        arc_id = str(shot.get("arc_id") or "")
        valid_arc_ids = arc_ids | {"cold_open", "ending"}
        if arc_id not in valid_arc_ids:
            _issue(
                issues,
                "VQ-LONGFORM-MONTAGE",
                f"arc_id must name cold_open, ending, or a story-map arc: {arc_id!r}",
                shot_id,
            )
        role = str(shot.get("story_role") or "")
        if role not in STORY_ROLES:
            _issue(
                issues,
                "VQ-LONGFORM-MONTAGE",
                f"story_role must be one of {sorted(STORY_ROLES)}",
                shot_id,
            )
        mode = str(shot.get("visual_mode") or "")
        if mode not in VISUAL_MODES:
            _issue(
                issues,
                "VQ-LONGFORM-MONTAGE",
                f"visual_mode must be one of {sorted(VISUAL_MODES)}",
                shot_id,
            )
        else:
            visual_modes.add(mode)
        for field in ("purpose", "vo_range", "src", "motion", "presentation"):
            if not _nonempty(shot.get(field)):
                _issue(
                    issues,
                    "VQ-LONGFORM-MONTAGE",
                    f"{field} is required",
                    shot_id,
                )

        start = _float(shot.get("t0"))
        end = _float(shot.get("t1"))
        if start is None or end is None or end <= start:
            _issue(
                issues,
                "VQ-LONGFORM-MONTAGE",
                "shot t0/t1 must be numeric and increasing",
                shot_id,
            )
            continue
        ordered.append((start, end, mode, shot_id))
        duration = end - start
        if duration > 8:
            raw_changes = shot.get("internal_changes_seconds")
            changes = sorted(
                float(value)
                for value in raw_changes
                if isinstance(value, (int, float)) and start < float(value) < end
            ) if isinstance(raw_changes, list) else []
            gaps = [
                right - left
                for left, right in zip([start, *changes], [*changes, end])
            ]
            if not changes or max(gaps, default=duration) > 6:
                _issue(
                    issues,
                    "VQ-LONGFORM-CADENCE",
                    (
                        f"{duration:.1f}s master shot needs declared semantic "
                        "changes with no gap above 6s"
                    ),
                    shot_id,
                    error=strict,
                )

        if arc_id:
            roles_by_arc.setdefault(arc_id, set()).add(role)
            if role in SOURCE_ROLES and _nonempty(shot.get("src")):
                sources_by_arc.setdefault(arc_id, set()).add(
                    str(shot["src"]).replace("\\", "/")
                )

    cold_roles = roles_by_arc.get("cold_open", set())
    for role in ("failure", "payoff"):
        if role not in cold_roles:
            _issue(
                issues,
                "VQ-LONGFORM-HOOK",
                f"cold-open montage role is missing: {role}",
                "cold_open",
            )
    cold_shots = [
        item for item in shots
        if isinstance(item, dict) and item.get("arc_id") == "cold_open"
    ]
    if cold_shots and not all(
        isinstance(item.get("t0"), (int, float)) and float(item["t0"]) < 8
        for item in cold_shots
        if item.get("story_role") in {"failure", "payoff"}
    ):
        _issue(
            issues,
            "VQ-LONGFORM-HOOK",
            "failure and payoff glimpse must begin before 0:08",
            "cold_open",
        )

    for arc_id in sorted(arc_ids):
        roles = roles_by_arc.get(arc_id, set())
        missing = {"before", "payoff"} - roles
        if missing:
            _issue(
                issues,
                "VQ-LONGFORM-PROOF",
                f"montage roles missing: {', '.join(sorted(missing))}",
                arc_id,
            )
        if not roles.intersection({"failure", "process"}):
            _issue(
                issues,
                "VQ-LONGFORM-PROOF",
                "montage needs failure or process proof",
                arc_id,
            )
        if strict:
            declared = arc_sources.get(arc_id, set())
            used = sources_by_arc.get(arc_id, set())
            if declared and not used.issubset(declared):
                _issue(
                    issues,
                    "VQ-LONGFORM-SOURCE",
                    "montage uses a source not bound to this story-map arc",
                    arc_id,
                )

    if len(visual_modes) < 4:
        _issue(
            issues,
            "VQ-LONGFORM-VISUAL-MODE",
            f"only {len(visual_modes)} visual modes planned; target at least 4",
            f"{SHOT_MANIFEST_PATH.as_posix()}:shots",
            error=False,
        )

    ordered.sort()
    run_start = 0
    while run_start < len(ordered):
        run_end = run_start + 1
        while run_end < len(ordered) and ordered[run_end][2] == ordered[run_start][2]:
            run_end += 1
        run = ordered[run_start:run_end]
        if len(run) >= 3 and run[-1][1] - run[0][0] > 12:
            _issue(
                issues,
                "VQ-LONGFORM-VISUAL-MODE",
                (
                    f"{run[-1][1] - run[0][0]:.1f}s remains in visual mode "
                    f"{run[0][2]!r} across {len(run)} shots"
                ),
                run[0][3],
                error=False,
            )
        run_start = run_end

    music = montage.get("music_phases")
    music_count = len(music) if isinstance(music, list) else 0
    if not 2 <= music_count <= 3:
        _issue(
            issues,
            "VQ-LONGFORM-AUDIO",
            f"plan 2–3 music phases; got {music_count}",
            f"{SHOT_MANIFEST_PATH.as_posix()}:music_phases",
            error=False,
        )
    sfx = montage.get("sfx_cues")
    sfx_count = len(sfx) if isinstance(sfx, list) else 0
    if not 8 <= sfx_count <= 15:
        _issue(
            issues,
            "VQ-LONGFORM-AUDIO",
            f"plan roughly 8–15 purposeful stingers/SFX; got {sfx_count}",
            f"{SHOT_MANIFEST_PATH.as_posix()}:sfx_cues",
            error=False,
        )


def run_longform_preflight(
    root: str | Path,
    *,
    strict: bool,
) -> CheckReport:
    base = Path(root).resolve()
    issues: list[CheckIssue] = []
    story = _read_object(base / STORY_MAP_PATH, "VQ-LONGFORM-STORY", issues)
    montage = _read_object(
        base / SHOT_MANIFEST_PATH,
        "VQ-LONGFORM-MONTAGE",
        issues,
    )
    if story is None or montage is None:
        return CheckReport(issues=issues)
    arc_ids, arc_sources, _duration = _validate_story_map(
        base,
        story,
        strict=strict,
        issues=issues,
    )
    _validate_montage(
        montage,
        arc_ids=arc_ids,
        arc_sources=arc_sources,
        strict=strict,
        issues=issues,
    )
    return CheckReport(issues=issues)


__all__ = [
    "SHOT_MANIFEST_PATH",
    "STORY_MAP_PATH",
    "longform_shot_manifest_template",
    "longform_story_map_template",
    "run_longform_preflight",
]
