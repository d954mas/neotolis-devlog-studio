from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from dlstudio.services import research


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


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

    all_time = research.get_project_feed(tmp_path, project_id, window="all", now=NOW)
    assert [item["id"] for item in all_time["reels"]] == ["old-hit", "fresh-hit"]


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
