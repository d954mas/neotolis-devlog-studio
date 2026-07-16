"""Tests for dlstudio.services.stock -- Pexels/Pixabay search + download.

`requests` is imported lazily inside the module's provider/download
functions, so every test here monkeypatches the real `requests` module's
`get` (the same module object the lazy `import requests` inside the
function resolves to via sys.modules) -- no network I/O ever happens.
"""
from __future__ import annotations

import json

import pytest

from dlstudio.services import stock


class _FakeResponse:
    def __init__(self, payload=None, *, content: bytes = b"", status: int = 200):
        self._payload = payload
        self._content = content
        self.status_code = status

    def raise_for_status(self):
        if self.status_code >= 400:
            raise RuntimeError(f"HTTP {self.status_code}")

    def json(self):
        return self._payload

    def iter_content(self, chunk_size=1024 * 1024):
        yield self._content

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


_PEXELS_PAYLOAD = {
    "videos": [
        {
            "id": 111,
            "url": "https://www.pexels.com/video/111",
            "duration": 12.0,
            "image": "https://images.pexels.com/111/preview.jpg",
            "user": {"name": "Jane Shooter"},
            "video_files": [
                {"width": 1920, "height": 1080, "link": "https://pexels.example/111_1080.mp4"},
                {"width": 640, "height": 360, "link": "https://pexels.example/111_360.mp4"},
            ],
        },
        {
            "id": 222,
            "url": "https://www.pexels.com/video/222",
            "duration": 8.0,
            "image": "https://images.pexels.com/222/preview.jpg",
            "user": {"name": "Bo Kamera"},
            "video_files": [
                # 9:16 file only -- should be excluded when aspect=16:9
                {"width": 1080, "height": 1920, "link": "https://pexels.example/222_portrait.mp4"},
            ],
        },
    ]
}

_PIXABAY_PAYLOAD = {
    "hits": [
        {
            "id": 333,
            "pageURL": "https://pixabay.com/videos/333",
            "duration": 15.0,
            "user": "pixauser",
            "videos": {
                "large": {"width": 1920, "height": 1080, "url": "https://pixabay.example/333.mp4",
                          "thumbnail": "https://pixabay.example/333_thumb.jpg"},
            },
        },
    ]
}


# ─── search: pexels ─────────────────────────────────────────────────────

def test_search_pexels_returns_typed_results(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "test-key")

    import requests

    def fake_get(url, headers=None, timeout=None):
        assert "test-key" == headers["Authorization"]
        return _FakeResponse(_PEXELS_PAYLOAD)

    monkeypatch.setattr(requests, "get", fake_get)

    results = stock.search("mountains", source="pexels", aspect="16:9", per_page=5)
    assert len(results) == 1  # the 9:16-only video is filtered out
    r = results[0]
    assert r.source == "pexels"
    assert r.id == "111"
    assert r.url == "https://pexels.example/111_1080.mp4"
    assert r.preview_url == "https://images.pexels.com/111/preview.jpg"
    assert r.width == 1920 and r.height == 1080
    assert r.duration == 12.0
    assert r.credit == "Jane Shooter"
    assert "Pexels" in r.license_note
    assert r.query == "mountains"


def test_search_pexels_sends_orientation_and_query(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "k")
    import requests

    captured = {}

    def fake_get(url, headers=None, timeout=None):
        captured["url"] = url
        captured["headers"] = headers
        return _FakeResponse({"videos": []})

    monkeypatch.setattr(requests, "get", fake_get)
    stock.search("beach", source="pexels", aspect="9:16", per_page=3)
    assert "orientation=portrait" in captured["url"]
    assert "beach" in captured["url"]
    assert captured["headers"]["Authorization"] == "k"


# ─── search: pixabay ────────────────────────────────────────────────────

def test_search_pixabay_returns_typed_results(monkeypatch):
    monkeypatch.setenv("PIXABAY_API_KEY", "pix-key")
    import requests

    def fake_get(url, timeout=None):
        assert "key=pix-key" in url
        return _FakeResponse(_PIXABAY_PAYLOAD)

    monkeypatch.setattr(requests, "get", fake_get)

    results = stock.search("city", source="pixabay", aspect="16:9", per_page=5)
    assert len(results) == 1
    r = results[0]
    assert r.source == "pixabay"
    assert r.id == "333"
    assert r.url == "https://pixabay.example/333.mp4"
    assert r.preview_url == "https://pixabay.example/333_thumb.jpg"
    assert r.credit == "pixauser"
    assert "Pixabay" in r.license_note


# ─── search: validation + env-key errors ───────────────────────────────

def test_search_unsupported_source_raises_value_error(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "k")
    with pytest.raises(ValueError, match="unsupported stock source"):
        stock.search("q", source="shutterstock")


def test_search_unsupported_aspect_raises_value_error(monkeypatch):
    monkeypatch.setenv("PEXELS_API_KEY", "k")
    with pytest.raises(ValueError, match="unsupported aspect"):
        stock.search("q", source="pexels", aspect="4:3")


