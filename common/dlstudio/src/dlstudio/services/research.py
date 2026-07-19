"""Persistent research projects for the Studio content-learning workflow.

The store deliberately uses one small JSON document under the workspace's
``data/research`` directory.  Studio is a single-user localhost application,
so an atomic replace is sufficient and keeps the resulting research corpus
easy for both humans and agents to inspect.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4


SCHEMA = "dlstudio.research/v1"
WINDOWS = {"7d": 7, "30d": 30, "90d": 90, "all": None}
SORTS = {"outlier", "velocity", "views", "newest"}
MODES = {"inspiration", "adaptation", "remake"}
VERDICTS = {"worked", "mixed", "did_not_work", "inconclusive"}


class ResearchError(ValueError):
    """Raised for invalid research operations or missing records."""


def store_path(workspace_root: Path) -> Path:
    return workspace_root.resolve() / "data" / "research" / "index.json"


def _empty_store() -> dict[str, Any]:
    return {"schema": SCHEMA, "projects": []}


def load_store(workspace_root: Path) -> dict[str, Any]:
    path = store_path(workspace_root)
    if not path.is_file():
        return _empty_store()
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchError(f"cannot read research store: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != SCHEMA:
        raise ResearchError("unsupported research store schema")
    if not isinstance(payload.get("projects"), list):
        raise ResearchError("research store projects must be a list")
    return payload


def save_store(workspace_root: Path, payload: dict[str, Any]) -> None:
    path = store_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    body = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    fd, temp_name = tempfile.mkstemp(prefix="index-", suffix=".json.tmp", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8", newline="\n") as handle:
            handle.write(body)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temp_name, path)
    finally:
        Path(temp_name).unlink(missing_ok=True)


def _slug(value: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", value.strip().lower()).strip("-")
    return slug or "research"


def _now_iso(now: datetime | None = None) -> str:
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError as exc:
        raise ResearchError(f"invalid ISO timestamp: {value}") from exc
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _project(payload: dict[str, Any], project_id: str) -> dict[str, Any]:
    for project in payload["projects"]:
        if project.get("id") == project_id:
            return project
    raise ResearchError(f"unknown research project: {project_id}")


def _project_brief_path(project_id: str) -> Path:
    return Path("data") / "research" / "projects" / project_id / "README.md"


def _write_project_brief(workspace_root: Path, project: dict[str, Any]) -> None:
    authors = "\n".join(
        f"- @{item['username']} — typical views: {item.get('median_views') or 'unknown'}"
        for item in project.get("authors", [])
    ) or "- No authors tracked yet"
    ranked_reels = sorted(project.get("reels", []), key=lambda item: item.get("views", 0), reverse=True)
    reels = "\n".join(
        f"- [{item.get('hook') or item['id']}]({item['url']}) — {item.get('views', 0)} views"
        for item in ranked_reels[:20]
    ) or "- No references collected yet"
    experiments = "\n".join(
        f"- `{item['id']}` — {item['mode']} / {item['status']} — `{item['agent_context_path']}`"
        for item in project.get("experiments", [])
    ) or "- No experiments created yet"
    brief = f"""---
schema: dlstudio.research-project/v1
project: {project['id']}
---

# Research project: {project['title']}

## Goal

{project.get('description') or 'No research goal written yet.'}

## Original style contract

{project.get('style_profile') or 'Preserve the project voice, footage, visual style, and product truth.'}

## Tracked authors

{authors}

## Strong references

{reels}

## Research notes

- [Current findings](FINDINGS.md)

## Experiments

{experiments}

## Agent routing

