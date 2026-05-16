"""Beat timeline summaries for planning and render status checks."""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path

from devlog.types import Beat, Edit


@dataclass(frozen=True)
class BeatSummary:
    beat_id: str
    title: str
    duration: float | None
    words: int | None
    chunks: int
    rendered: bool
    output: str


def _resolve(root: Path, path: str) -> Path:
    p = Path(path)
    return p if p.is_absolute() else root / p


def _audio_duration(path: Path) -> float | None:
    if not path.exists():
        return None
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def _words_info(path: Path) -> tuple[int | None, float | None]:
    if not path.exists():
        return None, None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None, None
    words = data.get("words")
    if not isinstance(words, list):
        return None, None
    duration = None
    if words:
        try:
            duration = float(words[-1]["end"])
        except Exception:
            duration = None
    return len(words), duration


def summarize_edit(edit: Edit, root: Path, suffix: str = "_video_1080p") -> list[BeatSummary]:
    summaries: list[BeatSummary] = []
    for beat_id in edit.order:
        beat: Beat = edit.beats[beat_id]
        audio_path = _resolve(root, beat.audio)
        words_path = _resolve(root, beat.words)
        words_count, words_duration = _words_info(words_path)
        duration = _audio_duration(audio_path) or words_duration
        output = f"data/finalize/{beat_id}{suffix}.mp4"
        summaries.append(BeatSummary(
            beat_id=beat_id,
            title=beat.title,
            duration=duration,
            words=words_count,
            chunks=len(beat.chunks),
            rendered=_resolve(root, output).exists(),
            output=output,
        ))
    return summaries


def format_summaries(summaries: list[BeatSummary]) -> str:
    if not summaries:
        return "No beats in edit order."
    lines = ["beat       dur     words  chunks  rendered  title"]
    total = 0.0
    known = 0
    for s in summaries:
        if s.duration is None:
            dur = "?"
        else:
            total += s.duration
            known += 1
            mins = int(s.duration // 60)
            secs = int(round(s.duration % 60))
            dur = f"{mins}:{secs:02d}"
        words = "?" if s.words is None else str(s.words)
        rendered = "yes" if s.rendered else "no"
        lines.append(f"{s.beat_id:<10} {dur:<7} {words:<6} {s.chunks:<7} {rendered:<8} {s.title}")
    if known:
        mins = int(total // 60)
        secs = int(round(total % 60))
        lines.append(f"\ntotal known duration: {mins}:{secs:02d} across {known}/{len(summaries)} beats")
    return "\n".join(lines)