def test_search_missing_pexels_key_raises_with_env_var_name(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    with pytest.raises(stock.StockConfigError, match="PEXELS_API_KEY"):
        stock.search("q", source="pexels")


def test_search_missing_pixabay_key_raises_with_env_var_name(monkeypatch):
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    with pytest.raises(stock.StockConfigError, match="PIXABAY_API_KEY"):
        stock.search("q", source="pixabay")


def test_stock_config_error_is_a_runtime_error(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    with pytest.raises(RuntimeError):
        stock.search("q", source="pexels")


def test_search_explicit_api_key_bypasses_env(monkeypatch):
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse({"videos": []}))
    # must not raise even though the env var is unset
    stock.search("q", source="pexels", api_key="explicit-key")


# ─── StockResult.to_dict ────────────────────────────────────────────────

def test_stock_result_to_dict_roundtrips():
    r = stock.StockResult(
        source="pexels", id="1", url="https://x/1.mp4", preview_url="https://x/1.jpg",
        width=1920, height=1080, duration=5.0, credit="Someone", license_note="note", query="q",
    )
    d = r.to_dict()
    assert d == {
        "source": "pexels", "id": "1", "url": "https://x/1.mp4", "preview_url": "https://x/1.jpg",
        "width": 1920, "height": 1080, "duration": 5.0, "credit": "Someone",
        "license_note": "note", "query": "q",
    }


# ─── download ───────────────────────────────────────────────────────────

def test_download_writes_files_and_manifest(tmp_path, monkeypatch):
    import requests

    def fake_get(url, stream=True, timeout=None):
        return _FakeResponse(content=f"bytes-for-{url}".encode())

    monkeypatch.setattr(requests, "get", fake_get)

    results = [
        stock.StockResult(
            source="pexels", id="1", url="https://x/1.mp4", preview_url="",
            width=1920, height=1080, duration=5.0, credit="A", license_note="Pexels License",
            query="cats",
        ),
        stock.StockResult(
            source="pixabay", id="2", url="https://y/2.mp4", preview_url="",
            width=1920, height=1080, duration=6.0, credit="B", license_note="Pixabay License",
            query="cats",
        ),
    ]
    out_dir = tmp_path / "out"
    manifest = stock.download(results, out_dir, retrieved_at="2026-07-16T00:00:00+00:00")

    assert len(manifest) == 2
    assert (out_dir / "manifest.json").exists()
    saved_files = sorted(p.name for p in out_dir.glob("*.mp4"))
    assert saved_files == ["pexels_1.mp4", "pixabay_2.mp4"]

    on_disk = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    first = next(e for e in manifest if e["id"] == "1")
    assert first == {
        "source": "pexels", "id": "1", "url": "https://x/1.mp4",
        "license": "Pexels License", "query": "cats",
        "retrieved_at": "2026-07-16T00:00:00+00:00", "file": "pexels_1.mp4",
    }
    assert (out_dir / "pexels_1.mp4").read_bytes() == b"bytes-for-https://x/1.mp4"


def test_download_defaults_retrieved_at_when_omitted(tmp_path, monkeypatch):
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(content=b"x"))

    result = stock.StockResult(
        source="pexels", id="9", url="https://x/9.mp4", preview_url="",
        width=100, height=100, duration=1.0, credit="", license_note="", query="",
    )
    manifest = stock.download([result], tmp_path / "out2")
    assert manifest[0]["retrieved_at"]  # non-empty, ISO-ish string


def test_download_accepts_manifest_file_path(tmp_path, monkeypatch):
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(content=b"y"))

    manifest_in = tmp_path / "search_results.json"
    manifest_in.write_text(json.dumps([
        {"source": "pexels", "id": "5", "url": "https://x/5.mp4", "license_note": "L", "query": "q"},
    ]), encoding="utf-8")

    out_dir = tmp_path / "downloaded"
    manifest = stock.download(manifest_in, out_dir, retrieved_at="2026-01-01T00:00:00+00:00")
    assert len(manifest) == 1
    assert (out_dir / "pexels_5.mp4").exists()


def test_download_accepts_dict_list_without_stockresult_objects(tmp_path, monkeypatch):
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(content=b"z"))

    items = [{"source": "pixabay", "id": "7", "url": "https://y/7.mp4", "license_note": "L2", "query": "q2"}]
    manifest = stock.download(items, tmp_path / "out3")
    assert manifest[0]["id"] == "7"
    assert manifest[0]["license"] == "L2"


def test_download_skips_items_without_url(tmp_path, monkeypatch):
    import requests

    monkeypatch.setattr(requests, "get", lambda *a, **k: _FakeResponse(content=b"w"))

    items = [{"source": "pexels", "id": "no-url"}]
    manifest = stock.download(items, tmp_path / "out4")
    assert manifest == []
