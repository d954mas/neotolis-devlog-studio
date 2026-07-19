"""Bounded ScrapeCreators collector for the local Pattern Lab.

The collector deliberately fetches one Reels page per selected author.  The
provider charges one credit per request, so the request count is also a simple,
visible cost ceiling.  Secrets stay in the Studio process environment and are
never returned by the status API.
"""
from __future__ import annotations

import os
from collections.abc import Callable, Mapping
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import urlencode

from dlstudio.services import research


PROVIDER = "scrapecreators"
DEFAULT_BASE_URL = "https://api.scrapecreators.com"
REELS_PATH = "/v1/instagram/user/reels"
POSTS_PATH = "/v2/instagram/user/posts"
MAX_AUTHORS_PER_SYNC = 25
CREDITS_PER_AUTHOR = 1
MAX_CREDITS_PER_AUTHOR = 2
FREE_CREDITS = 100
PAID_PRICE_PER_1000_REQUESTS_USD = 1.88


class ScrapeCreatorsError(RuntimeError):
    """Raised when the collector is unavailable or the provider rejects a run."""


class ScrapeCreatorsNotFoundError(ScrapeCreatorsError):
    """Raised when a provider endpoint cannot resolve an otherwise valid profile."""


FetchJson = Callable[[str, Mapping[str, str], float], Mapping[str, Any]]


def collector_status(*, environ: Mapping[str, str] | None = None) -> dict[str, Any]:
    values = environ if environ is not None else os.environ
    return {
        "provider": PROVIDER,
        "configured": bool(values.get("SCRAPECREATORS_API_KEY", "").strip()),
        "max_authors_per_sync": MAX_AUTHORS_PER_SYNC,
        "credits_per_author": CREDITS_PER_AUTHOR,
        "max_credits_per_author": MAX_CREDITS_PER_AUTHOR,
        "free_credits": FREE_CREDITS,
        "paid_price_per_1000_requests_usd": PAID_PRICE_PER_1000_REQUESTS_USD,
        "max_paid_cost_per_sync_usd": round(
            MAX_AUTHORS_PER_SYNC * MAX_CREDITS_PER_AUTHOR
            * PAID_PRICE_PER_1000_REQUESTS_USD / 1000,
            4,
        ),
    }


def _request_json(url: str, headers: Mapping[str, str], timeout: float) -> Mapping[str, Any]:
    import requests

    try:
        response = requests.get(url, headers=dict(headers), timeout=(10, timeout))
    except requests.RequestException as exc:
        raise ScrapeCreatorsError(f"ScrapeCreators request failed: {exc}") from exc
    if response.status_code == 401 or response.status_code == 403:
        raise ScrapeCreatorsError("ScrapeCreators API key is invalid or has been revoked")
    if response.status_code == 402:
        raise ScrapeCreatorsError("ScrapeCreators credits are exhausted")
    if response.status_code == 404:
        raise ScrapeCreatorsNotFoundError("Instagram author was not found or is unavailable")
    if response.status_code == 429:
        raise ScrapeCreatorsError("ScrapeCreators rate limit reached; try again later")
    try:
        response.raise_for_status()
        payload = response.json()
    except (requests.RequestException, ValueError) as exc:
        raise ScrapeCreatorsError("ScrapeCreators returned an invalid response") from exc
    if not isinstance(payload, Mapping):
        raise ScrapeCreatorsError("ScrapeCreators returned an unexpected response shape")
    return payload


def _project_authors(workspace_root: Path, project_id: str) -> list[dict[str, Any]]:
    payload = research.load_store(workspace_root)
    project = next((item for item in payload["projects"] if item.get("id") == project_id), None)
    if project is None:
        raise research.ResearchError(f"unknown research project: {project_id}")
    return list(project.get("authors", []))


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _optional_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return None
    return max(0.0, parsed)


def _caption(media: Mapping[str, Any]) -> str:
    value = media.get("caption")
    if isinstance(value, Mapping):
        text = value.get("text")
        return text if isinstance(text, str) else ""
    return value if isinstance(value, str) else ""


def _thumbnail(media: Mapping[str, Any]) -> str:
    versions = media.get("image_versions2")
    if isinstance(versions, Mapping):
        candidates = versions.get("candidates")
        if isinstance(candidates, list) and candidates and isinstance(candidates[0], Mapping):
            url = candidates[0].get("url")
            if isinstance(url, str):
                return url
    display_uri = media.get("display_uri")
    return display_uri if isinstance(display_uri, str) else ""


def _timestamp(value: Any) -> str | None:
    try:
        seconds = float(value)
    except (TypeError, ValueError):
        return None
    return datetime.fromtimestamp(seconds, tz=timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )


