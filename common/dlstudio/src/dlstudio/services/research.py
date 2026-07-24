"""Persistent research projects for the Studio content-learning workflow.

SQLite is the source of truth. Human- and agent-readable Markdown briefs are
derived artifacts and can always be regenerated from the database.
"""
from __future__ import annotations

import base64
import json
import math
import re
import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from dlstudio.services import research_database


SCHEMA = "dlstudio.research/v1"
WINDOWS = {"7d": 7, "30d": 30, "90d": 90, "all": None}
SORTS = {"outlier", "velocity", "views", "newest"}
MODES = {"inspiration", "adaptation", "remake"}
VERDICTS = {"worked", "mixed", "did_not_work", "inconclusive"}


class ResearchError(ValueError):
    """Raised for invalid research operations or missing records."""


def store_path(workspace_root: Path) -> Path:
    return research_database.database_path(workspace_root)


def _empty_store() -> dict[str, Any]:
    return {"schema": SCHEMA, "projects": []}


def load_store(workspace_root: Path) -> dict[str, Any]:
    try:
        return research_database.load_payload(workspace_root)
    except research_database.ResearchDatabaseError as exc:
        raise ResearchError(f"cannot read research store: {exc}") from exc


def save_store(workspace_root: Path, payload: dict[str, Any]) -> None:
    try:
        research_database.replace_payload(workspace_root, payload)
    except research_database.ResearchDatabaseError as exc:
        raise ResearchError(str(exc)) from exc


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
    with research_database.connect(workspace_root) as connection:
        rows = connection.execute("""
            SELECT p.id, p.title, p.description,
                (SELECT count(*) FROM authors a WHERE a.project_id = p.id) AS author_count,
                (SELECT count(*) FROM reels r WHERE r.project_id = p.id) AS reel_count,
                (SELECT count(*) FROM experiments e WHERE e.project_id = p.id) AS experiment_count
            FROM projects p ORDER BY p.created_at, p.id
        """).fetchall()
    return [dict(row) | {"agent_brief_path": _project_brief_path(row["id"]).as_posix()} for row in rows]


