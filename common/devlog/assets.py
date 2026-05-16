"""Asset inventory helpers for devlog edits."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from PIL import Image

from devlog.cache import _walk_asset_paths
from devlog.types import Edit


MEDIA_SUFFIXES = {
    ".png", ".jpg", ".jpeg", ".webp",
    ".mp4", ".mov", ".mkv", ".webm",
    ".wav", ".m4a", ".mp3", ".ogg", ".opus",
    ".json",
}

GENERATED_DATA_DIRS = (
    "data/finalize/",
    "data/recordings/",
    "data/review/",
)


@dataclass(frozen=True)
class AssetReport:
    used: list[str]
    missing: list[str]
    unused: list[str]
    low_res: list[str]


def _resolve(root: Path, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else root / p


def _rel(root: Path, path: Path) -> str:
    try:
        return path.relative_to(root).as_posix()
    except ValueError:
        return path.as_posix()


def collect_used_assets(edit: Edit) -> list[str]:
    used: list[str] = []
    for bid in edit.order:
        for path in _walk_asset_paths(edit.beats[bid]):
            if path not in used:
                used.append(path)
    return used


def _iter_data_files(root: Path) -> list[Path]:
    data = root / "data"
    if not data.exists():
        return []
    out = []
    for path in data.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root).as_posix()
        if (
            "/.cache/" in rel
            or rel.endswith("_ffmpeg_error.txt")
            or any(rel.startswith(prefix) for prefix in GENERATED_DATA_DIRS)
        ):
            continue
        if path.suffix.lower() in MEDIA_SUFFIXES:
            out.append(path)
    return out


def _target_size(edit: Edit, target_width: int | None) -> tuple[int, int]:
    if not target_width:
        return edit.design.W, edit.design.H
    return target_width, int(round(target_width * edit.design.H / edit.design.W))


def _image_uses(edit: Edit, target_width: int | None) -> list[tuple[str, str, int, int]]:
    target_w, target_h = _target_size(edit, target_width)
    uses: list[tuple[str, str, int, int]] = []
    for bid in edit.order:
        beat = edit.beats[bid]
        if beat.scene:
            uses.append((beat.scene.src, beat.scene.fit, target_w, target_h))
        for ch in beat.chunks:
            if ch.src:
                if ch.framed_card:
                    card_w = int(target_w * 0.78)
                    card_h = int(card_w * 9 / 16)
                    uses.append((ch.src, "cover", card_w, card_h))
                else:
                    uses.append((ch.src, ch.fit, target_w, target_h))
            if ch.bg_image:
                uses.append((ch.bg_image, "cover", target_w, target_h))
            if ch.scene:
                uses.append((ch.scene.src, ch.scene.fit, target_w, target_h))
    return uses


def _would_upscale(src_w: int, src_h: int, fit: str, target_w: int, target_h: int) -> bool:
    if fit == "contain":
        return src_w < target_w and src_h < target_h
    return src_w < target_w or src_h < target_h


def asset_report(edit: Edit, root: Path, target_width: int | None = None) -> AssetReport:
    used_raw = collect_used_assets(edit)
    used_abs = {_resolve(root, p).resolve() for p in used_raw}
    missing = [p for p in used_raw if not _resolve(root, p).exists()]

    unused = []
    for path in _iter_data_files(root):
        if path.resolve() not in used_abs:
            unused.append(_rel(root, path))

    low_res = []
    seen_low_res: set[str] = set()
    for raw, fit, target_w, target_h in _image_uses(edit, target_width):
        if raw in seen_low_res:
            continue
        path = _resolve(root, raw)
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not path.exists():
            continue
        try:
            with Image.open(path) as img:
                w, h = img.size
        except Exception:
            continue
        if _would_upscale(w, h, fit, target_w, target_h):
            low_res.append(f"{raw} ({w}x{h} upscales for {fit} {target_w}x{target_h})")
            seen_low_res.add(raw)

    return AssetReport(
        used=used_raw,
        missing=missing,
        unused=sorted(unused),
        low_res=low_res,
    )


def format_asset_report(report: AssetReport, *, show_used: bool = False, show_unused: bool = False) -> str:
    lines = [
        f"used: {len(report.used)}",
        f"missing: {len(report.missing)}",
        f"unused: {len(report.unused)}",
        f"low_res: {len(report.low_res)}",
    ]
    if report.missing:
        lines.append("\nmissing:")
        lines.extend(f"  {p}" for p in report.missing)
    if report.low_res:
        lines.append("\nlow-res images:")
        lines.extend(f"  {p}" for p in report.low_res)
    if show_unused and report.unused:
        lines.append("\nunused:")
        lines.extend(f"  {p}" for p in report.unused)
    if show_used and report.used:
        lines.append("\nused:")
        lines.extend(f"  {p}" for p in report.used)
    return "\n".join(lines)