When the user names an experiment, read its context file before proposing or
producing a Reel. Inspiration borrows an observation, adaptation tests a
pattern in the project's own style, and remake follows structure closely only
when explicitly selected. Never treat a reference as a target to copy by
default. Measured experiment results are evidence for the next iteration.
"""
    path = workspace_root.resolve() / _project_brief_path(project["id"])
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(brief, encoding="utf-8", newline="\n")


def list_projects(workspace_root: Path) -> list[dict[str, Any]]:
    payload = load_store(workspace_root)
    return [
        {
            "id": item["id"],
            "title": item["title"],
            "description": item.get("description", ""),
            "author_count": len(item.get("authors", [])),
            "reel_count": len(item.get("reels", [])),
            "experiment_count": len(item.get("experiments", [])),
            "agent_brief_path": _project_brief_path(item["id"]).as_posix(),
        }
        for item in payload["projects"]
    ]


def create_project(
    workspace_root: Path,
    *,
    title: str,
    description: str = "",
    style_profile: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    payload = load_store(workspace_root)
    base = _slug(title)
    existing = {item.get("id") for item in payload["projects"]}
    project_id = base
    counter = 2
    while project_id in existing:
        project_id = f"{base}-{counter}"
        counter += 1
    project = {
        "id": project_id,
        "title": title.strip(),
        "description": description.strip(),
        "style_profile": style_profile.strip(),
        "created_at": _now_iso(now),
        "authors": [],
        "reels": [],
        "experiments": [],
    }
    payload["projects"].append(project)
    _write_project_brief(workspace_root, project)
    save_store(workspace_root, payload)
    return project


def add_author(
    workspace_root: Path,
    project_id: str,
    *,
    username: str,
    display_name: str = "",
    profile_url: str = "",
    followers_count: int | None = None,
    median_views: int | None = None,
) -> dict[str, Any]:
    payload = load_store(workspace_root)
    project = _project(payload, project_id)
    normalized = username.strip().lstrip("@").lower()
    if not normalized:
        raise ResearchError("username must be non-empty")
    if any(item.get("id") == normalized for item in project["authors"]):
        raise ResearchError(f"author already exists: {normalized}")
    author = {
        "id": normalized,
        "username": normalized,
        "display_name": display_name.strip(),
        "profile_url": profile_url.strip() or f"https://www.instagram.com/{normalized}/",
        "followers_count": followers_count,
        "median_views": median_views,
    }
    project["authors"].append(author)
    _write_project_brief(workspace_root, project)
    save_store(workspace_root, payload)
    return author


def refresh_author_medians(
    workspace_root: Path,
    project_id: str,
    author_ids: list[str] | None = None,
) -> dict[str, int | None]:
    """Recompute typical views from the collected non-zero Reel snapshots."""
    payload = load_store(workspace_root)
    project = _project(payload, project_id)
    selected = set(author_ids) if author_ids is not None else {
        str(item["id"]) for item in project["authors"]
    }
    unknown = selected.difference(str(item["id"]) for item in project["authors"])
    if unknown:
        raise ResearchError(f"unknown author: {sorted(unknown)[0]}")

    medians: dict[str, int | None] = {}
    for author in project["authors"]:
        author_id = str(author["id"])
        if author_id not in selected:
            continue
        views = sorted(
            int(reel.get("views", 0))
            for reel in project["reels"]
            if reel.get("author_id") == author_id and int(reel.get("views", 0)) > 0
        )
        midpoint = len(views) // 2
        if not views:
            median = None
        elif len(views) % 2:
            median = views[midpoint]
        else:
            median = round((views[midpoint - 1] + views[midpoint]) / 2)
        author["median_views"] = median
        medians[author_id] = median

    _write_project_brief(workspace_root, project)
    save_store(workspace_root, payload)
    return medians


def remove_author(workspace_root: Path, project_id: str, author_id: str) -> dict[str, Any]:
    """Remove a tracked author and the references derived from that source."""
    payload = load_store(workspace_root)
    project = _project(payload, project_id)
    author = next((item for item in project["authors"] if item.get("id") == author_id), None)
    if author is None:
        raise ResearchError(f"unknown author: {author_id}")
    reel_ids = {
        item["id"] for item in project["reels"] if item.get("author_id") == author_id
    }
    removed_experiments = [
        item for item in project["experiments"] if item.get("reel_id") in reel_ids
    ]
    project["authors"] = [item for item in project["authors"] if item.get("id") != author_id]
    project["reels"] = [item for item in project["reels"] if item.get("author_id") != author_id]
    project["experiments"] = [
        item for item in project["experiments"] if item.get("reel_id") not in reel_ids
    ]
    for experiment in removed_experiments:
        context = experiment.get("agent_context_path")
        if isinstance(context, str) and context:
            (workspace_root.resolve() / context).unlink(missing_ok=True)
    _write_project_brief(workspace_root, project)
    save_store(workspace_root, payload)
    return {
        "author_id": author_id,
        "reels_removed": len(reel_ids),
        "experiments_removed": len(removed_experiments),
    }


def ingest_reel(
    workspace_root: Path,
    project_id: str,
    *,
    reel_id: str,
    author_id: str,
    url: str,
    published_at: str,
    caption: str = "",
    thumbnail_url: str = "",
    duration_seconds: float | None = None,
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    hook: str = "",
    patterns: list[str] | None = None,
    metrics_captured_at: str | None = None,
    platform: str = "instagram",
) -> dict[str, Any]:
    payload = load_store(workspace_root)
    project = _project(payload, project_id)
    if not any(item.get("id") == author_id for item in project["authors"]):
        raise ResearchError(f"unknown author: {author_id}")
    _parse_time(published_at)
    if metrics_captured_at:
        _parse_time(metrics_captured_at)
    captured_at = metrics_captured_at or _now_iso()
    existing = next((item for item in project["reels"] if item.get("id") == reel_id), None)
    history = list(existing.get("metrics_history", [])) if existing else []
    if existing and not history:
        history.append({
            "captured_at": existing.get("metrics_captured_at", captured_at),
            "views": existing.get("views", 0),
            "likes": existing.get("likes", 0),
            "comments": existing.get("comments", 0),
        })
    snapshot = {
        "captured_at": captured_at,
        "views": views,
        "likes": likes,
        "comments": comments,
    }
    if history and history[-1].get("captured_at") == captured_at:
        history[-1] = snapshot
    else:
        history.append(snapshot)
    reel = {
        "id": reel_id,
        "author_id": author_id,
        "platform": platform or (existing.get("platform", "instagram") if existing else "instagram"),
        "url": url,
        "caption": caption or (existing.get("caption", "") if existing else ""),
        "thumbnail_url": thumbnail_url or (existing.get("thumbnail_url", "") if existing else ""),
        "published_at": published_at,
        "duration_seconds": duration_seconds if duration_seconds is not None else (existing.get("duration_seconds") if existing else None),
        "views": views,
        "likes": likes,
        "comments": comments,
        "metrics_captured_at": captured_at,
        "metrics_history": history,
        "hook": hook or (existing.get("hook", "") if existing else ""),
        "patterns": list(patterns) if patterns else list(existing.get("patterns", []) if existing else []),
    }
    for index, existing in enumerate(project["reels"]):
        if existing.get("id") == reel_id:
            project["reels"][index] = reel
            break
    else:
        project["reels"].append(reel)
    _write_project_brief(workspace_root, project)
    save_store(workspace_root, payload)
    return reel


def _enrich_reel(
    reel: dict[str, Any],
    author: dict[str, Any],
    experiment: dict[str, Any] | None,
    now: datetime,
) -> dict[str, Any]:
    published = _parse_time(str(reel["published_at"]))
    age_hours = max((now - published).total_seconds() / 3600.0, 1.0 / 60.0)
    median = author.get("median_views")
    outlier = round(reel.get("views", 0) / median, 2) if median and median > 0 else None
    captured_at = _parse_time(str(reel.get("metrics_captured_at") or reel["published_at"]))
    history = list(reel.get("metrics_history", []))
    if not history:
        history = [{
            "captured_at": reel.get("metrics_captured_at", reel["published_at"]),
            "views": reel.get("views", 0),
            "likes": reel.get("likes", 0),
            "comments": reel.get("comments", 0),
        }]
    growth_views: int | None = None
    growth_hours: float | None = None
    growth_per_hour: float | None = None
    if len(history) >= 2:
        previous = history[-2]
        previous_time = _parse_time(str(previous["captured_at"]))
        growth_hours = max((captured_at - previous_time).total_seconds() / 3600.0, 1.0 / 60.0)
        growth_views = reel.get("views", 0) - int(previous.get("views", 0))
        growth_per_hour = round(growth_views / growth_hours, 1)
    lifetime_velocity = round(reel.get("views", 0) / age_hours, 1)
    return {
        **reel,
        "metrics_history": history,
        "author": author,
        "age_hours": round(age_hours, 2),
        "metrics_age_hours": round(max((now - captured_at).total_seconds() / 3600.0, 0), 2),
        "views_per_hour": lifetime_velocity,
        "growth_views": growth_views,
        "growth_hours": round(growth_hours, 2) if growth_hours is not None else None,
        "growth_per_hour": growth_per_hour,
        "velocity": growth_per_hour if growth_per_hour is not None else lifetime_velocity,
        "outlier_score": outlier,
        "experiment": experiment,
    }


def get_project_feed(
    workspace_root: Path,
    project_id: str,
    *,
    window: Literal["7d", "30d", "90d", "all"] = "7d",
    sort: Literal["outlier", "velocity", "views", "newest"] = "outlier",
    author_id: str | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if window not in WINDOWS:
        raise ResearchError(f"unsupported window: {window}")
    if sort not in SORTS:
        raise ResearchError(f"unsupported sort: {sort}")
    payload = load_store(workspace_root)
    project = _project(payload, project_id)
    brief_path = workspace_root.resolve() / _project_brief_path(project_id)
    if not brief_path.is_file():
        _write_project_brief(workspace_root, project)
    authors = {item["id"]: item for item in project["authors"]}
    experiments = {item["reel_id"]: item for item in project["experiments"]}
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff_days = WINDOWS[window]
    reels: list[dict[str, Any]] = []
    for reel in project["reels"]:
        if author_id and reel.get("author_id") != author_id:
            continue
        published = _parse_time(str(reel["published_at"]))
        if cutoff_days is not None and (current - published).total_seconds() > cutoff_days * 86400:
            continue
        author = authors.get(reel.get("author_id"))
        if author is None:
            continue
        reels.append(_enrich_reel(reel, author, experiments.get(reel["id"]), current))
    key = {
        "outlier": lambda item: (item["outlier_score"] is not None, item["outlier_score"] or -1),
        "velocity": lambda item: item["velocity"],
        "views": lambda item: item["views"],
        "newest": lambda item: _parse_time(item["published_at"]).timestamp(),
    }[sort]
    reels.sort(key=key, reverse=True)
    return {
        "id": project["id"],
        "title": project["title"],
        "description": project.get("description", ""),
        "style_profile": project.get("style_profile", ""),
        "window": window,
        "sort": sort,
        "authors": project["authors"],
        "reels": reels,
        "experiments": project["experiments"],
        "agent_brief_path": _project_brief_path(project["id"]).as_posix(),
    }


def create_experiment(
    workspace_root: Path,
    project_id: str,
    *,
    reel_id: str,
    mode: Literal["inspiration", "adaptation", "remake"] = "adaptation",
    hypothesis: str = "",
    take_from_reference: list[str] | None = None,
    keep_original: list[str] | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    if mode not in MODES:
        raise ResearchError(f"unsupported experiment mode: {mode}")
    payload = load_store(workspace_root)
    project = _project(payload, project_id)
    reel = next((item for item in project["reels"] if item.get("id") == reel_id), None)
    if reel is None:
        raise ResearchError(f"unknown reel: {reel_id}")
    author = next(item for item in project["authors"] if item["id"] == reel["author_id"])
    experiment_id = f"exp-{_slug(reel_id)}-{uuid4().hex[:6]}"
    rel_context = Path("data") / "research" / "projects" / project_id / "experiments" / f"{experiment_id}.md"
    experiment = {
        "id": experiment_id,
        "reel_id": reel_id,
        "mode": mode,
        "status": "idea",
        "hypothesis": hypothesis.strip(),
        "take_from_reference": [item.strip() for item in (take_from_reference or []) if item.strip()],
        "keep_original": [item.strip() for item in (keep_original or []) if item.strip()],
        "created_at": _now_iso(now),
        "agent_context_path": rel_context.as_posix(),
        "result": None,
    }
    project["experiments"].append(experiment)
    context = _experiment_markdown(project, author, reel, experiment)
    context_path = workspace_root.resolve() / rel_context
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(context, encoding="utf-8", newline="\n")
    _write_project_brief(workspace_root, project)
    save_store(workspace_root, payload)
    return experiment


def record_experiment_result(
    workspace_root: Path,
    project_id: str,
    experiment_id: str,
    *,
    verdict: Literal["worked", "mixed", "did_not_work", "inconclusive"],
    published_url: str = "",
    views: int = 0,
    likes: int = 0,
    comments: int = 0,
    notes: str = "",
    measured_at: str | None = None,
) -> dict[str, Any]:
    if verdict not in VERDICTS:
        raise ResearchError(f"unsupported experiment verdict: {verdict}")
    payload = load_store(workspace_root)
    project = _project(payload, project_id)
    experiment = next(
        (item for item in project["experiments"] if item.get("id") == experiment_id),
        None,
    )
    if experiment is None:
        raise ResearchError(f"unknown experiment: {experiment_id}")
    timestamp = measured_at or _now_iso()
    _parse_time(timestamp)
    experiment["status"] = "measured"
    experiment["result"] = {
        "verdict": verdict,
        "published_url": published_url.strip(),
        "views": views,
        "likes": likes,
        "comments": comments,
        "notes": notes.strip(),
        "measured_at": timestamp,
    }
    reel = next(item for item in project["reels"] if item["id"] == experiment["reel_id"])
    author = next(item for item in project["authors"] if item["id"] == reel["author_id"])
    context_path = workspace_root.resolve() / experiment["agent_context_path"]
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(
        _experiment_markdown(project, author, reel, experiment),
        encoding="utf-8",
        newline="\n",
    )
    _write_project_brief(workspace_root, project)
    save_store(workspace_root, payload)
    return experiment


def _experiment_markdown(
    project: dict[str, Any],
    author: dict[str, Any],
    reel: dict[str, Any],
    experiment: dict[str, Any],
) -> str:
    take = "\n".join(f"- {item}" for item in experiment["take_from_reference"]) or "- Not specified yet"
    original = "\n".join(f"- {item}" for item in experiment["keep_original"]) or "- Project voice and visual style"
    result = experiment.get("result")
    result_section = ""
    if result:
        result_section = f"""
