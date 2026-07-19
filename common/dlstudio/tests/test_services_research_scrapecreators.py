from __future__ import annotations

from datetime import datetime, timezone

import pytest

from dlstudio.services import research, research_scrapecreators as collector


NOW = datetime(2026, 7, 19, 12, 0, tzinfo=timezone.utc)


def _seed(root):
    project = research.create_project(root, title="Gamedev", now=NOW)
    research.add_author(root, project["id"], username="topdev")
    return project["id"]


def _provider_page(*, views: int = 12_000, caption: str = "Failure first"):
    return {
        "credits_remaining": 87,
        "items": [{
            "media": {
                "id": "3913028191006298064_42",
                "pk": "3913028191006298064",
                "code": "DZN3mhZBQ_Q",
                "taken_at": 1784476800,
                "caption": {"text": caption} if caption else None,
                "play_count": views,
                "like_count": 800,
                "comment_count": 32,
                "video_duration": 24.5,
                "image_versions2": {
                    "candidates": [{"url": "https://cdn.example/reel.jpg"}],
                },
            },
        }],
        "paging_info": {"more_available": True, "max_id": "next"},
    }


def test_collector_status_never_exposes_key():
    status = collector.collector_status(environ={"SCRAPECREATORS_API_KEY": "secret"})
    assert status["configured"] is True
    assert status["max_authors_per_sync"] == 25
    assert status["credits_per_author"] == 1
    assert status["max_credits_per_author"] == 2
    assert status["max_paid_cost_per_sync_usd"] == 0.094
    assert "secret" not in repr(status)


def test_sync_imports_reels_with_one_bounded_request_per_author(tmp_path):
    project_id = _seed(tmp_path)
    calls = []

    def fetch(url, headers, timeout):
        calls.append((url, headers, timeout))
        return _provider_page()

    result = collector.sync_project(
        tmp_path,
        project_id,
        api_key="test-key",
        fetch_json=fetch,
        now=NOW,
    )

    assert result["credits_used"] == 1
    assert result["max_credits"] == 2
    assert result["credits_remaining"] == 87
    assert result["reels_imported"] == 1
    assert calls[0][0].endswith("/v1/instagram/user/reels?handle=topdev")
    assert calls[0][1]["x-api-key"] == "test-key"
    reel = research.get_project_feed(tmp_path, project_id, window="all", now=NOW)["reels"][0]
    assert reel["url"] == "https://www.instagram.com/reel/DZN3mhZBQ_Q/"
    assert reel["views"] == 12_000
    assert reel["author"]["median_views"] == 12_000
    assert reel["outlier_score"] == 1.0
    assert reel["duration_seconds"] == 24.5
    assert reel["thumbnail_url"] == "https://cdn.example/reel.jpg"


def test_repeat_sync_keeps_analysis_notes_and_adds_metric_snapshot(tmp_path):
    project_id = _seed(tmp_path)
    collector.sync_project(
        tmp_path,
        project_id,
        api_key="test-key",
        fetch_json=lambda *_: _provider_page(),
        now=datetime(2026, 7, 19, 8, 0, tzinfo=timezone.utc),
    )
    research.ingest_reel(
        tmp_path,
        project_id,
        reel_id="3913028191006298064_42",
        author_id="topdev",
        url="https://www.instagram.com/reel/DZN3mhZBQ_Q/",
        published_at="2026-07-19T16:00:00Z",
        views=12_000,
        hook="Broken mechanic in frame one",
        patterns=["failure first"],
        metrics_captured_at="2026-07-19T08:00:00Z",
    )
    collector.sync_project(
        tmp_path,
        project_id,
        api_key="test-key",
        fetch_json=lambda *_: _provider_page(views=18_000, caption=""),
        now=NOW,
    )

    reel = research.get_project_feed(tmp_path, project_id, window="all", now=NOW)["reels"][0]
    assert reel["views"] == 18_000
    assert reel["hook"] == "Broken mechanic in frame one"
    assert reel["patterns"] == ["failure first"]
    assert len(reel["metrics_history"]) == 2


def test_sync_falls_back_to_profile_posts_and_keeps_only_reels(tmp_path):
    project_id = _seed(tmp_path)
    calls = []

    def fetch(url, *_):
        calls.append(url)
        if "/user/reels" in url:
            raise collector.ScrapeCreatorsNotFoundError("not found")
        reel = _provider_page()["items"][0]["media"]
        reel["product_type"] = "clips"
        image = {**reel, "id": "image-id", "product_type": "feed", "media_type": 1}
        return {"credits_remaining": 86, "items": [reel, image]}

    result = collector.sync_project(
        tmp_path,
        project_id,
        api_key="test-key",
        fetch_json=fetch,
        now=NOW,
    )

    assert len(calls) == 2
    assert "/v2/instagram/user/posts" in calls[1]
    assert result["credits_used"] == 2
    assert result["items_received"] == 2
    assert result["reels_imported"] == 1


def test_sync_requires_key_and_enforces_author_limit(tmp_path):
    project_id = _seed(tmp_path)
    with pytest.raises(collector.ScrapeCreatorsError, match="not configured"):
        collector.sync_project(tmp_path, project_id, api_key="")

    for index in range(25):
        research.add_author(tmp_path, project_id, username=f"author{index}")
    with pytest.raises(research.ResearchError, match="limited to 25 authors"):
        collector.sync_project(tmp_path, project_id, api_key="test-key")
