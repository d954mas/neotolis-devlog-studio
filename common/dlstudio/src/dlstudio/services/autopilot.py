"""Deterministic asset inventory and shot-ledger preflight.

These helpers intentionally contain no AI runtime.  They turn files and a
planner-authored shot manifest into facts that CLI/UI/reviewer agents can use
before a render is attempted.
"""
from __future__ import annotations

import hashlib
import json
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from PIL import Image
from pydantic import BaseModel, ConfigDict, Field

from dlstudio.ir import CheckIssue, CheckReport


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class AssetRecord(_Model):
    path: str
    sha256: str
    size: int
    modified_at: str
    kind: Literal["image", "video", "audio", "font", "other"]
    width: int | None = None
    height: int | None = None
    duration: float | None = None
    fps: float | None = None
    orientation: Literal["landscape", "vertical", "square", "unknown"] = "unknown"
    intended_for: Literal["landscape", "vertical", "both", "unknown"] = "unknown"
    provenance: str = "unknown"
    source_role: Literal["real_product", "reference", "illustration", "generated", "other"] = "other"
    quality_flags: list[str] = Field(default_factory=list)


class AssetCatalog(_Model):
    version: int = 1
    root: str
    created_at: str = ""
    assets: list[AssetRecord] = Field(default_factory=list)


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}
_AUDIO_EXTS = {".wav", ".mp3", ".ogg", ".flac", ".m4a", ".aac"}
_FONT_EXTS = {".ttf", ".otf", ".woff", ".woff2"}
_SCAN_DIRS = ("footage", "images", "music", "sfx", "fonts", "infographics")


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _orientation(width: int | None, height: int | None) -> tuple[str, str]:
    if not width or not height:
        return "unknown", "unknown"
    ratio = width / height
    if 0.9 <= ratio <= 1.1:
        return "square", "both"
    if width > height:
        return "landscape", "landscape"
    return "vertical", "vertical"


def _kind(path: Path) -> str:
    ext = path.suffix.lower()
    if ext in _IMAGE_EXTS:
        return "image"
    if ext in _VIDEO_EXTS:
        return "video"
    if ext in _AUDIO_EXTS:
        return "audio"
    if ext in _FONT_EXTS:
        return "font"
    return "other"


def _probe(path: Path, kind: str) -> tuple[int | None, int | None, float | None, float | None, list[str]]:
    flags: list[str] = []
    if kind == "image":
        try:
            with Image.open(path) as image:
                width, height = image.size
            return width, height, None, None, flags
        except OSError:
            return None, None, None, None, ["unreadable"]
    if kind not in {"video", "audio"}:
        return None, None, None, None, flags
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_streams", "-show_format", str(path),
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError:
        return None, None, None, None, ["unprobed"]
    if result.returncode:
        return None, None, None, None, ["unreadable"]
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError:
        return None, None, None, None, ["unreadable"]
    video = next((s for s in payload.get("streams", []) if s.get("codec_type") == "video"), {})
    width = video.get("width")
    height = video.get("height")
    duration_raw = payload.get("format", {}).get("duration")
    try:
        duration = float(duration_raw)
    except (TypeError, ValueError):
        duration = None
    fps = None
    rate = video.get("avg_frame_rate")
    if isinstance(rate, str) and "/" in rate:
        left, right = rate.split("/", 1)
        try:
            fps = float(left) / float(right) if float(right) else None
        except ValueError:
            pass
    return width, height, duration, fps, flags


def _source_facts(rel: str) -> tuple[str, str]:
    value = rel.casefold().replace("\\", "/")
    if "/footage/" in value and any(token in value for token in ("game", "gameplay", "old2d", "new3d")):
        return "game_capture", "real_product"
    if "/infographics/" in value or "/hyperframes/" in value:
        return "generated", "generated"
    if "canvas" in value:
        return "canvas", "reference"
    if "steam" in value:
        return "steam", "real_product"
    if "diary" in value or "wishlist" in value:
        return "diary", "real_product"
    if "/footage/" in value:
        return "screen_capture", "real_product"
    if "/images/" in value:
        return "image", "illustration"
    return "unknown", "other"