## Result

- Verdict: {result['verdict']}
- Published Reel: {result.get('published_url') or 'Not recorded'}
- Views at measurement: {result.get('views', 0)}
- Likes: {result.get('likes', 0)}
- Comments: {result.get('comments', 0)}
- Measured: {result['measured_at']}
- Notes: {result.get('notes') or 'No notes'}
"""
    return f"""---
schema: dlstudio.research-experiment/v1
id: {experiment['id']}
project: {project['id']}
mode: {experiment['mode']}
status: {experiment['status']}
created_at: {experiment['created_at']}
---

# Research experiment: {project['title']}

## Source

- Author: @{author['username']}
- Reel: {reel['url']}
- Views at capture: {reel['views']}
- Published: {reel['published_at']}
- Hook: {reel.get('hook') or 'Not transcribed yet'}

## Hypothesis

{experiment['hypothesis'] or 'Define the learning hypothesis before production.'}

## Take from the reference

{take}

## Keep original

{original}

## Project style profile

{project.get('style_profile') or 'No explicit profile yet. Preserve the project voice and product truth.'}
{result_section}

## Agent instruction

Use the source as research evidence, not as a target to copy. The experiment
mode controls similarity: inspiration borrows an observation, adaptation tests
a pattern in the project's own style, and remake follows the structure closely
only when explicitly selected.
"""
