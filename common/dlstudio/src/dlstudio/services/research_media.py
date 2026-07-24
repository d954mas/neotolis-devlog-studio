"""Disposable local media cache for Pattern Lab Reels."""
from __future__ import annotations

import os
import re
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

from dlstudio.services import research


CACHE_ENV = "DLSTUDIO_RESEARCH_CACHE_DIR"
MAX_MEDIA_BYTES = 500 * 1024 * 1024


class ResearchMediaError(RuntimeError):
    """Raised when a Reel cannot be cached safely."""


FetchMedia = Callable[[str, Path, int], tuple[int, str]]
ResolveMediaUrl = Callable[[str], str]


def cache_root(
    workspace_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    values = environ if environ is not None else os.environ
    configured = values.get(CACHE_ENV, "").strip()
    if configured:
        return Path(configured).expanduser().resolve()
    return workspace_root.resolve() / ".runtime" / "research-media"


def _safe_component(value: str) -> str:
    readable = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-._")[:80]
    if not readable:
        raise research.ResearchError("invalid research media id")
    return readable


def _reel(workspace_root: Path, project_id: str, reel_id: str) -> dict[str, Any]:
    payload = research.load_store(workspace_root)
    project = next((item for item in payload["projects"] if item.get("id") == project_id), None)
    if project is None:
        raise research.ResearchError(f"unknown research project: {project_id}")
    reel = next((item for item in project.get("reels", []) if item.get("id") == reel_id), None)
    if reel is None:
        raise research.ResearchError(f"unknown research Reel: {reel_id}")
    return reel


def media_path(
    workspace_root: Path,
    project_id: str,
    reel_id: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    root = cache_root(workspace_root, environ=environ)
    return root / _safe_component(project_id) / f"{_safe_component(reel_id)}.mp4"


def status(
    workspace_root: Path,
    project_id: str,
    reel_id: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    _reel(workspace_root, project_id, reel_id)
    path = media_path(workspace_root, project_id, reel_id, environ=environ)
    cached = path.is_file()
    return {
        "cached": cached,
        "size_bytes": path.stat().st_size if cached else 0,
        "media_url": (
            f"/api/research/projects/{project_id}/reels/{reel_id}/media" if cached else None
        ),
    }


def summary(
    workspace_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, int]:
    root = cache_root(workspace_root, environ=environ)
    files = [path for path in root.rglob("*.mp4") if path.is_file()] if root.is_dir() else []
    return {
        "file_count": len(files),
        "size_bytes": sum(path.stat().st_size for path in files),
    }


def _fetch_media(url: str, destination: Path, max_bytes: int) -> tuple[int, str]:
    import requests

    try:
        with requests.get(
            url,
            headers={"User-Agent": "Mozilla/5.0"},
            stream=True,
            timeout=(10, 90),
        ) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").split(";", 1)[0].lower()
            declared = int(response.headers.get("content-length", "0") or 0)
            if declared > max_bytes:
                raise ResearchMediaError("Reel video is larger than the 500 MB cache limit")
            size = 0
            with destination.open("wb") as handle:
                for chunk in response.iter_content(chunk_size=1024 * 1024):
                    if not chunk:
                        continue
                    size += len(chunk)
                    if size > max_bytes:
                        raise ResearchMediaError("Reel video is larger than the 500 MB cache limit")
                    handle.write(chunk)
    except requests.RequestException as exc:
        raise ResearchMediaError(f"Reel download failed: {exc}") from exc
    if size == 0:
        raise ResearchMediaError("Reel download returned an empty file")
    if content_type and not (
        content_type.startswith("video/") or content_type == "application/octet-stream"
    ):
        raise ResearchMediaError(f"Reel download returned {content_type}, not a video")
    return size, content_type


def download(
    workspace_root: Path,
    project_id: str,
    reel_id: str,
    *,
    resolve_media_url: ResolveMediaUrl,
    fetch_media: FetchMedia | None = None,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    reel = _reel(workspace_root, project_id, reel_id)
    existing = status(workspace_root, project_id, reel_id, environ=environ)
    if existing["cached"]:
        return {**existing, "downloaded": False, "credits_used": 0}

    destination = media_path(workspace_root, project_id, reel_id, environ=environ)
    destination.parent.mkdir(parents=True, exist_ok=True)
    partial = destination.with_suffix(".mp4.part")
    partial.unlink(missing_ok=True)
    try:
        media_url = resolve_media_url(str(reel["url"]))
        (fetch_media or _fetch_media)(media_url, partial, MAX_MEDIA_BYTES)
        os.replace(partial, destination)
    except Exception:
        partial.unlink(missing_ok=True)
        raise
    cached = status(workspace_root, project_id, reel_id, environ=environ)
    return {**cached, "downloaded": True, "credits_used": 1}


def delete(
    workspace_root: Path,
    project_id: str,
    reel_id: str,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, Any]:
    _reel(workspace_root, project_id, reel_id)
    path = media_path(workspace_root, project_id, reel_id, environ=environ)
    removed = path.is_file()
    path.unlink(missing_ok=True)
    try:
        path.parent.rmdir()
    except OSError:
        pass
    return {"removed": removed}


def clear(
    workspace_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> dict[str, int]:
    root = cache_root(workspace_root, environ=environ)
    before = summary(workspace_root, environ=environ)
    if root.is_dir():
        for path in root.rglob("*"):
            if path.is_file() and path.suffix in {".mp4", ".part"}:
                path.unlink(missing_ok=True)
        for path in sorted((item for item in root.rglob("*") if item.is_dir()), reverse=True):
            try:
                path.rmdir()
            except OSError:
                pass
        try:
            root.rmdir()
        except OSError:
            pass
    return {"removed_files": before["file_count"], "removed_bytes": before["size_bytes"]}
