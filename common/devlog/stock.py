"""Stock B-roll search, download cache, and project manifest helpers."""
from __future__ import annotations

import hashlib
import json
import os
import re
import shutil
import subprocess
import tomllib
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode, urlsplit

import requests

from devlog.config import find_config_path


ASPECT_RESOLUTIONS = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}

PEXELS_ORIENTATIONS = {
    "16:9": "landscape",
    "9:16": "portrait",
    "1:1": "square",
}


@dataclass(frozen=True)
class StockCandidate:
    provider: str
    query: str
    provider_id: str
    source_url: str
    download_url: str
    duration: float
    width: int
    height: int
    aspect: str

    def to_dict(self) -> dict:
        return asdict(self)


def _read_stock_config() -> dict:
    path = find_config_path()
    if not path:
        return {}
    data = tomllib.loads(path.read_text(encoding="utf-8"))
    return dict(data.get("stock", {}))


def _api_keys(provider: str) -> list[str]:
    stock = _read_stock_config()
    env_names = [
        f"{provider.upper()}_API_KEYS",
        f"{provider.upper()}_API_KEY",
    ]
    for name in env_names:
        value = os.environ.get(name)
        if value:
            return [item.strip() for item in value.split(",") if item.strip()]
    raw = stock.get(f"{provider}_api_keys") or stock.get(f"{provider}_api_key")
    if isinstance(raw, str):
        return [item.strip() for item in raw.split(",") if item.strip()]
    if isinstance(raw, list):
        return [str(item).strip() for item in raw if str(item).strip()]
    return []


def _require_api_key(provider: str) -> str:
    keys = _api_keys(provider)
    if not keys:
        env = f"{provider.upper()}_API_KEY"
        raise SystemExit(
            f"{provider} API key is required. Set {env} or [stock].{provider}_api_keys in devlog.toml."
        )
    return keys[0]


def _matches_aspect(width: int, height: int, aspect: str, *, tolerance: float = 0.12) -> bool:
    target_w, target_h = ASPECT_RESOLUTIONS[aspect]
    return abs((width / height) - (target_w / target_h)) <= tolerance


def _candidate_sort_key(item: StockCandidate) -> tuple[float, int]:
    target_w, target_h = ASPECT_RESOLUTIONS[item.aspect]
    target_pixels = target_w * target_h
    pixels = item.width * item.height
    return (abs(pixels - target_pixels), -pixels)


def search_pexels(query: str, *, aspect: str, min_duration: float, limit: int) -> list[StockCandidate]:
    api_key = _require_api_key("pexels")
    params = {
        "query": query,
        "per_page": min(max(limit * 2, 10), 80),
        "orientation": PEXELS_ORIENTATIONS[aspect],
    }
    response = requests.get(
        f"https://api.pexels.com/videos/search?{urlencode(params)}",
        headers={"Authorization": api_key},
        timeout=(30, 60),
    )
    response.raise_for_status()
    out: list[StockCandidate] = []
    for video in response.json().get("videos", []):
        duration = float(video.get("duration") or 0)
        if duration < min_duration:
            continue
        files = []
        for item in video.get("video_files", []):
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            if width and height and _matches_aspect(width, height, aspect):
                files.append((width * height, width, height, item.get("link") or ""))
        if not files:
            continue
        _, width, height, download_url = sorted(files, reverse=True)[0]
        if not download_url:
            continue
        out.append(StockCandidate(
            provider="pexels",
            query=query,
            provider_id=str(video.get("id") or ""),
            source_url=video.get("url") or "",
            download_url=download_url,
            duration=duration,
            width=width,
            height=height,
            aspect=aspect,
        ))
    out.sort(key=_candidate_sort_key)
    return out[:limit]


def search_pixabay(query: str, *, aspect: str, min_duration: float, limit: int) -> list[StockCandidate]:
    api_key = _require_api_key("pixabay")
    params = {
        "q": query,
        "video_type": "all",
        "per_page": min(max(limit * 2, 10), 200),
        "key": api_key,
    }
    response = requests.get(
        f"https://pixabay.com/api/videos/?{urlencode(params)}",
        timeout=(30, 60),
    )
    response.raise_for_status()
    out: list[StockCandidate] = []
    for video in response.json().get("hits", []):
        duration = float(video.get("duration") or 0)
        if duration < min_duration:
            continue
        files = []
        for item in (video.get("videos") or {}).values():
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            if width and height and _matches_aspect(width, height, aspect):
                files.append((width * height, width, height, item.get("url") or ""))
        if not files:
            continue
        _, width, height, download_url = sorted(files, reverse=True)[0]
        if not download_url:
            continue
        out.append(StockCandidate(
            provider="pixabay",
            query=query,
            provider_id=str(video.get("id") or ""),
            source_url=video.get("pageURL") or "",
            download_url=download_url,
            duration=duration,
            width=width,
            height=height,
            aspect=aspect,
        ))
    out.sort(key=_candidate_sort_key)
    return out[:limit]


