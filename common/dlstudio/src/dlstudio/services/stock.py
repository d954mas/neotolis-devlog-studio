"""stock: thin B-roll provider wrappers (Pexels / Pixabay).

Ports the provider layer of legacy `common/devlog/stock.py` — commodity
search + download against two stock-video APIs — kept intentionally THIN per
docs/ARCHITECTURE_V2.md's services/ contract: this module is a wrapper over
the provider HTTP APIs, not a ranking/curation engine. The only "logic" here
(aspect-ratio filtering + picking the best-matching file per result, then
sorting by how close the file's pixel count is to the target resolution) is
carried over unchanged from legacy — nothing new is added on top of it.

`requests` is imported lazily inside the functions that actually make an
HTTP call, never at module import time, matching the services/ lazy-import
contract (see services/__init__.py's module docstring): this module must
stay importable even when the `stock` extra isn't installed, and only
blow up (with a clear ImportError) the moment a caller actually tries to
hit the network.

API keys come from the environment: PEXELS_API_KEY / PIXABAY_API_KEY. No
devlog.toml [stock] table support (that was a legacy multi-project config
feature) -- v2 projects that need a stock key set it in their shell/CI env.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ASPECT_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "16:9": (1920, 1080),
    "9:16": (1080, 1920),
    "1:1": (1080, 1080),
}

PEXELS_ORIENTATIONS: dict[str, str] = {
    "16:9": "landscape",
    "9:16": "portrait",
    "1:1": "square",
}

_LICENSE_NOTES: dict[str, str] = {
    "pexels": "Pexels License (free to use, attribution appreciated, not required).",
    "pixabay": "Pixabay Content License (free to use, attribution not required).",
}


class StockConfigError(RuntimeError):
    """Raised when a required provider API key is missing from the
    environment. The message names the exact env var to set so a caller
    never has to go hunting for it."""


@dataclass(frozen=True)
class StockResult:
    """One search hit, normalized across providers.

    `credit` is the uploader/photographer display name (provider's own
    attribution string, not a legal requirement — see `license_note`).
    `query` is carried on the result so a later `download()` call has full
    provenance without the caller having to thread the query through
    separately.
    """

    source: str            # "pexels" | "pixabay"
    id: str
    url: str                # direct download URL of the best-matching file
    preview_url: str
    width: int
    height: int
    duration: float
    credit: str
    license_note: str
    query: str = ""

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _require_api_key(source: str, api_key: str | None) -> str:
    if api_key:
        return api_key
    import os

    env_name = f"{source.upper()}_API_KEY"
    value = os.environ.get(env_name)
    if value:
        return value
    raise StockConfigError(
        f"{source} API key is required. Set the {env_name} environment "
        f"variable, or pass api_key= explicitly."
    )


def _matches_aspect(width: int, height: int, aspect: str, *, tolerance: float = 0.12) -> bool:
    target_w, target_h = ASPECT_RESOLUTIONS[aspect]
    if not width or not height:
        return False
    return abs((width / height) - (target_w / target_h)) <= tolerance


def _sort_key(item: StockResult, aspect: str) -> tuple[float, int]:
    target_w, target_h = ASPECT_RESOLUTIONS[aspect]
    target_pixels = target_w * target_h
    pixels = item.width * item.height
    return (abs(pixels - target_pixels), -pixels)


def _search_pexels(query: str, *, aspect: str, per_page: int, api_key: str) -> list[StockResult]:
    import requests
    from urllib.parse import urlencode

    params = {
        "query": query,
        "per_page": min(max(per_page * 2, 10), 80),
        "orientation": PEXELS_ORIENTATIONS[aspect],
    }
    response = requests.get(
        f"https://api.pexels.com/videos/search?{urlencode(params)}",
        headers={"Authorization": api_key},
        timeout=(30, 60),
    )
    response.raise_for_status()

    out: list[StockResult] = []
    for video in response.json().get("videos", []):
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
        out.append(StockResult(
            source="pexels",
            id=str(video.get("id") or ""),
            url=download_url,
            preview_url=video.get("image") or "",
            width=width,
            height=height,
            duration=float(video.get("duration") or 0),
            credit=(video.get("user") or {}).get("name") or "",
            license_note=_LICENSE_NOTES["pexels"],
            query=query,
        ))
    out.sort(key=lambda item: _sort_key(item, aspect))
    return out[:per_page]


def _search_pixabay(query: str, *, aspect: str, per_page: int, api_key: str) -> list[StockResult]:
    import requests
    from urllib.parse import urlencode

    params = {
        "q": query,
        "video_type": "all",
        "per_page": min(max(per_page * 2, 10), 200),
        "key": api_key,
    }
    response = requests.get(
        f"https://pixabay.com/api/videos/?{urlencode(params)}",
        timeout=(30, 60),
    )
    response.raise_for_status()

    out: list[StockResult] = []
    for video in response.json().get("hits", []):
        files = []
        preview = ""
        for item in (video.get("videos") or {}).values():
            width = int(item.get("width") or 0)
            height = int(item.get("height") or 0)
            if width and height and _matches_aspect(width, height, aspect):
                files.append((width * height, width, height, item.get("url") or ""))
                preview = preview or (item.get("thumbnail") or "")
        if not files:
            continue
        _, width, height, download_url = sorted(files, reverse=True)[0]
        if not download_url:
            continue
        out.append(StockResult(
            source="pixabay",
            id=str(video.get("id") or ""),
            url=download_url,
            preview_url=preview,
            width=width,
            height=height,
            duration=float(video.get("duration") or 0),
            credit=str(video.get("user") or ""),
            license_note=_LICENSE_NOTES["pixabay"],
            query=query,
        ))
    out.sort(key=lambda item: _sort_key(item, aspect))
    return out[:per_page]


_PROVIDERS = {
    "pexels": _search_pexels,
    "pixabay": _search_pixabay,
}


def search(
    query: str,
    *,
    source: str = "pexels",
    aspect: str = "16:9",
    per_page: int = 10,
    api_key: str | None = None,
) -> list[StockResult]:
    """Search a stock provider for b-roll matching `query`.

    `source` selects the provider ("pexels" | "pixabay"). `aspect` is one of
    ASPECT_RESOLUTIONS' keys ("16:9" | "9:16" | "1:1") -- only files that
    roughly match the target aspect ratio are returned, closest-match first,
    capped at `per_page`. The API key is resolved from `api_key`, else the
    PEXELS_API_KEY / PIXABAY_API_KEY environment variable; raises
    `StockConfigError` naming the missing env var if neither is set.
    """
    if source not in _PROVIDERS:
        raise ValueError(f"unsupported stock source: {source!r}. Use one of {sorted(_PROVIDERS)}.")
    if aspect not in ASPECT_RESOLUTIONS:
        raise ValueError(f"unsupported aspect: {aspect!r}. Use one of {sorted(ASPECT_RESOLUTIONS)}.")
    api_key = _require_api_key(source, api_key)
    return _PROVIDERS[source](query, aspect=aspect, per_page=per_page, api_key=api_key)


def _load_items(results_or_manifest: Any) -> list[dict[str, Any]]:
    """Normalize `download()`'s first argument to a list of plain dicts.

    Accepts: a list of StockResult, a list of dicts (e.g. already loaded
    from a `dl2 stock search --out manifest.json` file), or a path (str /
    Path) to such a JSON file on disk.
    """
    if isinstance(results_or_manifest, (str, Path)):
        payload = json.loads(Path(results_or_manifest).read_text(encoding="utf-8-sig"))
        if not isinstance(payload, list):
            raise ValueError(f"{results_or_manifest}: expected a JSON list of stock results")
        return [dict(item) for item in payload]
    items = []
    for item in results_or_manifest:
        items.append(item.to_dict() if isinstance(item, StockResult) else dict(item))
    return items


def _download_file(url: str, dest: Path) -> None:
    import requests

    dest.parent.mkdir(parents=True, exist_ok=True)
    tmp = dest.with_suffix(dest.suffix + ".tmp")
    with requests.get(url, stream=True, timeout=(60, 240)) as response:
        response.raise_for_status()
        with tmp.open("wb") as handle:
            for chunk in response.iter_content(chunk_size=1024 * 1024):
                if chunk:
                    handle.write(chunk)
    tmp.replace(dest)


def download(
    results_or_manifest: Any,
    out_dir: Path | str,
    *,
    retrieved_at: str | None = None,
) -> list[dict[str, Any]]:
    """Download every result to `out_dir` and write `out_dir/manifest.json`
    with per-item provenance: source, id, url, preview_url, credit, license,
    query, retrieved_at, and the saved file name. `preview_url`/`credit` are
    carried through so a later packaging step (e.g. `publish-packager`) can
    place the required attribution without re-hitting the provider API.

    `retrieved_at` is caller-supplied (an ISO-8601 timestamp string) so
    callers/tests get deterministic manifests; when omitted it defaults to
    `datetime.now(timezone.utc).isoformat()` at call time.

    No ranking/dedup beyond what legacy did: entries are downloaded in the
    order given, one file each -- if the caller wants only the top N, slice
    before calling this.
    """
    items = _load_items(results_or_manifest)
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    ts = retrieved_at or datetime.now(timezone.utc).isoformat()

    manifest: list[dict[str, Any]] = []
    for item in items:
        source = item.get("source", "")
        item_id = item.get("id", "")
        url = item.get("url", "")
        if not url:
            continue
        filename = f"{source}_{item_id or len(manifest)}.mp4"
        dest = out_dir / filename
        _download_file(url, dest)
        manifest.append({
            "source": source,
            "id": item_id,
            "url": url,
            "preview_url": item.get("preview_url", ""),
            "credit": item.get("credit", ""),
            "license": item.get("license_note", ""),
            "query": item.get("query", ""),
            "retrieved_at": ts,
            "file": dest.name,
        })

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return manifest