def build_asset_catalog(root: str | Path, *, out_path: str | Path | None = None) -> AssetCatalog:
    base = Path(root).resolve()
    candidates: set[Path] = set()
    for name in _SCAN_DIRS:
        folder = base / "data" / name
        if folder.is_dir():
            candidates.update(path for path in folder.rglob("*") if path.is_file())
    shared = base
    for candidate in (base, *base.parents):
        if (candidate / "product.toml").is_file():
            shared = candidate / "shared" / "assets"
            break
    if shared.is_dir():
        candidates.update(path for path in shared.rglob("*") if path.is_file())

    assets: list[AssetRecord] = []
    for path in sorted(candidates):
        kind = _kind(path)
        if kind == "other":
            continue
        try:
            rel = path.relative_to(base).as_posix()
        except ValueError:
            rel = path.as_posix()
        width, height, duration, fps, flags = _probe(path, kind)
        orientation, intended = _orientation(width, height)
        provenance, source_role = _source_facts(rel)
        stat = path.stat()
        assets.append(AssetRecord(
            path=rel,
            sha256=_sha256(path),
            size=stat.st_size,
            modified_at=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            kind=kind,
            width=width,
            height=height,
            duration=duration,
            fps=fps,
            orientation=orientation,
            intended_for=intended,
            provenance=provenance,
            source_role=source_role,
            quality_flags=flags,
        ))
    by_hash: dict[str, list[AssetRecord]] = {}
    for asset in assets:
        by_hash.setdefault(asset.sha256, []).append(asset)
    for group in by_hash.values():
        if len(group) > 1:
            for asset in group:
                if "duplicate" not in asset.quality_flags:
                    asset.quality_flags.append("duplicate")

    catalog = AssetCatalog(
        root=str(base),
        created_at=datetime.now(timezone.utc).isoformat(),
        assets=assets,
    )
    if out_path is not None:
        destination = Path(out_path)
        destination.parent.mkdir(parents=True, exist_ok=True)
        destination.write_text(
            json.dumps(catalog.model_dump(mode="json"), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    return catalog


def validate_shot_manifest(
    shots: list[dict],
    catalog: AssetCatalog,
    *,
    orientation: Literal["landscape", "vertical"],
    final: bool = False,
) -> CheckReport:
    issues: list[CheckIssue] = []
    assets = {asset.path.replace("\\", "/"): asset for asset in catalog.assets}
    used: dict[str, list[dict]] = {}
    ids: set[str] = set()

    for index, shot in enumerate(shots):
        shot_id = str(shot.get("id") or f"shot-{index}")
        where = shot_id
        if shot_id in ids:
            issues.append(CheckIssue(severity="error", code="VQ-DUP", message="duplicate shot id", where=where))
        ids.add(shot_id)
        src = str(shot.get("src") or "").replace("\\", "/")
        used.setdefault(src, []).append(shot)
        try:
            duration = float(shot.get("t1", 0)) - float(shot.get("t0", 0))
        except (TypeError, ValueError):
            duration = 0.0
        minimum = float(shot.get("min_readable_duration", 0) or 0)
        intent = str(shot.get("intent", "normal"))
        motion = str(shot.get("motion", "none"))
        if duration + 1e-9 < minimum:
            issues.append(CheckIssue(
                severity="error", code="VQ-READ",
                message=f"shot lasts {duration:.2f}s, below readable minimum {minimum:.2f}s",
                where=where,
            ))
        if duration < 1.2 and intent not in {"flash", "montage"}:
            issues.append(CheckIssue(
                severity="error" if final else "warn", code="VQ-PACE",
                message=f"ordinary shot is only {duration:.2f}s (<1.2s)", where=where,
            ))
        if duration > 6.0 and motion in {"", "none", "static"} and intent != "deliberate_hold":
            issues.append(CheckIssue(
                severity="error" if final else "warn", code="VQ-PACE",
                message=f"static shot lasts {duration:.2f}s without deliberate_hold", where=where,
            ))
        elif duration > 4.0 and motion in {"", "none", "static"}:
            issues.append(CheckIssue(
                severity="warn", code="VQ-PACE",
                message=f"static shot lasts {duration:.2f}s without motion", where=where,
            ))
        if final and not bool(shot.get("approved")):
            issues.append(CheckIssue(
                severity="error", code="VQ-SOURCE", message="shot is not approved", where=where,
            ))

        asset = assets.get(src)
        if asset is None:
            issues.append(CheckIssue(
                severity="error", code="VQ-SOURCE", message=f"shot source is absent from catalog: {src}", where=where,
            ))
            continue
        declared_role = str(shot.get("source_role", ""))
        purpose = str(shot.get("purpose", ""))
        if declared_role and declared_role != asset.source_role:
            issues.append(CheckIssue(
                severity="error", code="VQ-SOURCE",
                message=f"declared role {declared_role!r} differs from catalog role {asset.source_role!r}",
                where=where,
            ))
        if "real" in purpose.casefold() and asset.source_role != "real_product":
            issues.append(CheckIssue(
                severity="error", code="VQ-SOURCE",
                message="real-product claim uses a non-product source", where=where,
            ))
        # An opposite-orientation source is unsafe only when it is treated as
        # the frame itself.  A landscape gameplay capture inside an explicit
        # vertical inset/split card preserves its native pixels and is a
        # legitimate proof shot; silently center-cropping it full-bleed is not.
        presentation = str(shot.get("presentation", "full_bleed"))
        orientation_safe_presentations = {"inset", "framed", "contain", "split"}
        if (
            asset.intended_for not in {orientation, "both", "unknown"}
            and presentation not in orientation_safe_presentations
        ):
            issues.append(CheckIssue(
                severity="error", code="VQ-SOURCE",
                message=(
                    f"{asset.orientation} source is not intended for {orientation} "
                    "full-bleed use; declare presentation=inset/framed/contain/split"
                ),
                where=where,
            ))
        bad_flags = sorted(set(asset.quality_flags) & {"stale", "unreadable", "upscale", "letterbox"})
        if bad_flags:
            issues.append(CheckIssue(
                severity="error", code="VQ-SOURCE",
                message=f"source quality flags block use: {', '.join(bad_flags)}", where=where,
            ))

    for src, entries in used.items():
        if not src or len(entries) < 2:
            continue
        intentional = all(
            entry.get("reuse") == "callback" or entry.get("intent") == "callback"
            for entry in entries
        )
        if not intentional:
            issues.append(CheckIssue(
                severity="error" if final else "warn", code="VQ-DUP",
                message=f"source reused {len(entries)} times without callback intent: {src}",
                where=src,
            ))
    return CheckReport(issues=issues)
