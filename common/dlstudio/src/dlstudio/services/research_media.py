"""Disposable local media cache for Pattern Lab Reels."""
from __future__ import annotations

import hashlib
import os
import re
import tempfile
from contextlib import contextmanager
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any
from urllib.parse import quote

from dlstudio.services import research


CACHE_ENV = "DLSTUDIO_RESEARCH_CACHE_DIR"
MAX_MEDIA_BYTES = 500 * 1024 * 1024
OWNERSHIP_MARKER = ".dlstudio-research-media-cache"
_OWNERSHIP_CONTENT = "dlstudio.research-media-cache/v1\n"


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
    readable = re.sub(r"[^a-zA-Z0-9._-]+", "-", value).strip("-._")[:56]
    digest = hashlib.sha256(value.encode("utf-8")).hexdigest()[:16]
    return f"{readable or 'id'}-{digest}"


def _assert_safe_cache_root(workspace_root: Path, root: Path) -> None:
    workspace = workspace_root.resolve()
    resolved = root.resolve()
    canonical = (workspace / ".runtime" / "research-media").resolve()
    anchor = Path(resolved.anchor).resolve()
    forbidden = {anchor, workspace, Path.home().resolve()}
    if resolved in forbidden or resolved in workspace.parents:
        raise ResearchMediaError(f"unsafe cache root: {resolved}")
    try:
        resolved.relative_to(workspace)
    except ValueError:
        pass
    else:
        if resolved != canonical:
            raise ResearchMediaError(
                "configured research cache inside the workspace must use "
                f"the canonical path: {canonical}"
            )
    for candidate in (resolved, *resolved.parents):
        if (candidate / "product.toml").is_file() or (
            candidate / "production.toml"
        ).is_file():
            raise ResearchMediaError(
                f"research cache cannot live inside product/production data: {resolved}"
            )


@contextmanager
def _cache_mutation_lock(root: Path):
    """Serialize downloads, deletes, and clear across Studio processes."""

    root.mkdir(parents=True, exist_ok=True)
    path = root / ".dlstudio-research-media.lock"
    handle = path.open("a+b")
    try:
        if path.stat().st_size == 0:
            handle.write(b"\0")
            handle.flush()
        handle.seek(0)
        if os.name == "nt":
            import msvcrt

            msvcrt.locking(handle.fileno(), msvcrt.LK_LOCK, 1)
        else:
            import fcntl

            fcntl.flock(handle.fileno(), fcntl.LOCK_EX)
        yield
    finally:
        try:
            handle.seek(0)
            if os.name == "nt":
                import msvcrt

                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                import fcntl

                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)
        finally:
            handle.close()


def _marker_path(root: Path) -> Path:
    return root / OWNERSHIP_MARKER


def _owned_marker_valid(root: Path) -> bool:
    marker = _marker_path(root)
    try:
        return marker.is_file() and marker.read_text(encoding="utf-8") == _OWNERSHIP_CONTENT
    except OSError:
        return False


def _ensure_owned_cache_root(
    workspace_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path:
    """Create/validate the marker that grants this service ownership."""

    root = cache_root(workspace_root, environ=environ)
    _assert_safe_cache_root(workspace_root, root)
    if _owned_marker_valid(root):
        return root
    if root.exists() and any(root.iterdir()):
        raise ResearchMediaError(f"research media cache is not owned by dlstudio: {root}")
    root.mkdir(parents=True, exist_ok=True)
    marker = _marker_path(root)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{marker.name}.", suffix=".tmp", dir=root
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            stream.write(_OWNERSHIP_CONTENT)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, marker)
    finally:
        temporary.unlink(missing_ok=True)
    return root


def _require_owned_cache_root(
    workspace_root: Path,
    *,
    environ: Mapping[str, str] | None = None,
) -> Path | None:
    root = cache_root(workspace_root, environ=environ)
    _assert_safe_cache_root(workspace_root, root)
    if not root.exists():
        return None
    if not _owned_marker_valid(root):
        raise ResearchMediaError(f"research media cache is not owned by dlstudio: {root}")
    return root


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
            f"/api/research/projects/{quote(project_id, safe='')}/reels/"
            f"{quote(reel_id, safe='')}/media"
            if cached
            else None
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
    root = _ensure_owned_cache_root(workspace_root, environ=environ)
    with _cache_mutation_lock(root):
        existing = status(workspace_root, project_id, reel_id, environ=environ)
        if existing["cached"]:
            return {**existing, "downloaded": False, "credits_used": 0}

        destination = media_path(workspace_root, project_id, reel_id, environ=environ)
        destination.parent.mkdir(parents=True, exist_ok=True)
        handle, partial_name = tempfile.mkstemp(
            prefix=f".{destination.name}.",
            suffix=".part",
            dir=destination.parent,
        )
        os.close(handle)
        partial = Path(partial_name)
        try:
            media_url = resolve_media_url(str(reel["url"]))
            (fetch_media or _fetch_media)(media_url, partial, MAX_MEDIA_BYTES)
            if not partial.is_file() or partial.stat().st_size <= 0:
                raise ResearchMediaError("Reel download returned an empty file")
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
    root = _require_owned_cache_root(workspace_root, environ=environ)
    if root is None:
        return {"removed": False}
    with _cache_mutation_lock(root):
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
    root = _require_owned_cache_root(workspace_root, environ=environ)
    if root is None:
        return {"removed_files": 0, "removed_bytes": 0}
    with _cache_mutation_lock(root):
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
    return {"removed_files": before["file_count"], "removed_bytes": before["size_bytes"]}
