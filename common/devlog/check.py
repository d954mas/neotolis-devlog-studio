"""Project validation for devlog edits.

`dl check <edit>` is intentionally cheap: it validates the Python edit model,
referenced files, word-index ranges, and obvious chunk/scene mistakes before a
render spends time in ffmpeg.
"""
from __future__ import annotations

import json
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Literal

from devlog.types import Beat, Chunk, Edit, Scene


Severity = Literal["error", "warning"]


@dataclass(frozen=True)
class CheckIssue:
    severity: Severity
    code: str
    message: str


def _resolve(root: Path, path: str | None) -> Path | None:
    if not path:
        return None
    p = Path(path)
    return p if p.is_absolute() else root / p


def _asset_issue(root: Path, path: str | None, where: str, issues: list[CheckIssue]) -> None:
    p = _resolve(root, path)
    if p is None:
        issues.append(CheckIssue("error", "missing-path", f"{where}: path is required"))
    elif not p.exists():
        issues.append(CheckIssue("error", "missing-asset", f"{where}: file not found: {path}"))


def _load_words(root: Path, beat_id: str, beat: Beat, issues: list[CheckIssue]) -> list[dict] | None:
    words_path = _resolve(root, beat.words)
    if words_path is None or not words_path.exists():
        issues.append(CheckIssue("error", "missing-words", f"{beat_id}: words file not found: {beat.words}"))
        return None
    try:
        data = json.loads(words_path.read_text(encoding="utf-8"))
    except Exception as exc:
        issues.append(CheckIssue("error", "bad-words-json", f"{beat_id}: cannot read words JSON: {exc}"))
        return None
    words = data.get("words")
    if not isinstance(words, list) or not words:
        issues.append(CheckIssue("error", "empty-words", f"{beat_id}: words JSON has no non-empty 'words' list"))
        return None
    for i, word in enumerate(words):
        if not isinstance(word, dict) or "start" not in word or "end" not in word:
            issues.append(CheckIssue("error", "bad-word-entry", f"{beat_id}: word #{i} lacks start/end"))
            return None
    return words


def _check_scene(root: Path, scene: Scene | None, where: str, issues: list[CheckIssue]) -> None:
    if scene is None:
        return
    _asset_issue(root, scene.src, f"{where} scene", issues)
    if scene.kind not in ("video", "image"):
        issues.append(CheckIssue("error", "bad-scene-kind", f"{where}: unknown scene kind {scene.kind!r}"))
    if scene.offset < 0:
        issues.append(CheckIssue("error", "bad-scene-offset", f"{where}: scene offset must be >= 0"))
    if scene.fit not in ("cover", "contain"):
        issues.append(CheckIssue("error", "bad-fit", f"{where}: fit must be cover or contain"))


def _probe_media_duration(path: Path) -> float | None:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "csv=p=0", str(path)],
        capture_output=True,
        text=True,
    )
    if r.returncode != 0:
        return None
    try:
        return float(r.stdout.strip())
    except ValueError:
        return None


def _check_video_duration(root: Path, path: str | None, offset: float, where: str, issues: list[CheckIssue]) -> None:
    p = _resolve(root, path)
    if p is None or not p.exists():
        return
    duration = _probe_media_duration(p)
    if duration is None:
        issues.append(CheckIssue("warning", "unprobeable-media", f"{where}: ffprobe could not read duration for {path}"))
        return
    if offset >= duration - 0.1:
        issues.append(CheckIssue(
            "warning",
            "video-offset-past-eof",
            f"{where}: offset {offset:.2f}s is past media duration {duration:.2f}s: {path}",
        ))