def create_project(
    workspace_root: Path,
    *,
    title: str,
    description: str = "",
    style_profile: str = "",
    now: datetime | None = None,
) -> dict[str, Any]:
    base = _slug(title)
    with research_database.connect(workspace_root) as connection:
        existing = {row[0] for row in connection.execute("SELECT id FROM projects")}
        project_id = base
        counter = 2
        while project_id in existing:
            project_id = f"{base}-{counter}"
            counter += 1
        created_at = _now_iso(now)
        research_database.backup_before_write(workspace_root, connection)
        with connection:
            connection.execute(
                "INSERT INTO projects(id, title, description, style_profile, created_at) VALUES (?, ?, ?, ?, ?)",
                (project_id, title.strip(), description.strip(), style_profile.strip(), created_at),
            )
    project = {
        "id": project_id,
        "title": title.strip(),
        "description": description.strip(),
        "style_profile": style_profile.strip(),
        "created_at": created_at,
        "authors": [],
        "reels": [],
        "experiments": [],
    }
    _write_project_brief(workspace_root, project)
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
    normalized = username.strip().lstrip("@").lower()
    if not normalized:
        raise ResearchError("username must be non-empty")
    author = {
        "id": normalized,
        "username": normalized,
        "display_name": display_name.strip(),
        "profile_url": profile_url.strip() or f"https://www.instagram.com/{normalized}/",
        "followers_count": followers_count,
        "median_views": median_views,
    }
    with research_database.connect(workspace_root) as connection:
        if connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
            raise ResearchError(f"unknown research project: {project_id}")
        research_database.backup_before_write(workspace_root, connection)
        try:
            with connection:
                connection.execute(
                    """INSERT INTO authors(
                        project_id, id, username, display_name, profile_url,
                        followers_count, median_views
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                    (
                        project_id, author["id"], author["username"], author["display_name"],
                        author["profile_url"], followers_count, median_views,
                    ),
                )
        except sqlite3.IntegrityError as exc:
            raise ResearchError(f"author already exists: {normalized}") from exc
    snapshot = load_store(workspace_root)
    _write_project_brief(workspace_root, _project(snapshot, project_id))
    return author


def refresh_author_medians(
    workspace_root: Path,
    project_id: str,
    author_ids: list[str] | None = None,
) -> dict[str, int | None]:
    """Recompute typical views from the collected non-zero Reel snapshots."""
    with research_database.connect(workspace_root) as connection:
        if connection.execute("SELECT 1 FROM projects WHERE id = ?", (project_id,)).fetchone() is None:
            raise ResearchError(f"unknown research project: {project_id}")
        known = {
            row[0] for row in connection.execute(
                "SELECT id FROM authors WHERE project_id = ?", (project_id,)
            )
        }
        selected = set(author_ids) if author_ids is not None else known
        unknown = selected.difference(known)
        if unknown:
            raise ResearchError(f"unknown author: {sorted(unknown)[0]}")
        research_database.backup_before_write(workspace_root, connection)
        medians: dict[str, int | None] = {}
        with connection:
            for author_id in selected:
                views = [
                    row[0] for row in connection.execute(
                        """SELECT views FROM reels WHERE project_id = ? AND author_id = ?
                        AND views > 0 ORDER BY views""",
                        (project_id, author_id),
                    )
                ]
                midpoint = len(views) // 2
                if not views:
                    median = None
                elif len(views) % 2:
                    median = views[midpoint]
                else:
                    median = round((views[midpoint - 1] + views[midpoint]) / 2)
                connection.execute(
                    "UPDATE authors SET median_views = ? WHERE project_id = ? AND id = ?",
                    (median, project_id, author_id),
                )
                medians[author_id] = median
    snapshot = load_store(workspace_root)
    _write_project_brief(workspace_root, _project(snapshot, project_id))
    return medians


def remove_author(workspace_root: Path, project_id: str, author_id: str) -> dict[str, Any]:
    """Remove a tracked author and the references derived from that source."""
    with research_database.connect(workspace_root) as connection:
        if connection.execute(
            "SELECT 1 FROM authors WHERE project_id = ? AND id = ?", (project_id, author_id)
        ).fetchone() is None:
            raise ResearchError(f"unknown author: {author_id}")
        reel_count = connection.execute(
            "SELECT count(*) FROM reels WHERE project_id = ? AND author_id = ?",
            (project_id, author_id),
        ).fetchone()[0]
        contexts = [
            row[0] for row in connection.execute(
                """SELECT e.agent_context_path FROM experiments e
                JOIN reels r ON r.project_id = e.project_id AND r.id = e.reel_id
                WHERE r.project_id = ? AND r.author_id = ?""",
                (project_id, author_id),
            )
        ]
        research_database.backup_before_write(workspace_root, connection)
        with connection:
            connection.execute(
                "DELETE FROM authors WHERE project_id = ? AND id = ?", (project_id, author_id)
            )
    for context in contexts:
        if context:
            (workspace_root.resolve() / context).unlink(missing_ok=True)
    snapshot = load_store(workspace_root)
    _write_project_brief(workspace_root, _project(snapshot, project_id))
    return {
        "author_id": author_id,
        "reels_removed": reel_count,
        "experiments_removed": len(contexts),
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
    _parse_time(published_at)
    if metrics_captured_at:
        _parse_time(metrics_captured_at)
    captured_at = metrics_captured_at or _now_iso()
    with research_database.connect(workspace_root) as connection:
        if connection.execute(
            "SELECT 1 FROM authors WHERE project_id = ? AND id = ?", (project_id, author_id)
        ).fetchone() is None:
            raise ResearchError(f"unknown author: {author_id}")
        existing_row = connection.execute(
            "SELECT * FROM reels WHERE project_id = ? AND id = ?", (project_id, reel_id)
        ).fetchone()
        existing = dict(existing_row) if existing_row is not None else {}
        current_patterns = [
            row[0] for row in connection.execute(
                """SELECT value FROM reel_patterns WHERE project_id = ? AND reel_id = ?
                ORDER BY position""",
                (project_id, reel_id),
            )
        ]
        reel = {
            "id": reel_id,
            "author_id": author_id,
            "platform": platform or existing.get("platform", "instagram"),
            "url": url,
            "caption": caption or existing.get("caption", ""),
            "thumbnail_url": thumbnail_url or existing.get("thumbnail_url", ""),
            "published_at": published_at,
            "duration_seconds": duration_seconds if duration_seconds is not None else existing.get("duration_seconds"),
            "views": views,
            "likes": likes,
            "comments": comments,
            "metrics_captured_at": captured_at,
            "hook": hook or existing.get("hook", ""),
            "patterns": list(patterns) if patterns else current_patterns,
        }
        research_database.backup_before_write(workspace_root, connection)
        with connection:
            connection.execute(
                """INSERT INTO reels(
                    project_id, id, author_id, platform, url, caption, thumbnail_url,
                    published_at, duration_seconds, views, likes, comments,
                    metrics_captured_at, hook
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(project_id, id) DO UPDATE SET
                    author_id=excluded.author_id, platform=excluded.platform, url=excluded.url,
                    caption=excluded.caption, thumbnail_url=excluded.thumbnail_url,
                    published_at=excluded.published_at, duration_seconds=excluded.duration_seconds,
                    views=excluded.views, likes=excluded.likes, comments=excluded.comments,
                    metrics_captured_at=excluded.metrics_captured_at, hook=excluded.hook""",
                (
                    project_id, reel_id, author_id, reel["platform"], url, reel["caption"],
                    reel["thumbnail_url"], published_at, reel["duration_seconds"], views,
                    likes, comments, captured_at, reel["hook"],
                ),
            )
            connection.execute(
                """INSERT OR REPLACE INTO reel_metrics(
                    project_id, reel_id, captured_at, views, likes, comments
                ) VALUES (?, ?, ?, ?, ?, ?)""",
                (project_id, reel_id, captured_at, views, likes, comments),
            )
            if patterns:
                connection.execute(
                    "DELETE FROM reel_patterns WHERE project_id = ? AND reel_id = ?",
                    (project_id, reel_id),
                )
                connection.executemany(
                    "INSERT INTO reel_patterns(project_id, reel_id, position, value) VALUES (?, ?, ?, ?)",
                    [(project_id, reel_id, position, value) for position, value in enumerate(patterns)],
                )
        history = [
            dict(row) for row in connection.execute(
                """SELECT captured_at, views, likes, comments FROM reel_metrics
                WHERE project_id = ? AND reel_id = ? ORDER BY captured_at""",
                (project_id, reel_id),
            )
        ]
    return reel | {"metrics_history": history}


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
    window: Literal["7d", "30d", "90d", "all"] = "all",
    sort: Literal["outlier", "velocity", "views", "newest"] = "newest",
    author_id: str | None = None,
    now: datetime | None = None,
    limit: int = 60,
    cursor: str | None = None,
) -> dict[str, Any]:
    if window not in WINDOWS:
        raise ResearchError(f"unsupported window: {window}")
    if sort not in SORTS:
        raise ResearchError(f"unsupported sort: {sort}")
    if limit < 1 or limit > 100:
        raise ResearchError("feed limit must be between 1 and 100")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    current = current.astimezone(timezone.utc)
    cursor_value: str | float | int | None = None
    cursor_id: str | None = None
    if cursor:
        try:
            padded = cursor + "=" * (-len(cursor) % 4)
            decoded = json.loads(base64.urlsafe_b64decode(padded).decode("utf-8"))
            if decoded.get("sort") != sort:
                raise ValueError("cursor sort mismatch")
            cursor_value = decoded["value"]
            cursor_id = str(decoded["id"])
            if sort == "newest":
                if not isinstance(cursor_value, str):
                    raise ValueError("cursor value must be a timestamp")
            elif (
                not isinstance(cursor_value, (int, float))
                or isinstance(cursor_value, bool)
                or not math.isfinite(float(cursor_value))
            ):
                raise ValueError("cursor value must be finite")
            if not cursor_id or len(cursor_id) > 160:
                raise ValueError("cursor id is invalid")
        except (ValueError, KeyError, TypeError, json.JSONDecodeError) as exc:
            raise ResearchError("invalid feed cursor") from exc
    cutoff_days = WINDOWS[window]
    cutoff_iso = _now_iso(current - timedelta(days=cutoff_days)) if cutoff_days else None
    try:
        page = research_database.get_feed_page(
            workspace_root,
            project_id,
            cutoff_iso=cutoff_iso,
            sort=sort,
            author_id=author_id,
            now_iso=_now_iso(current),
            limit=limit,
            cursor_value=cursor_value,
            cursor_id=cursor_id,
        )
    except research_database.ResearchDatabaseError as exc:
        raise ResearchError(str(exc)) from exc
    project = page["project"]
    brief_path = workspace_root.resolve() / _project_brief_path(project_id)
    if not brief_path.is_file():
        snapshot = load_store(workspace_root)
        _write_project_brief(workspace_root, _project(snapshot, project_id))
    raw_reels = page["reels"]
    reels = []
    for reel in raw_reels:
        sort_value = reel.pop("sort_value")
        enriched = _enrich_reel(reel, reel["author"], reel.get("experiment"), current)
        enriched["_sort_value"] = sort_value
        reels.append(enriched)
    next_cursor = None
    if page["has_more"] and reels:
        last = reels[-1]
        cursor_payload = json.dumps(
            {"sort": sort, "value": last.pop("_sort_value"), "id": last["id"]},
            separators=(",", ":"),
        ).encode("utf-8")
        next_cursor = base64.urlsafe_b64encode(cursor_payload).decode("ascii").rstrip("=")
    for reel in reels:
        reel.pop("_sort_value", None)
    return {
        "id": project["id"],
        "title": project["title"],
        "description": project.get("description", ""),
        "style_profile": project.get("style_profile", ""),
        "window": window,
        "sort": sort,
        "authors": page["authors"],
        "reels": reels,
        "experiments": page["experiments"],
        "counts": page["counts"],
        "page": {
            "limit": limit,
            "total": page["total"],
            "has_more": page["has_more"],
            "next_cursor": next_cursor,
        },
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
    with research_database.connect(workspace_root) as connection:
        project_row = connection.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        reel_row = connection.execute(
            "SELECT * FROM reels WHERE project_id = ? AND id = ?", (project_id, reel_id)
        ).fetchone()
        if project_row is None:
            raise ResearchError(f"unknown research project: {project_id}")
        if reel_row is None:
            raise ResearchError(f"unknown reel: {reel_id}")
        author_row = connection.execute(
            "SELECT * FROM authors WHERE project_id = ? AND id = ?",
            (project_id, reel_row["author_id"]),
        ).fetchone()
        research_database.backup_before_write(workspace_root, connection)
        with connection:
            connection.execute(
                """INSERT INTO experiments(
                    id, project_id, reel_id, mode, status, hypothesis, created_at,
                    agent_context_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    experiment_id, project_id, reel_id, mode, "idea",
                    experiment["hypothesis"], experiment["created_at"],
                    experiment["agent_context_path"],
                ),
            )
            items = [
                (experiment_id, kind, position, value)
                for kind, values in (
                    ("take", experiment["take_from_reference"]),
                    ("keep", experiment["keep_original"]),
                )
                for position, value in enumerate(values)
            ]
            if items:
                connection.executemany(
                    "INSERT INTO experiment_items(experiment_id, kind, position, value) VALUES (?, ?, ?, ?)",
                    items,
                )
    project = dict(project_row)
    reel = dict(reel_row)
    author = dict(author_row)
    context = _experiment_markdown(project, author, reel, experiment)
    context_path = workspace_root.resolve() / rel_context
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(context, encoding="utf-8", newline="\n")
    snapshot = load_store(workspace_root)
    _write_project_brief(workspace_root, _project(snapshot, project_id))
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
    timestamp = measured_at or _now_iso()
    _parse_time(timestamp)
    with research_database.connect(workspace_root) as connection:
        experiment_row = connection.execute(
            "SELECT * FROM experiments WHERE project_id = ? AND id = ?",
            (project_id, experiment_id),
        ).fetchone()
        if experiment_row is None:
            raise ResearchError(f"unknown experiment: {experiment_id}")
        project_row = connection.execute("SELECT * FROM projects WHERE id = ?", (project_id,)).fetchone()
        reel_row = connection.execute(
            "SELECT * FROM reels WHERE project_id = ? AND id = ?",
            (project_id, experiment_row["reel_id"]),
        ).fetchone()
        author_row = connection.execute(
            "SELECT * FROM authors WHERE project_id = ? AND id = ?",
            (project_id, reel_row["author_id"]),
        ).fetchone()
        research_database.backup_before_write(workspace_root, connection)
        with connection:
            connection.execute(
                "UPDATE experiments SET status = 'measured' WHERE id = ?", (experiment_id,)
            )
            connection.execute(
                """INSERT INTO experiment_results(
                    experiment_id, verdict, published_url, views, likes, comments,
                    notes, measured_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(experiment_id) DO UPDATE SET
                    verdict=excluded.verdict, published_url=excluded.published_url,
                    views=excluded.views, likes=excluded.likes, comments=excluded.comments,
                    notes=excluded.notes, measured_at=excluded.measured_at""",
                (
                    experiment_id, verdict, published_url.strip(), views, likes,
                    comments, notes.strip(), timestamp,
                ),
            )
        refreshed = connection.execute(
            "SELECT * FROM experiments WHERE id = ?", (experiment_id,)
        ).fetchone()
        experiment = research_database.experiment_from_row(connection, refreshed)
    project = dict(project_row)
    reel = dict(reel_row)
    author = dict(author_row)
    context_path = workspace_root.resolve() / experiment["agent_context_path"]
    context_path.parent.mkdir(parents=True, exist_ok=True)
    context_path.write_text(
        _experiment_markdown(project, author, reel, experiment),
        encoding="utf-8",
        newline="\n",
    )
    snapshot = load_store(workspace_root)
    _write_project_brief(workspace_root, _project(snapshot, project_id))
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