def search_stock(query: str, *, source: str, aspect: str, min_duration: float,
                 limit: int) -> list[StockCandidate]:
    if aspect not in ASPECT_RESOLUTIONS:
        raise SystemExit(f"Unsupported aspect: {aspect}. Use one of {', '.join(ASPECT_RESOLUTIONS)}.")
    if source == "pexels":
        return search_pexels(query, aspect=aspect, min_duration=min_duration, limit=limit)
    if source == "pixabay":
        return search_pixabay(query, aspect=aspect, min_duration=min_duration, limit=limit)
    raise SystemExit(f"Unsupported stock source: {source}")


def write_candidates(path: Path, candidates: list[StockCandidate]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps([item.to_dict() for item in candidates], ensure_ascii=False, indent=2),
        encoding="utf-8",
    )


def _url_hash(url: str) -> str:
    clean = urlsplit(url)
    without_query = clean._replace(query="", fragment="").geturl()
    return hashlib.sha1(without_query.encode("utf-8")).hexdigest()[:16]


def _safe_slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    return (slug or fallback)[:48]


def _probe_ok(path: Path) -> bool:
    try:
        subprocess.run(
            ["ffprobe", "-v", "error", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True,
            text=True,
            check=True,
        )
        return True
    except Exception:
        return False


def _download_to_cache(candidate: dict, workspace_root: Path) -> Path:
    provider = candidate["provider"]
    url = candidate["download_url"]
    cache_dir = workspace_root / ".asset_cache" / "stock" / provider
    cache_dir.mkdir(parents=True, exist_ok=True)
    cache_path = cache_dir / f"vid-{_url_hash(url)}.mp4"
    if cache_path.exists() and cache_path.stat().st_size > 0 and _probe_ok(cache_path):
        return cache_path

    tmp_path = cache_path.with_suffix(".tmp")
    with requests.get(url, stream=True, timeout=(60, 240)) as response:
        response.raise_for_status()
        with tmp_path.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    if not _probe_ok(tmp_path):
        tmp_path.unlink(missing_ok=True)
        raise RuntimeError(f"downloaded stock file is not decodable: {url}")
    tmp_path.replace(cache_path)
    return cache_path


def _load_manifest(path: Path) -> list[dict]:
    if not path.exists():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8-sig"))
        return data if isinstance(data, list) else []
    except Exception:
        return []


def _write_manifest(path: Path, entries: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(entries, ensure_ascii=False, indent=2), encoding="utf-8")


def download_candidates(candidates_path: Path, *, project_root: Path, workspace_root: Path,
                        out_dir: Path, limit: int | None = None) -> list[dict]:
    payload = json.loads(candidates_path.read_text(encoding="utf-8-sig"))
    candidates = payload if isinstance(payload, list) else payload.get("candidates", [])
    downloadable = [item for item in candidates if item.get("download_url") and item.get("provider")]
    if limit is not None:
        downloadable = downloadable[:limit]

    out_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = out_dir / "manifest.json"
    manifest = _load_manifest(manifest_path)
    by_source = {item.get("source_url") or item.get("download_url"): item for item in manifest}
    downloaded: list[dict] = []
    for idx, candidate in enumerate(downloadable, start=1):
        cache_path = _download_to_cache(candidate, workspace_root)
        slug = _safe_slug(candidate.get("query", ""), candidate.get("provider_id") or f"stock_{idx}")
        provider = candidate["provider"]
        project_path = out_dir / f"{slug}_{provider}_{idx:02d}.mp4"
        shutil.copyfile(cache_path, project_path)
        rel_project = project_path.relative_to(project_root).as_posix()
        entry = {
            "asset_id": f"{provider}_{candidate.get('provider_id') or _url_hash(candidate['download_url'])}",
            "provider": provider,
            "query": candidate.get("query", ""),
            "source_url": candidate.get("source_url", ""),
            "download_url": candidate.get("download_url", ""),
            "cached_path": cache_path.as_posix(),
            "project_path": rel_project,
            "status": "downloaded",
            "used_in": [],
            "duration": candidate.get("duration"),
            "width": candidate.get("width"),
            "height": candidate.get("height"),
            "aspect": candidate.get("aspect"),
            "license": provider,
            "downloaded_at": datetime.now(timezone.utc).isoformat(),
        }
        key = entry["source_url"] or entry["download_url"]
        by_source[key] = entry
        downloaded.append(entry)
    _write_manifest(manifest_path, list(by_source.values()))
    return downloaded
