"""SQLite persistence for Pattern Lab research data.

The database is local to the workspace, uses WAL for resilient concurrent reads,
and keeps the former JSON document only as a one-time migration input.
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterator


SCHEMA_VERSION = 1
LEGACY_SCHEMA = "dlstudio.research/v1"


class ResearchDatabaseError(RuntimeError):
    """Raised when the research database cannot be initialized or migrated."""


def database_path(workspace_root: Path) -> Path:
    return workspace_root.resolve() / "data" / "research" / "research.sqlite3"


def legacy_store_path(workspace_root: Path) -> Path:
    return workspace_root.resolve() / "data" / "research" / "index.json"


SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS schema_migrations (
    version INTEGER PRIMARY KEY,
    applied_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS projects (
    id TEXT PRIMARY KEY,
    title TEXT NOT NULL,
    description TEXT NOT NULL DEFAULT '',
    style_profile TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS authors (
    project_id TEXT NOT NULL,
    id TEXT NOT NULL,
    username TEXT NOT NULL,
    display_name TEXT NOT NULL DEFAULT '',
    profile_url TEXT NOT NULL DEFAULT '',
    followers_count INTEGER,
    median_views INTEGER,
    PRIMARY KEY (project_id, id),
    UNIQUE (project_id, username),
    FOREIGN KEY (project_id) REFERENCES projects(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reels (
    project_id TEXT NOT NULL,
    id TEXT NOT NULL,
    author_id TEXT NOT NULL,
    platform TEXT NOT NULL DEFAULT 'instagram',
    url TEXT NOT NULL,
    caption TEXT NOT NULL DEFAULT '',
    thumbnail_url TEXT NOT NULL DEFAULT '',
    published_at TEXT NOT NULL,
    duration_seconds REAL,
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    metrics_captured_at TEXT NOT NULL,
    hook TEXT NOT NULL DEFAULT '',
    PRIMARY KEY (project_id, id),
    FOREIGN KEY (project_id, author_id)
        REFERENCES authors(project_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reel_metrics (
    project_id TEXT NOT NULL,
    reel_id TEXT NOT NULL,
    captured_at TEXT NOT NULL,
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    PRIMARY KEY (project_id, reel_id, captured_at),
    FOREIGN KEY (project_id, reel_id)
        REFERENCES reels(project_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS reel_patterns (
    project_id TEXT NOT NULL,
    reel_id TEXT NOT NULL,
    position INTEGER NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (project_id, reel_id, position),
    FOREIGN KEY (project_id, reel_id)
        REFERENCES reels(project_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS experiments (
    id TEXT PRIMARY KEY,
    project_id TEXT NOT NULL,
    reel_id TEXT NOT NULL,
    mode TEXT NOT NULL CHECK (mode IN ('inspiration', 'adaptation', 'remake')),
    status TEXT NOT NULL,
    hypothesis TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL,
    agent_context_path TEXT NOT NULL,
    FOREIGN KEY (project_id, reel_id)
        REFERENCES reels(project_id, id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS experiment_items (
    experiment_id TEXT NOT NULL,
    kind TEXT NOT NULL CHECK (kind IN ('take', 'keep')),
    position INTEGER NOT NULL,
    value TEXT NOT NULL,
    PRIMARY KEY (experiment_id, kind, position),
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
);
CREATE TABLE IF NOT EXISTS experiment_results (
    experiment_id TEXT PRIMARY KEY,
    verdict TEXT NOT NULL CHECK (
        verdict IN ('worked', 'mixed', 'did_not_work', 'inconclusive')
    ),
    published_url TEXT NOT NULL DEFAULT '',
    views INTEGER NOT NULL DEFAULT 0,
    likes INTEGER NOT NULL DEFAULT 0,
    comments INTEGER NOT NULL DEFAULT 0,
    notes TEXT NOT NULL DEFAULT '',
    measured_at TEXT NOT NULL,
    FOREIGN KEY (experiment_id) REFERENCES experiments(id) ON DELETE CASCADE
);
CREATE INDEX IF NOT EXISTS idx_reels_project_published
    ON reels(project_id, published_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_reels_project_views
    ON reels(project_id, views DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_reels_author_published
    ON reels(project_id, author_id, published_at DESC, id DESC);
CREATE INDEX IF NOT EXISTS idx_metrics_reel_captured
    ON reel_metrics(project_id, reel_id, captured_at DESC);
CREATE INDEX IF NOT EXISTS idx_experiments_project_reel
    ON experiments(project_id, reel_id);
"""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def _configure(connection: sqlite3.Connection) -> None:
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    connection.execute("PRAGMA busy_timeout = 5000")
    connection.execute("PRAGMA synchronous = NORMAL")


