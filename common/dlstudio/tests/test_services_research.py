from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from dlstudio.services import research


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def test_research_uses_a_normalized_sqlite_database(tmp_path):
    project = research.create_project(tmp_path, title="Gamedev", now=NOW)
    research.add_author(tmp_path, project["id"], username="creator")
    research.ingest_reel(
        tmp_path,
        project["id"],
        reel_id="first-reel",
        author_id="creator",
        url="https://www.instagram.com/reel/first-reel/",
        published_at="2026-07-18T12:00:00Z",
        views=1_000,
        patterns=["failure first", "fast reveal"],
        metrics_captured_at="2026-07-19T12:00:00Z",
    )

    database = tmp_path / "data" / "research" / "research.sqlite3"
    assert database.is_file()
    with sqlite3.connect(database) as connection:
        assert connection.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
        assert connection.execute("PRAGMA foreign_key_list('reels')").fetchall()
        tables = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            )
        }
        assert {
            "schema_migrations",
            "projects",
            "authors",
            "reels",
            "reel_metrics",
            "reel_patterns",
            "experiments",
            "experiment_items",
            "experiment_results",
        }.issubset(tables)
        assert connection.execute("SELECT count(*) FROM reels").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM reel_patterns").fetchone()[0] == 2


def test_existing_json_store_is_migrated_once_without_data_loss(tmp_path):
    source = tmp_path / "data" / "research" / "index.json"
    source.parent.mkdir(parents=True)
    source.write_text(
        json.dumps(
            {
                "schema": "dlstudio.research/v1",
                "projects": [
                    {
                        "id": "gamedev",
                        "title": "Gamedev",
                        "description": "Learn",
                        "style_profile": "Keep our voice",
                        "created_at": "2026-07-19T12:00:00Z",
                        "authors": [
                            {
                                "id": "creator",
                                "username": "creator",
                                "display_name": "Creator",
                                "profile_url": "https://www.instagram.com/creator/",
                                "followers_count": 100,
                                "median_views": 500,
                            }
                        ],
                        "reels": [
                            {
                                "id": "legacy-reel",
                                "author_id": "creator",
                                "platform": "instagram",
                                "url": "https://www.instagram.com/reel/legacy-reel/",
                                "caption": "Legacy caption",
                                "thumbnail_url": "",
                                "published_at": "2026-07-18T12:00:00Z",
                                "duration_seconds": 20,
                                "views": 2_000,
                                "likes": 100,
                                "comments": 5,
                                "metrics_captured_at": "2026-07-19T12:00:00Z",
                                "metrics_history": [
                                    {
                                        "captured_at": "2026-07-19T12:00:00Z",
                                        "views": 2_000,
                                        "likes": 100,
                                        "comments": 5,
                                    }
                                ],
                                "hook": "Legacy hook",
                                "patterns": ["legacy pattern"],
                            }
                        ],
                        "experiments": [],
                    }
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    first = research.get_project_feed(tmp_path, "gamedev", now=NOW)
    second = research.get_project_feed(tmp_path, "gamedev", now=NOW)

    assert [item["id"] for item in first["reels"]] == ["legacy-reel"]
    assert [item["id"] for item in second["reels"]] == ["legacy-reel"]
    assert first["reels"][0]["patterns"] == ["legacy pattern"]
    assert (tmp_path / "data" / "research" / "research.sqlite3").is_file()
    imported = list((tmp_path / "data" / "research" / "backups").glob("index-v1-imported-*.json"))
    assert len(imported) == 1
    assert not source.exists()


def test_legacy_research_import_rejects_path_traversal_project_id(tmp_path):
    source = tmp_path / "data" / "research" / "index.json"
    source.parent.mkdir(parents=True)
    source.write_text(json.dumps({
        "schema": "dlstudio.research/v1",
        "projects": [{
            "id": "../../escape",
            "title": "Unsafe",
            "created_at": "2026-07-19T12:00:00Z",
            "authors": [],
            "reels": [],
            "experiments": [],
        }],
    }), encoding="utf-8")

    with pytest.raises(research.ResearchError, match="unsafe id"):
        research.load_store(tmp_path)
    assert not (tmp_path / "escape" / "README.md").exists()


def test_project_brief_resolver_rejects_linked_project_root(tmp_path):
    projects = tmp_path / "data" / "research" / "projects"
    projects.mkdir(parents=True)
    outside = tmp_path / "outside"
    outside.mkdir()
    linked = projects / "gamedev"
    try:
        linked.symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("directory symlinks are unavailable")

    with pytest.raises(research.ResearchError, match="link/junction"):
        research._resolve_project_brief(tmp_path, "gamedev")


def test_store_keeps_a_daily_local_database_backup(tmp_path):
    project = research.create_project(tmp_path, title="Gamedev", now=NOW)

    research.add_author(tmp_path, project["id"], username="creator")

    backups = list((tmp_path / "data" / "research" / "backups").glob("research-*.sqlite3"))
    assert len(backups) == 1
    with sqlite3.connect(backups[0]) as connection:
        assert connection.execute("SELECT count(*) FROM projects").fetchone()[0] == 1
        assert connection.execute("SELECT count(*) FROM authors").fetchone()[0] == 0


def _seed(root: Path) -> str:
    project = research.create_project(
        root,
        title="Gamedev",
        description="Learn short-form storytelling",
        style_profile="Dry humour, real gameplay, no fake claims.",
        now=NOW,
    )
    research.add_author(
        root,
        project["id"],
        username="topdev",
        followers_count=100_000,
        median_views=20_000,
    )
    return project["id"]


def test_feed_filters_by_window_and_ranks_relative_outliers(tmp_path):
    project_id = _seed(tmp_path)
    research.ingest_reel(
        tmp_path,
        project_id,
        reel_id="fresh-hit",
        author_id="topdev",
        url="https://www.instagram.com/reel/fresh-hit/",
        published_at="2026-07-18T12:00:00Z",
        views=100_000,
        hook="I broke the cart physics",
    )
    research.ingest_reel(
        tmp_path,
        project_id,
        reel_id="old-hit",
        author_id="topdev",
        url="https://www.instagram.com/reel/old-hit/",
        published_at="2026-05-01T12:00:00Z",
        views=300_000,
    )

    recent = research.get_project_feed(tmp_path, project_id, window="7d", now=NOW)
    assert [item["id"] for item in recent["reels"]] == ["fresh-hit"]
    assert recent["reels"][0]["outlier_score"] == 5.0
    assert recent["reels"][0]["views_per_hour"] == pytest.approx(4166.7)

    all_time = research.get_project_feed(
        tmp_path,
        project_id,
        window="all",
        sort="outlier",
        now=NOW,
    )
    assert [item["id"] for item in all_time["reels"]] == ["old-hit", "fresh-hit"]

    historical = research.get_project_feed(tmp_path, project_id, now=NOW)
    assert historical["window"] == "all"
    assert historical["sort"] == "newest"
    assert [item["id"] for item in historical["reels"]] == ["fresh-hit", "old-hit"]


def test_experiment_defaults_to_adaptation_and_writes_agent_context(tmp_path):
    project_id = _seed(tmp_path)
    research.ingest_reel(
        tmp_path,
        project_id,
        reel_id="cart-hook",
        author_id="topdev",
        url="https://www.instagram.com/reel/cart-hook/",
        published_at="2026-07-18T12:00:00Z",
        views=120_000,
        hook="I broke the cart physics",
    )

    experiment = research.create_experiment(
        tmp_path,
        project_id,
        reel_id="cart-hook",
        hypothesis="Showing the broken mechanic first improves the hook.",
        take_from_reference=["problem in the first second", "failure to fix arc"],
        keep_original=["our gameplay", "our dry humour"],
        now=NOW,
    )

    assert experiment["mode"] == "adaptation"
    context = tmp_path / experiment["agent_context_path"]
    assert context.is_file()
    text = context.read_text(encoding="utf-8")
    assert "@topdev" in text
    assert "Showing the broken mechanic first" in text
    assert "our dry humour" in text
    assert "research evidence, not as a target to copy" in text

    measured = research.record_experiment_result(
        tmp_path,
        project_id,
        experiment["id"],
        verdict="worked",
        published_url="https://www.instagram.com/reel/our-version/",
        views=42_000,
        likes=2_100,
        notes="The failure-first opening held attention.",
        measured_at="2026-07-26T12:00:00Z",
    )
    assert measured["status"] == "measured"
    assert measured["result"]["verdict"] == "worked"
    updated_context = context.read_text(encoding="utf-8")
    assert "## Result" in updated_context
    assert "The failure-first opening held attention" in updated_context
    assert "status: measured" in updated_context
    brief = tmp_path / "data/research/projects/gamedev/README.md"
    brief_text = brief.read_text(encoding="utf-8")
    assert "Dry humour, real gameplay" in brief_text
    assert experiment["id"] in brief_text
    assert experiment["agent_context_path"] in brief_text
    assert "measured experiment results are evidence" in brief_text.lower()


def test_experiment_db_insert_rolls_back_when_agent_context_write_fails(
    tmp_path,
    monkeypatch,
):
    project_id = _seed(tmp_path)
    research.ingest_reel(
        tmp_path,
        project_id,
        reel_id="context-failure",
        author_id="topdev",
        url="https://www.instagram.com/reel/context-failure/",
        published_at="2026-07-18T12:00:00Z",
    )
    monkeypatch.setattr(
        research,
        "_write_experiment_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        research.create_experiment(
            tmp_path,
            project_id,
            reel_id="context-failure",
        )

    with sqlite3.connect(research.store_path(tmp_path)) as connection:
        assert connection.execute(
            "SELECT COUNT(*) FROM experiments WHERE project_id = ?",
            (project_id,),
        ).fetchone()[0] == 0


def test_experiment_result_rolls_back_when_context_refresh_fails(
    tmp_path,
    monkeypatch,
):
    project_id = _seed(tmp_path)
    research.ingest_reel(
        tmp_path,
        project_id,
        reel_id="result-context-failure",
        author_id="topdev",
        url="https://www.instagram.com/reel/result-context-failure/",
        published_at="2026-07-18T12:00:00Z",
    )
    experiment = research.create_experiment(
        tmp_path,
        project_id,
        reel_id="result-context-failure",
    )
    monkeypatch.setattr(
        research,
        "_write_experiment_context",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("disk full")),
    )

    with pytest.raises(OSError, match="disk full"):
        research.record_experiment_result(
            tmp_path,
            project_id,
            experiment["id"],
            verdict="worked",
        )

    with sqlite3.connect(research.store_path(tmp_path)) as connection:
        row = connection.execute(
            "SELECT status FROM experiments WHERE id = ?",
            (experiment["id"],),
        ).fetchone()
        result_count = connection.execute(
            "SELECT COUNT(*) FROM experiment_results WHERE experiment_id = ?",
            (experiment["id"],),
        ).fetchone()[0]
    assert row[0] == "idea"
    assert result_count == 0


def test_project_and_author_ids_are_stable_and_duplicates_rejected(tmp_path):
    first = research.create_project(tmp_path, title="Game Dev", now=NOW)
    second = research.create_project(tmp_path, title="Game Dev", now=NOW)
    assert first["id"] == "game-dev"
    assert second["id"] == "game-dev-2"

    research.add_author(tmp_path, first["id"], username="@Creator")
    with pytest.raises(research.ResearchError, match="already exists"):
        research.add_author(tmp_path, first["id"], username="creator")


def test_remove_author_cascades_imported_reels(tmp_path):
    project_id = _seed(tmp_path)
    research.ingest_reel(
        tmp_path,
        project_id,
        reel_id="wrong-reference",
        author_id="topdev",
        url="https://www.instagram.com/reel/wrong-reference/",
        published_at="2026-07-18T12:00:00Z",
        views=100,
    )

    removed = research.remove_author(tmp_path, project_id, "topdev")

    assert removed == {
        "author_id": "topdev",
        "reels_removed": 1,
        "experiments_removed": 0,
    }
    feed = research.get_project_feed(tmp_path, project_id, window="all", now=NOW)
    assert feed["authors"] == []
    assert feed["reels"] == []


def test_repeated_ingest_keeps_metric_history_and_calculates_growth(tmp_path):
    project_id = _seed(tmp_path)
    common = {
        "reel_id": "growing-reel",
        "author_id": "topdev",
        "url": "https://www.instagram.com/reel/growing-reel/",
        "published_at": "2026-07-19T06:00:00Z",
    }
    research.ingest_reel(
        tmp_path,
        project_id,
        **common,
        views=10_000,
        likes=700,
        hook="Original hook analysis",
        patterns=["failure first"],
        metrics_captured_at="2026-07-19T08:00:00Z",
    )
    research.ingest_reel(
        tmp_path,
        project_id,
        **common,
        views=16_000,
        likes=1_100,
        metrics_captured_at="2026-07-19T12:00:00Z",
    )

    reel = research.get_project_feed(tmp_path, project_id, now=NOW)["reels"][0]
    assert len(reel["metrics_history"]) == 2
    assert reel["growth_views"] == 6_000
    assert reel["growth_hours"] == 4
    assert reel["growth_per_hour"] == 1_500
    assert reel["velocity"] == 1_500
    assert reel["metrics_age_hours"] == 0
    assert reel["hook"] == "Original hook analysis"
    assert reel["patterns"] == ["failure first"]


def test_feed_uses_stable_cursor_pagination(tmp_path):
    project_id = _seed(tmp_path)
    for index in range(35):
        research.ingest_reel(
            tmp_path,
            project_id,
            reel_id=f"reel-{index:03d}",
            author_id="topdev",
            url=f"https://www.instagram.com/reel/{index:03d}/",
            published_at=f"2026-07-{(index % 19) + 1:02d}T12:00:00Z",
            views=1_000 + index,
        )

    first = research.get_project_feed(tmp_path, project_id, limit=20, now=NOW)
    second = research.get_project_feed(
        tmp_path,
        project_id,
        limit=20,
        cursor=first["page"]["next_cursor"],
        now=NOW,
    )

    first_ids = {item["id"] for item in first["reels"]}
    second_ids = {item["id"] for item in second["reels"]}
    assert len(first_ids) == 20
    assert len(second_ids) == 15
    assert first_ids.isdisjoint(second_ids)
    assert first["page"] == {
        "limit": 20,
        "total": 35,
        "has_more": True,
        "next_cursor": first["page"]["next_cursor"],
    }
    assert second["page"]["has_more"] is False
    assert second["page"]["next_cursor"] is None

    for sort in ("views", "outlier", "velocity"):
        ranked_first = research.get_project_feed(
            tmp_path, project_id, sort=sort, limit=20, now=NOW
        )
        ranked_second = research.get_project_feed(
            tmp_path,
            project_id,
            sort=sort,
            limit=20,
            cursor=ranked_first["page"]["next_cursor"],
            now=NOW,
        )
        ranked_ids = [item["id"] for item in ranked_first["reels"] + ranked_second["reels"]]
        assert len(ranked_ids) == 35
        assert len(set(ranked_ids)) == 35

    with pytest.raises(research.ResearchError, match="invalid feed cursor"):
        research.get_project_feed(tmp_path, project_id, cursor="not-a-cursor", now=NOW)


def test_feed_normalizes_offsets_and_orders_by_absolute_instant(tmp_path):
    project_id = _seed(tmp_path)
    research.ingest_reel(
        tmp_path,
        project_id,
        reel_id="offset-older",
        author_id="topdev",
        url="https://www.instagram.com/reel/offset-older/",
        published_at="2026-07-19T12:00:00+05:00",
        metrics_captured_at="2026-07-19T13:00:00+05:00",
    )
    research.ingest_reel(
        tmp_path,
        project_id,
        reel_id="utc-newer",
        author_id="topdev",
        url="https://www.instagram.com/reel/utc-newer/",
        published_at="2026-07-19T08:00:00Z",
    )

    feed = research.get_project_feed(tmp_path, project_id, limit=20, now=NOW)
    selected = [item for item in feed["reels"] if item["id"] in {"offset-older", "utc-newer"}]
    assert [item["id"] for item in selected] == ["utc-newer", "offset-older"]
    assert selected[1]["published_at"] == "2026-07-19T07:00:00Z"
    assert selected[1]["metrics_captured_at"] == "2026-07-19T08:00:00Z"


def test_experiment_context_paths_cannot_escape_project(tmp_path):
    project_id = _seed(tmp_path)
    research.ingest_reel(
        tmp_path,
        project_id,
        reel_id="reference",
        author_id="topdev",
        url="https://www.instagram.com/reel/reference/",
        published_at="2026-07-18T12:00:00Z",
    )
    experiment = research.create_experiment(
        tmp_path,
        project_id,
        reel_id="reference",
        hypothesis="safe path",
    )
    victim = tmp_path.parent / "victim.md"
    victim.write_text("keep", encoding="utf-8")
    database = tmp_path / "data" / "research" / "research.sqlite3"
    with sqlite3.connect(database) as connection:
        connection.execute(
            "UPDATE experiments SET agent_context_path = ? WHERE id = ?",
            ("../../victim.md", experiment["id"]),
        )
        connection.commit()

    with pytest.raises(research.ResearchError, match="unsafe experiment context"):
        research.record_experiment_result(
            tmp_path,
            project_id,
            experiment["id"],
            verdict="worked",
        )
    with pytest.raises(research.ResearchError, match="unsafe experiment context"):
        research.remove_author(tmp_path, project_id, "topdev")
    assert victim.read_text(encoding="utf-8") == "keep"
