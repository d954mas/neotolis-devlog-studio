from __future__ import annotations

from dlstudio.services import research, research_media


def _seed(root):
    project = research.create_project(root, title="Gamedev")
    research.add_author(root, project["id"], username="creator")
    research.ingest_reel(
        root,
        project["id"],
        reel_id="reel-1",
        author_id="creator",
        url="https://www.instagram.com/reel/abc/",
        published_at="2026-07-19T12:00:00Z",
    )
    return project["id"]


def test_reel_media_cache_is_disposable_and_idempotent(tmp_path):
    project_id = _seed(tmp_path)
    resolved = []

    def resolve(source_url):
        resolved.append(source_url)
        return "https://cdn.example/reel.mp4"

    def fetch(url, destination, max_bytes):
        assert url == "https://cdn.example/reel.mp4"
        assert max_bytes == research_media.MAX_MEDIA_BYTES
        destination.write_bytes(b"fake-mp4")
        return 8, "video/mp4"

    first = research_media.download(
        tmp_path,
        project_id,
        "reel-1",
        resolve_media_url=resolve,
        fetch_media=fetch,
    )
    assert first["cached"] is True
    assert first["downloaded"] is True
    assert first["credits_used"] == 1
    assert research_media.summary(tmp_path) == {"file_count": 1, "size_bytes": 8}

    second = research_media.download(
        tmp_path,
        project_id,
        "reel-1",
        resolve_media_url=resolve,
        fetch_media=fetch,
    )
    assert second["downloaded"] is False
    assert second["credits_used"] == 0
    assert len(resolved) == 1

    assert research_media.delete(tmp_path, project_id, "reel-1") == {"removed": True}
    assert research_media.summary(tmp_path) == {"file_count": 0, "size_bytes": 0}
    assert research.load_store(tmp_path)["projects"][0]["reels"][0]["id"] == "reel-1"


def test_clear_removes_only_media_cache(tmp_path):
    project_id = _seed(tmp_path)
    path = research_media.media_path(tmp_path, project_id, "reel-1")
    path.parent.mkdir(parents=True)
    path.write_bytes(b"video")
    keep = tmp_path / ".runtime" / "other-tool" / "keep.txt"
    keep.parent.mkdir(parents=True)
    keep.write_text("keep", encoding="utf-8")

    assert research_media.clear(tmp_path) == {"removed_files": 1, "removed_bytes": 5}
    assert not path.exists()
    assert keep.read_text(encoding="utf-8") == "keep"


def test_custom_cache_root_is_supported(tmp_path):
    project_id = _seed(tmp_path)
    custom = tmp_path / "external-cache"
    path = research_media.media_path(
        tmp_path,
        project_id,
        "reel-1",
        environ={research_media.CACHE_ENV: str(custom)},
    )
    assert path.is_relative_to(custom)
