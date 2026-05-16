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
        if "/.cache/" in rel or rel.endswith("_ffmpeg_error.txt"):
            continue
        if path.suffix.lower() in MEDIA_SUFFIXES:
            out.append(path)
    return out


def asset_report(edit: Edit, root: Path, target_width: int | None = None) -> AssetReport:
    used_raw = collect_used_assets(edit)
    used_abs = {_resolve(root, p).resolve() for p in used_raw}
    missing = [p for p in used_raw if not _resolve(root, p).exists()]

    unused = []
    for path in _iter_data_files(root):
        if path.resolve() not in used_abs:
            unused.append(_rel(root, path))

    low_res = []
    min_width = target_width or edit.design.W
    for raw in used_raw:
        path = _resolve(root, raw)
        if path.suffix.lower() not in {".png", ".jpg", ".jpeg", ".webp"} or not path.exists():
            continue
        try:
            with Image.open(path) as img:
                w, h = img.size
        except Exception:
            continue
        if w < min_width:
            low_res.append(f"{raw} ({w}x{h} < {min_width}px wide)")

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