def _initialize(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA journal_mode = WAL")
    connection.executescript(SCHEMA_SQL)
    connection.execute(
        "INSERT OR IGNORE INTO schema_migrations(version, applied_at) VALUES (?, ?)",
        (SCHEMA_VERSION, _utc_now()),
    )
    connection.execute(f"PRAGMA user_version = {SCHEMA_VERSION}")
    connection.commit()


def _connect_raw(workspace_root: Path) -> sqlite3.Connection:
    path = database_path(workspace_root)
    path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(path, timeout=5.0)
    _configure(connection)
    version = connection.execute("PRAGMA user_version").fetchone()[0]
    if version > SCHEMA_VERSION:
        connection.close()
        raise ResearchDatabaseError(
            f"research database schema {version} is newer than supported {SCHEMA_VERSION}"
        )
    if version < SCHEMA_VERSION:
        _initialize(connection)
    return connection


@contextmanager
def connect(workspace_root: Path) -> Iterator[sqlite3.Connection]:
    connection = _connect_raw(workspace_root)
    try:
        _migrate_legacy_json(workspace_root, connection)
        yield connection
    finally:
        connection.close()


def _insert_payload(connection: sqlite3.Connection, payload: dict[str, Any]) -> None:
    for project in payload.get("projects", []):
        connection.execute(
            "INSERT INTO projects(id, title, description, style_profile, created_at) VALUES (?, ?, ?, ?, ?)",
            (
                project["id"], project["title"], project.get("description", ""),
                project.get("style_profile", ""), project.get("created_at") or _utc_now(),
            ),
        )
        for author in project.get("authors", []):
            connection.execute(
                """INSERT INTO authors(
                    project_id, id, username, display_name, profile_url,
                    followers_count, median_views
                ) VALUES (?, ?, ?, ?, ?, ?, ?)""",
                (
                    project["id"], author["id"], author["username"],
                    author.get("display_name", ""), author.get("profile_url", ""),
                    author.get("followers_count"), author.get("median_views"),
                ),
            )
        for reel in project.get("reels", []):
            captured_at = reel.get("metrics_captured_at") or reel["published_at"]
            connection.execute(
                """INSERT INTO reels(
                    project_id, id, author_id, platform, url, caption, thumbnail_url,
                    published_at, duration_seconds, views, likes, comments,
                    metrics_captured_at, hook
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    project["id"], reel["id"], reel["author_id"],
                    reel.get("platform", "instagram"), reel["url"], reel.get("caption", ""),
                    reel.get("thumbnail_url", ""), reel["published_at"],
                    reel.get("duration_seconds"), reel.get("views", 0), reel.get("likes", 0),
                    reel.get("comments", 0), captured_at, reel.get("hook", ""),
                ),
            )
            history = reel.get("metrics_history") or [{
                "captured_at": captured_at,
                "views": reel.get("views", 0),
                "likes": reel.get("likes", 0),
                "comments": reel.get("comments", 0),
            }]
            for snapshot in history:
                connection.execute(
                    """INSERT OR REPLACE INTO reel_metrics(
                        project_id, reel_id, captured_at, views, likes, comments
                    ) VALUES (?, ?, ?, ?, ?, ?)""",
                    (
                        project["id"], reel["id"], snapshot["captured_at"],
                        snapshot.get("views", 0), snapshot.get("likes", 0),
                        snapshot.get("comments", 0),
                    ),
                )
            for position, pattern in enumerate(reel.get("patterns", [])):
                connection.execute(
                    "INSERT INTO reel_patterns(project_id, reel_id, position, value) VALUES (?, ?, ?, ?)",
                    (project["id"], reel["id"], position, pattern),
                )
        for experiment in project.get("experiments", []):
            connection.execute(
                """INSERT INTO experiments(
                    id, project_id, reel_id, mode, status, hypothesis, created_at,
                    agent_context_path
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                (
                    experiment["id"], project["id"], experiment["reel_id"],
                    experiment["mode"], experiment.get("status", "idea"),
                    experiment.get("hypothesis", ""), experiment.get("created_at") or _utc_now(),
                    experiment.get("agent_context_path", ""),
                ),
            )
            for kind, key in (("take", "take_from_reference"), ("keep", "keep_original")):
                for position, value in enumerate(experiment.get(key, [])):
                    connection.execute(
                        "INSERT INTO experiment_items(experiment_id, kind, position, value) VALUES (?, ?, ?, ?)",
                        (experiment["id"], kind, position, value),
                    )
            result = experiment.get("result")
            if result:
                connection.execute(
                    """INSERT INTO experiment_results(
                        experiment_id, verdict, published_url, views, likes, comments,
                        notes, measured_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        experiment["id"], result["verdict"], result.get("published_url", ""),
                        result.get("views", 0), result.get("likes", 0),
                        result.get("comments", 0), result.get("notes", ""),
                        result["measured_at"],
                    ),
                )


def _migrate_legacy_json(workspace_root: Path, connection: sqlite3.Connection) -> None:
    source = legacy_store_path(workspace_root)
    if not source.is_file():
        return
    if connection.execute("SELECT EXISTS(SELECT 1 FROM projects)").fetchone()[0]:
        return
    try:
        payload = json.loads(source.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ResearchDatabaseError(f"cannot read legacy research store: {exc}") from exc
    if not isinstance(payload, dict) or payload.get("schema") != LEGACY_SCHEMA:
        raise ResearchDatabaseError("unsupported legacy research store schema")
    try:
        with connection:
            _insert_payload(connection, payload)
    except (KeyError, TypeError, sqlite3.DatabaseError) as exc:
        raise ResearchDatabaseError(f"cannot migrate legacy research store: {exc}") from exc

    backups = source.parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    target = backups / f"index-v1-imported-{stamp}.json"
    counter = 2
    while target.exists():
        target = backups / f"index-v1-imported-{stamp}-{counter}.json"
        counter += 1
    source.replace(target)


def backup_before_write(workspace_root: Path, connection: sqlite3.Connection) -> None:
    if not connection.execute("SELECT EXISTS(SELECT 1 FROM projects)").fetchone()[0]:
        return
    backups = database_path(workspace_root).parent / "backups"
    backups.mkdir(parents=True, exist_ok=True)
    target = backups / f"research-{date.today().isoformat()}.sqlite3"
    if target.exists():
        return
    with sqlite3.connect(target) as destination:
        connection.backup(destination)
    for stale in sorted(backups.glob("research-*.sqlite3"), reverse=True)[14:]:
        stale.unlink(missing_ok=True)


def experiment_from_row(
    connection: sqlite3.Connection,
    row: sqlite3.Row,
) -> dict[str, Any]:
    items = connection.execute(
        """SELECT kind, value FROM experiment_items
        WHERE experiment_id = ? ORDER BY kind, position""",
        (row["id"],),
    ).fetchall()
    result = connection.execute(
        "SELECT * FROM experiment_results WHERE experiment_id = ?",
        (row["id"],),
    ).fetchone()
    return {
        "id": row["id"],
        "reel_id": row["reel_id"],
        "mode": row["mode"],
        "status": row["status"],
        "hypothesis": row["hypothesis"],
        "take_from_reference": [item["value"] for item in items if item["kind"] == "take"],
        "keep_original": [item["value"] for item in items if item["kind"] == "keep"],
        "created_at": row["created_at"],
        "agent_context_path": row["agent_context_path"],
        "result": None if result is None else {
            "verdict": result["verdict"],
            "published_url": result["published_url"],
            "views": result["views"],
            "likes": result["likes"],
            "comments": result["comments"],
            "notes": result["notes"],
            "measured_at": result["measured_at"],
        },
    }


def load_payload(workspace_root: Path) -> dict[str, Any]:
    with connect(workspace_root) as connection:
        projects: list[dict[str, Any]] = []
        for project_row in connection.execute("SELECT * FROM projects ORDER BY created_at, id"):
            project_id = project_row["id"]
            authors = [
                dict(row)
                for row in connection.execute(
                    """SELECT id, username, display_name, profile_url,
                    followers_count, median_views FROM authors
                    WHERE project_id = ? ORDER BY rowid""",
                    (project_id,),
                )
            ]
            reels: list[dict[str, Any]] = []
            for reel_row in connection.execute(
                "SELECT * FROM reels WHERE project_id = ? ORDER BY rowid",
                (project_id,),
            ):
                history = [
                    dict(row)
                    for row in connection.execute(
                        """SELECT captured_at, views, likes, comments FROM reel_metrics
                        WHERE project_id = ? AND reel_id = ? ORDER BY captured_at""",
                        (project_id, reel_row["id"]),
                    )
                ]
                patterns = [
                    row["value"]
                    for row in connection.execute(
                        """SELECT value FROM reel_patterns
                        WHERE project_id = ? AND reel_id = ? ORDER BY position""",
                        (project_id, reel_row["id"]),
                    )
                ]
                reels.append({
                    key: reel_row[key]
                    for key in (
                        "id", "author_id", "platform", "url", "caption", "thumbnail_url",
                        "published_at", "duration_seconds", "views", "likes", "comments",
                        "metrics_captured_at", "hook",
                    )
                } | {"metrics_history": history, "patterns": patterns})
            experiments = [
                experiment_from_row(connection, row)
                for row in connection.execute(
                    "SELECT * FROM experiments WHERE project_id = ? ORDER BY created_at, id",
                    (project_id,),
                )
            ]
            projects.append({
                "id": project_id,
                "title": project_row["title"],
                "description": project_row["description"],
                "style_profile": project_row["style_profile"],
                "created_at": project_row["created_at"],
                "authors": authors,
                "reels": reels,
                "experiments": experiments,
            })
        return {"schema": LEGACY_SCHEMA, "projects": projects}


def replace_payload(workspace_root: Path, payload: dict[str, Any]) -> None:
    if not isinstance(payload, dict) or payload.get("schema") != LEGACY_SCHEMA:
        raise ResearchDatabaseError("unsupported research payload schema")
    with connect(workspace_root) as connection:
        backup_before_write(workspace_root, connection)
        try:
            with connection:
                connection.execute("DELETE FROM projects")
                _insert_payload(connection, payload)
        except (KeyError, TypeError, sqlite3.DatabaseError) as exc:
            raise ResearchDatabaseError(f"cannot persist research database: {exc}") from exc


def _rows_by_reel(
    connection: sqlite3.Connection,
    table: str,
    columns: str,
    project_id: str,
    reel_ids: list[str],
    order_by: str,
) -> dict[str, list[sqlite3.Row]]:
    grouped = {reel_id: [] for reel_id in reel_ids}
    if not reel_ids:
        return grouped
    placeholders = ",".join("?" for _ in reel_ids)
    rows = connection.execute(
        f"SELECT reel_id, {columns} FROM {table} "
        f"WHERE project_id = ? AND reel_id IN ({placeholders}) ORDER BY {order_by}",
        (project_id, *reel_ids),
    )
    for row in rows:
        grouped[row["reel_id"]].append(row)
    return grouped


def get_feed_page(
    workspace_root: Path,
    project_id: str,
    *,
    cutoff_iso: str | None,
    sort: str,
    author_id: str | None,
    now_iso: str,
    limit: int,
    cursor_value: str | float | int | None,
    cursor_id: str | None,
) -> dict[str, Any]:
    sort_expression = {
        "newest": "r.published_at",
        "views": "CAST(r.views AS REAL)",
        "outlier": "CASE WHEN a.median_views > 0 THEN CAST(r.views AS REAL) / a.median_views ELSE -1.0 END",
        "velocity": """CASE
            WHEN d.previous_captured_at IS NOT NULL THEN
                CAST(r.views - d.previous_views AS REAL) /
                MAX((julianday(r.metrics_captured_at) - julianday(d.previous_captured_at)) * 24.0, 1.0 / 60.0)
            ELSE CAST(r.views AS REAL) /
                MAX((julianday(:now_iso) - julianday(r.published_at)) * 24.0, 1.0 / 60.0)
            END""",
    }.get(sort)
    if sort_expression is None:
        raise ResearchDatabaseError(f"unsupported feed sort: {sort}")

    filters = ["r.project_id = :project_id"]
    parameters: dict[str, Any] = {
        "project_id": project_id,
        "now_iso": now_iso,
        "limit": limit + 1,
    }
    if cutoff_iso is not None:
        filters.append("r.published_at >= :cutoff_iso")
        parameters["cutoff_iso"] = cutoff_iso
    if author_id is not None:
        filters.append("r.author_id = :author_id")
        parameters["author_id"] = author_id
    page_filter = ""
    if cursor_value is not None and cursor_id is not None:
        page_filter = """WHERE (
            sort_value < :cursor_value OR
            (sort_value = :cursor_value AND id < :cursor_id)
        )"""
        parameters["cursor_value"] = cursor_value
        parameters["cursor_id"] = cursor_id

    metric_cte = """
        metric_ranked AS (
            SELECT project_id, reel_id, captured_at, views,
                ROW_NUMBER() OVER (
                    PARTITION BY project_id, reel_id ORDER BY captured_at DESC
                ) AS rank
            FROM reel_metrics
            WHERE project_id = :project_id
        ),
        metric_delta AS (
            SELECT project_id, reel_id,
                MAX(CASE WHEN rank = 2 THEN captured_at END) AS previous_captured_at,
                MAX(CASE WHEN rank = 2 THEN views END) AS previous_views
            FROM metric_ranked
            WHERE rank <= 2
            GROUP BY project_id, reel_id
        )
    """
    base_cte = f"""
        base AS (
            SELECT r.*, {sort_expression} AS sort_value,
                a.username AS author_username,
                a.display_name AS author_display_name,
                a.profile_url AS author_profile_url,
                a.followers_count AS author_followers_count,
                a.median_views AS author_median_views,
                d.previous_captured_at,
                d.previous_views
            FROM reels r
            JOIN authors a ON a.project_id = r.project_id AND a.id = r.author_id
            LEFT JOIN metric_delta d
                ON d.project_id = r.project_id AND d.reel_id = r.id
            WHERE {' AND '.join(filters)}
        )
    """
    with connect(workspace_root) as connection:
        project = connection.execute(
            "SELECT * FROM projects WHERE id = ?", (project_id,)
        ).fetchone()
        if project is None:
            raise ResearchDatabaseError(f"unknown research project: {project_id}")
        authors = [
            dict(row)
            for row in connection.execute(
                """SELECT id, username, display_name, profile_url,
                followers_count, median_views FROM authors
                WHERE project_id = ? ORDER BY rowid""",
                (project_id,),
            )
        ]
        total = connection.execute(
            f"SELECT count(*) FROM reels r WHERE {' AND '.join(filters)}",
            parameters,
        ).fetchone()[0]
        rows = connection.execute(
            f"WITH {metric_cte}, {base_cte} SELECT * FROM base {page_filter} "
            "ORDER BY sort_value DESC, id DESC LIMIT :limit",
            parameters,
        ).fetchall()
        has_more = len(rows) > limit
        rows = rows[:limit]
        reel_ids = [row["id"] for row in rows]
        metrics = _rows_by_reel(
            connection, "reel_metrics", "captured_at, views, likes, comments",
            project_id, reel_ids, "reel_id, captured_at",
        )
        patterns = _rows_by_reel(
            connection, "reel_patterns", "position, value",
            project_id, reel_ids, "reel_id, position",
        )

        experiments_by_reel: dict[str, dict[str, Any]] = {}
        experiments: list[dict[str, Any]] = []
        if reel_ids:
            placeholders = ",".join("?" for _ in reel_ids)
            experiment_rows = connection.execute(
                f"""SELECT * FROM experiments WHERE project_id = ?
                AND reel_id IN ({placeholders}) ORDER BY created_at, id""",
                (project_id, *reel_ids),
            ).fetchall()
            for experiment_row in experiment_rows:
                experiment = experiment_from_row(connection, experiment_row)
                experiments.append(experiment)
                experiments_by_reel[experiment["reel_id"]] = experiment

        reels = []
        for row in rows:
            history = [
                {
                    "captured_at": item["captured_at"],
                    "views": item["views"],
                    "likes": item["likes"],
                    "comments": item["comments"],
                }
                for item in metrics[row["id"]]
            ]
            reels.append({
                key: row[key]
                for key in (
                    "id", "author_id", "platform", "url", "caption", "thumbnail_url",
                    "published_at", "duration_seconds", "views", "likes", "comments",
                    "metrics_captured_at", "hook",
                )
            } | {
                "metrics_history": history,
                "patterns": [item["value"] for item in patterns[row["id"]]],
                "author": {
                    "id": row["author_id"],
                    "username": row["author_username"],
                    "display_name": row["author_display_name"],
                    "profile_url": row["author_profile_url"],
                    "followers_count": row["author_followers_count"],
                    "median_views": row["author_median_views"],
                },
                "experiment": experiments_by_reel.get(row["id"]),
                "sort_value": row["sort_value"],
            })
        counts = connection.execute(
            """SELECT
                (SELECT count(*) FROM authors WHERE project_id = ?) AS authors,
                (SELECT count(*) FROM reels WHERE project_id = ?) AS reels,
                (SELECT count(*) FROM experiments WHERE project_id = ?) AS experiments""",
            (project_id, project_id, project_id),
        ).fetchone()
        return {
            "project": dict(project),
            "authors": authors,
            "reels": reels,
            "experiments": experiments,
            "counts": dict(counts),
            "total": total,
            "has_more": has_more,
        }