def _normalize_reel(media: Mapping[str, Any], author_id: str) -> dict[str, Any] | None:
    reel_id = str(media.get("id") or media.get("pk") or media.get("code") or "").strip()
    published_at = _timestamp(media.get("taken_at"))
    if not reel_id or published_at is None:
        return None
    code = str(media.get("code") or "").strip()
    raw_url = media.get("url")
    url = raw_url if isinstance(raw_url, str) and raw_url else (
        f"https://www.instagram.com/reel/{code}/" if code else ""
    )
    if not url:
        return None
    views = media.get("play_count")
    if views is None:
        views = media.get("ig_play_count")
    return {
        "reel_id": reel_id,
        "author_id": author_id,
        "url": url,
        "published_at": published_at,
        "caption": _caption(media),
        "thumbnail_url": _thumbnail(media),
        "duration_seconds": _optional_float(media.get("video_duration")),
        "views": _nonnegative_int(views),
        "likes": _nonnegative_int(media.get("like_count")),
        "comments": _nonnegative_int(media.get("comment_count")),
        "platform": "instagram",
    }


def sync_project(
    workspace_root: Path,
    project_id: str,
    *,
    author_ids: list[str] | None = None,
    api_key: str | None = None,
    base_url: str | None = None,
    fetch_json: FetchJson | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Fetch one current Reels page for every selected author and import it."""
    key = (api_key if api_key is not None else os.environ.get("SCRAPECREATORS_API_KEY", "")).strip()
    if not key:
        raise ScrapeCreatorsError(
            "ScrapeCreators is not configured; set SCRAPECREATORS_API_KEY before starting Studio"
        )
    authors = _project_authors(workspace_root, project_id)
    by_id = {str(item["id"]): item for item in authors}
    selected_ids = author_ids if author_ids is not None else list(by_id)
    if not selected_ids:
        raise research.ResearchError("add at least one author before syncing")
    if len(selected_ids) > MAX_AUTHORS_PER_SYNC:
        raise research.ResearchError(
            f"a sync is limited to {MAX_AUTHORS_PER_SYNC} authors "
            f"(up to {MAX_AUTHORS_PER_SYNC * MAX_CREDITS_PER_AUTHOR} credits)"
        )
    unknown = [author_id for author_id in selected_ids if author_id not in by_id]
    if unknown:
        raise research.ResearchError(f"unknown author: {unknown[0]}")

    captured = now or datetime.now(timezone.utc)
    if captured.tzinfo is None:
        captured = captured.replace(tzinfo=timezone.utc)
    captured_at = captured.astimezone(timezone.utc).isoformat(timespec="seconds").replace(
        "+00:00", "Z"
    )
    requester = fetch_json or _request_json
    endpoint = (base_url or os.environ.get("SCRAPECREATORS_BASE_URL") or DEFAULT_BASE_URL).rstrip("/")
    imported = 0
    received = 0
    skipped = 0
    failures: list[dict[str, str]] = []
    credits_remaining: int | None = None
    requests_made = 0
    authors_completed = 0

    for author_id in selected_ids:
        url = f"{endpoint}{REELS_PATH}?{urlencode({'handle': by_id[author_id]['username']})}"
        requests_made += 1
        used_posts_fallback = False
        try:
            payload = requester(url, {"x-api-key": key, "Accept": "application/json"}, 45.0)
        except ScrapeCreatorsNotFoundError:
            # Some public profiles return 404 from the dedicated Reels surface
            # even though their profile grid contains clips.  The posts surface
            # is the verified fallback; keep only product_type=clips below.
            fallback_url = (
                f"{endpoint}{POSTS_PATH}?"
                f"{urlencode({'handle': by_id[author_id]['username']})}"
            )
            requests_made += 1
            used_posts_fallback = True
            try:
                payload = requester(
                    fallback_url,
                    {"x-api-key": key, "Accept": "application/json"},
                    45.0,
                )
            except ScrapeCreatorsError as exc:
                failures.append({"author_id": author_id, "error": str(exc)})
                continue
        except ScrapeCreatorsError as exc:
            failures.append({"author_id": author_id, "error": str(exc)})
            if "API key" in str(exc) or "credits are exhausted" in str(exc):
                break
            continue
        balance = payload.get("credits_remaining")
        if isinstance(balance, (int, float)):
            credits_remaining = max(0, int(balance))
        raw_items = payload.get("items")
        if not isinstance(raw_items, list):
            failures.append({"author_id": author_id, "error": "unexpected provider response"})
            continue
        authors_completed += 1
        received += len(raw_items)
        for item in raw_items:
            media = (
                item
                if used_posts_fallback and isinstance(item, Mapping)
                else item.get("media") if isinstance(item, Mapping) else None
            )
            if not isinstance(media, Mapping):
                skipped += 1
                continue
            if used_posts_fallback and media.get("product_type") != "clips":
                continue
            normalized = _normalize_reel(media, author_id)
            if normalized is None:
                skipped += 1
                continue
            research.ingest_reel(
                workspace_root,
                project_id,
                **normalized,
                metrics_captured_at=captured_at,
            )
            imported += 1

    author_medians = research.refresh_author_medians(
        workspace_root,
        project_id,
        selected_ids,
    )

    return {
        "provider": PROVIDER,
        "authors_requested": len(selected_ids),
        "authors_completed": authors_completed,
        "credits_used": requests_made,
        "max_credits": len(selected_ids) * MAX_CREDITS_PER_AUTHOR,
        "credits_remaining": credits_remaining,
        "items_received": received,
        "reels_imported": imported,
        "items_skipped": skipped,
        "author_medians": author_medians,
        "failures": failures,
        "captured_at": captured_at,
    }