def _check_chunk(
    root: Path,
    beat_id: str,
    idx: int,
    chunk: Chunk,
    words_count: int | None,
    default_scene: Scene | None,
    issues: list[CheckIssue],
    deep: bool,
) -> None:
    where = f"{beat_id} chunk {idx}"
    if chunk.kind not in ("plate", "overlay", "image", "video"):
        issues.append(CheckIssue("error", "bad-chunk-kind", f"{where}: unknown kind {chunk.kind!r}"))

    start, end = chunk.words
    if start < 0 or end < 0 or end < start:
        issues.append(CheckIssue("error", "bad-word-range", f"{where}: invalid word range {chunk.words}"))
    if words_count is not None and (start >= words_count or end >= words_count):
        issues.append(CheckIssue(
            "error",
            "word-range-out-of-bounds",
            f"{where}: word range {chunk.words} exceeds words length {words_count}",
        ))

    if chunk.kind in ("plate", "overlay") and not chunk.text and chunk.kind == "plate":
        issues.append(CheckIssue("warning", "empty-text", f"{where}: plate has empty text"))
    if chunk.kind == "image":
        _asset_issue(root, chunk.src, where, issues)
    if chunk.kind == "video":
        _asset_issue(root, chunk.src, where, issues)
    if chunk.bg_image:
        _asset_issue(root, chunk.bg_image, f"{where} bg_image", issues)
    _check_scene(root, chunk.scene, where, issues)

    if chunk.kind == "overlay" and not chunk.scene and default_scene is None:
        issues.append(CheckIssue("warning", "scene-less-overlay", f"{where}: overlay has no scene and beat has no default scene"))
    if chunk.fit not in ("cover", "contain"):
        issues.append(CheckIssue("error", "bad-fit", f"{where}: fit must be cover or contain"))
    if chunk.position not in ("bottom", "top", "middle"):
        issues.append(CheckIssue("error", "bad-position", f"{where}: bad overlay position {chunk.position!r}"))
    if chunk.style not in ("band", "card", "hero"):
        issues.append(CheckIssue("error", "bad-style", f"{where}: bad overlay style {chunk.style!r}"))
    if deep:
        if chunk.kind == "video":
            _check_video_duration(root, chunk.src, chunk.offset, where, issues)
        if chunk.scene and chunk.scene.kind == "video":
            _check_video_duration(root, chunk.scene.src, chunk.scene.offset, f"{where} scene", issues)


def check_edit(edit: Edit, root: Path, deep: bool = False) -> list[CheckIssue]:
    """Return validation issues for an edit rooted at `root`."""
    issues: list[CheckIssue] = []
    for name, path in (
        ("display", edit.design.fonts.display),
        ("text", edit.design.fonts.text),
        ("mono", edit.design.fonts.mono),
        ("emoji", edit.design.fonts.emoji),
    ):
        if path and not Path(path).exists():
            issues.append(CheckIssue("warning", "missing-font", f"{name} font not found: {path}"))
    if not edit.order:
        issues.append(CheckIssue("error", "empty-order", "edit order is empty"))

    seen: set[str] = set()
    for bid in edit.order:
        if bid in seen:
            issues.append(CheckIssue("error", "duplicate-beat", f"beat {bid!r} appears more than once in order"))
        seen.add(bid)
        if bid not in edit.beats:
            issues.append(CheckIssue("error", "unknown-beat", f"order references missing beat {bid!r}"))

    for bid in edit.beats:
        if bid not in seen:
            issues.append(CheckIssue("warning", "unused-beat", f"beat {bid!r} is defined but not in order"))

    for bid, beat in edit.beats.items():
        _asset_issue(root, beat.audio, f"{bid} audio", issues)
        words = _load_words(root, bid, beat, issues)
        words_count = len(words) if words is not None else None
        _check_scene(root, beat.scene, f"{bid} default", issues)
        if deep and beat.scene and beat.scene.kind == "video":
            _check_video_duration(root, beat.scene.src, beat.scene.offset, f"{bid} default scene", issues)
        if not beat.chunks:
            issues.append(CheckIssue("error", "empty-beat", f"{bid}: beat has no chunks"))
            continue
        prev_start = -1
        for idx, chunk in enumerate(beat.chunks):
            if chunk.words[0] < prev_start:
                issues.append(CheckIssue("error", "non-monotonic-chunks", f"{bid} chunk {idx}: word start moves backwards"))
            prev_start = chunk.words[0]
            _check_chunk(root, bid, idx, chunk, words_count, beat.scene, issues, deep)

    return issues


def format_issues(issues: list[CheckIssue]) -> str:
    if not issues:
        return "No issues found."
    lines = []
    for issue in issues:
        tag = "ERROR" if issue.severity == "error" else "WARN"
        lines.append(f"[{tag}] {issue.code}: {issue.message}")
    return "\n".join(lines)
