from __future__ import annotations

import pytest

pytest.importorskip("fastapi")

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dlstudio.api.research import create_research_router
from dlstudio.services import research_media, research_scrapecreators


def test_research_api_vertical_slice(tmp_path):
    app = FastAPI()
    app.include_router(create_research_router(tmp_path))
    client = TestClient(app)

    created = client.post("/api/research/projects", json={
        "title": "Gamedev",
        "description": "Learn from strong Reels",
        "style_profile": "Real gameplay and dry humour",
    })
    assert created.status_code == 201
    project_id = created.json()["id"]

    author = client.post(f"/api/research/projects/{project_id}/authors", json={
        "username": "topdev",
        "followers_count": 100000,
        "median_views": 20000,
    })
    assert author.status_code == 201

    reel = client.post(f"/api/research/projects/{project_id}/reels", json={
        "id": "cart-hook",
        "author_id": "topdev",
        "url": "https://www.instagram.com/reel/cart-hook/",
        "published_at": "2026-07-19T08:00:00Z",
        "views": 100000,
        "hook": "I broke the cart physics",
        "patterns": ["problem first", "failure to fix"],
    })
    assert reel.status_code == 201

    feed = client.get(f"/api/research/projects/{project_id}?range=all&sort=outlier&limit=1")
    assert feed.status_code == 200
    assert feed.json()["reels"][0]["outlier_score"] == 5.0
    assert feed.json()["page"]["limit"] == 1
    assert feed.json()["page"]["total"] == 1

    experiment = client.post(f"/api/research/projects/{project_id}/experiments", json={
        "reel_id": "cart-hook",
        "mode": "adaptation",
        "hypothesis": "Lead with the broken mechanic.",
        "take_from_reference": ["problem first"],
        "keep_original": ["our gameplay"],
    })
    assert experiment.status_code == 201
    assert experiment.json()["agent_context_path"].endswith(".md")

    result = client.post(
        f"/api/research/projects/{project_id}/experiments/{experiment.json()['id']}/result",
        json={
            "verdict": "mixed",
            "published_url": "https://www.instagram.com/reel/our-version/",
            "views": 35_000,
            "notes": "Strong opening, weak payoff.",
        },
    )
    assert result.status_code == 200
    assert result.json()["status"] == "measured"
    assert result.json()["result"]["verdict"] == "mixed"

    summary = client.get("/api/research/projects").json()[0]
    assert summary == {
        "id": "gamedev",
        "title": "Gamedev",
        "description": "Learn from strong Reels",
        "author_count": 1,
        "reel_count": 1,
        "experiment_count": 1,
        "agent_brief_path": "data/research/projects/gamedev/README.md",
    }


def test_research_api_reports_unknown_project(tmp_path):
    app = FastAPI()
    app.include_router(create_research_router(tmp_path))
    response = TestClient(app).get("/api/research/projects/missing")
    assert response.status_code == 404


def test_research_collector_status_and_sync_routes(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(create_research_router(tmp_path))
    client = TestClient(app)
    project_id = client.post("/api/research/projects", json={"title": "Gamedev"}).json()["id"]
    client.post(
        f"/api/research/projects/{project_id}/authors",
        json={"username": "topdev"},
    )
    monkeypatch.setenv("SCRAPECREATORS_API_KEY", "configured-for-test")
    monkeypatch.setattr(
        research_scrapecreators,
        "sync_project",
        lambda *args, **kwargs: {
            "provider": "scrapecreators",
            "authors_requested": 1,
            "authors_completed": 1,
            "credits_used": 1,
            "max_credits": 1,
            "credits_remaining": 88,
            "items_received": 12,
            "reels_imported": 12,
            "items_skipped": 0,
            "failures": [],
            "captured_at": "2026-07-19T12:00:00Z",
        },
    )

    status = client.get("/api/research/collector/status")
    assert status.status_code == 200
    assert status.json()["configured"] is True
    assert "configured-for-test" not in status.text

    sync = client.post(
        f"/api/research/projects/{project_id}/sync",
        json={"author_ids": ["topdev"]},
    )
    assert sync.status_code == 200
    assert sync.json()["credits_used"] == 1


def test_research_quick_add_accepts_profile_link_or_handle(tmp_path):
    app = FastAPI()
    app.include_router(create_research_router(tmp_path))
    client = TestClient(app)
    project_id = client.post("/api/research/projects", json={"title": "Gamedev"}).json()["id"]

    added = client.post(
        f"/api/research/projects/{project_id}/quick-add",
        json={"kind": "author", "value": "https://www.instagram.com/Julia.GameDev/?hl=ru"},
    )
    assert added.status_code == 201
    assert added.json()["created"] is True
    assert added.json()["author"]["username"] == "julia.gamedev"
    assert added.json()["credits_used"] == 0

    repeated = client.post(
        f"/api/research/projects/{project_id}/quick-add",
        json={"kind": "author", "value": "@julia.gamedev"},
    )
    assert repeated.status_code == 201
    assert repeated.json()["created"] is False


def test_research_quick_add_reel_uses_provider_import(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(create_research_router(tmp_path))
    client = TestClient(app)
    project_id = client.post("/api/research/projects", json={"title": "Gamedev"}).json()["id"]
    expected = {
        "kind": "reel",
        "created": True,
        "author_created": True,
        "credits_used": 1,
        "author": {"id": "creator", "username": "creator"},
        "reel": {"id": "reel-1", "url": "https://www.instagram.com/reel/abc/"},
    }
    monkeypatch.setattr(research_scrapecreators, "import_reel_url", lambda *args, **kwargs: expected)

    response = client.post(
        f"/api/research/projects/{project_id}/quick-add",
        json={"kind": "reel", "value": "https://www.instagram.com/reel/abc/"},
    )
    assert response.status_code == 201
    assert response.json() == expected


def test_research_media_cache_api_does_not_delete_research_data(tmp_path, monkeypatch):
    app = FastAPI()
    app.include_router(create_research_router(tmp_path))
    client = TestClient(app)
    project_id = client.post("/api/research/projects", json={"title": "Gamedev"}).json()["id"]
    client.post(
        f"/api/research/projects/{project_id}/authors",
        json={"username": "creator"},
    )
    client.post(
        f"/api/research/projects/{project_id}/reels",
        json={
            "id": "reel-1",
            "author_id": "creator",
            "url": "https://www.instagram.com/reel/abc/",
            "published_at": "2026-07-19T12:00:00Z",
        },
    )
    monkeypatch.setattr(
        research_scrapecreators,
        "resolve_reel_video_url",
        lambda source_url: "https://cdn.example/reel.mp4",
    )

    def fetch(url, destination, max_bytes):
        destination.write_bytes(b"fake-mp4")
        return 8, "video/mp4"

    monkeypatch.setattr(research_media, "_fetch_media", fetch)

    cached = client.post(f"/api/research/projects/{project_id}/reels/reel-1/media")
    assert cached.status_code == 200
    assert cached.json()["downloaded"] is True
    assert client.get("/api/research/media-cache").json() == {
        "file_count": 1,
        "size_bytes": 8,
    }
    media = client.get(f"/api/research/projects/{project_id}/reels/reel-1/media")
    assert media.status_code == 200
    assert media.content == b"fake-mp4"

    cleared = client.delete("/api/research/media-cache")
    assert cleared.json() == {"removed_files": 1, "removed_bytes": 8}
    assert client.get(f"/api/research/projects/{project_id}?range=all").json()["reels"][0]["id"] == "reel-1"
