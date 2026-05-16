"""Detect beat renders that are missing or older than their inputs."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from devlog.cache import _walk_asset_paths
from devlog.types import Edit


@dataclass(frozen=True)
class StaleBeat:
    beat_id: str
    output: str
    reason: str


def _resolve(root: Path, path: str | Path) -> Path:
    p = Path(path)
    return p if p.is_absolute() else root / p


def stale_beats(
    edit: Edit,
    root: Path,
    *,
    suffix: str = "_video_1080p",
    source_paths: list[Path] | None = None,
) -> list[StaleBeat]:
    source_paths = source_paths or []
    out: list[StaleBeat] = []
    for beat_id in edit.order:
        beat = edit.beats[beat_id]
        output = f"data/finalize/{beat_id}{suffix}.mp4"
        output_path = _resolve(root, output)
        if not output_path.exists():
            out.append(StaleBeat(beat_id=beat_id, output=output, reason="missing render"))
            continue

        output_mtime = output_path.stat().st_mtime
        stale_reason: str | None = None
        for source in source_paths:
            source_path = _resolve(root, source)
            if source_path.exists() and source_path.stat().st_mtime > output_mtime:
                stale_reason = f"source newer: {source_path.name}"
                break
        if stale_reason is None:
            for raw in _walk_asset_paths(beat):
                asset_path = _resolve(root, raw)
                if not asset_path.exists():
                    stale_reason = f"missing asset: {raw}"
                    break
                if asset_path.stat().st_mtime > output_mtime:
                    stale_reason = f"asset newer: {raw}"
                    break
        if stale_reason:
            out.append(StaleBeat(beat_id=beat_id, output=output, reason=stale_reason))
    return out


def format_stale(beats: list[StaleBeat]) -> str:
    if not beats:
        return "No stale beat renders."
    lines = ["beat       output                         reason"]
    for beat in beats:
        lines.append(f"{beat.beat_id:<10} {beat.output:<30} {beat.reason}")
    return "\n".join(lines)
