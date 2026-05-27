"""B-roll planning helpers for shotlists.

This module is intentionally heuristic-only. The chat/agent layer can make the
creative call; the CLI should surface visual gaps, useful search terms, and
local files that are worth checking.
"""
from __future__ import annotations

import re
from dataclasses import asdict, dataclass
from pathlib import Path

from devlog.types import Edit


VISUAL_SUFFIXES = {".png", ".jpg", ".jpeg", ".webp", ".mp4", ".mov", ".mkv", ".webm"}
GENERATED_DATA_PREFIXES = (
    "data/finalize/",
    "data/recordings/",
    "data/review/",
)

KEYWORD_TERMS = (
    (("render", "рендер", "ffmpeg", "compose", "pipeline", "пайплайн"),
     ("render pipeline", "ffmpeg render", "video editing timeline")),
    (("queue", "очеред", "task", "задач"),
     ("task queue dashboard", "background job progress", "server logs")),
    (("log", "лог", "terminal", "терминал", "console", "консол"),
     ("terminal logs", "build output", "developer console")),
    (("code", "код", "source", "исходник", "github", "git", "commit", "коммит"),
     ("source code editor", "github repository", "git commits")),
    (("site", "сайт", "website", "web", "landing", "страниц"),
     ("website interface", "product website", "web app screen")),
    (("game", "игр", "unity", "godot", "pixel", "jam"),
     ("indie game footage", "game development", "gameplay capture")),
    (("reddit", "реддит"),
     ("reddit post", "online community discussion", "social media comments")),
    (("youtube", "ютуб", "shorts", "reel", "рилс"),
     ("youtube channel", "video analytics", "creator dashboard")),
    (("audio", "voice", "озвуч", "голос", "record", "запис"),
     ("voice recording waveform", "audio editor", "microphone setup")),
    (("asset", "ассет", "b-roll", "visual", "визуал"),
     ("video assets library", "b-roll footage", "media browser")),
)

REAL_FOOTAGE_HINTS = (
    "site", "сайт", "website", "product", "продукт", "game", "игр",
    "github", "code", "код", "reddit", "youtube", "studio", "ui",
)


@dataclass(frozen=True)
class BrollSuggestion:
    beat_id: str
    beat_title: str
    chunk_index: int
    words: str
    chunk_kind: str
    current_visual: str
    visual_gap: bool
    priority: str
    visual_idea: str
    search_terms: list[str]
    local_candidates: list[str]
    avoid: str

    def to_dict(self) -> dict:
        return asdict(self)


def _scene_desc(chunk, beat) -> str:
    if chunk.kind in {"image", "video"} and chunk.src:
        return f"{chunk.kind}:{chunk.src}"
    scene = chunk.scene or beat.scene
    if scene:
        return f"{scene.kind}:{scene.src}"
    return "solid"


def _chunk_text(chunk, beat) -> str:
    text = chunk.text or chunk.subtitle or chunk.label or ""
    return " ".join(part for part in (beat.title, beat.vo, text) if part)


def _tokens(value: str) -> set[str]:
    return {
        token.lower()
        for token in re.findall(r"[A-Za-zА-Яа-яЁё0-9]+", value)
        if len(token) >= 3
    }


def _search_terms(text: str) -> list[str]:
    lowered = text.lower()
    terms: list[str] = []
    for needles, mapped_terms in KEYWORD_TERMS:
        if any(needle in lowered for needle in needles):
            for term in mapped_terms:
                if term not in terms:
                    terms.append(term)
    if not terms:
        terms.extend(("software product demo", "developer workflow", "screen recording"))
    return terms[:5]


def _needs_real_footage(text: str) -> bool:
    lowered = text.lower()
    return any(hint in lowered for hint in REAL_FOOTAGE_HINTS)


def _visual_idea(text: str, terms: list[str], *, needs_real: bool) -> str:
    if needs_real:
        return f"Use real captured product/dev footage if available; search fallback: {terms[0]}."
    return f"Use short contextual B-roll around: {terms[0]}."


def _iter_visual_files(root: Path) -> list[Path]:
    data = root / "data"
    if not data.exists():
        return []
    out: list[Path] = []
    for path in data.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in VISUAL_SUFFIXES:
            continue
        rel = path.relative_to(root).as_posix()
        if (
            "/.cache/" in rel
            or rel.endswith("_ffmpeg_error.txt")
            or any(rel.startswith(prefix) for prefix in GENERATED_DATA_PREFIXES)
        ):
            continue
        out.append(path)
    return out


def _local_candidates(root: Path, text: str, terms: list[str], *, limit: int = 5) -> list[str]:
    wanted = _tokens(text)
    for term in terms:
        wanted.update(_tokens(term))
    scored: list[tuple[int, str]] = []
    for path in _iter_visual_files(root):
        rel = path.relative_to(root).as_posix()
        haystack = " ".join(_tokens(path.stem) | _tokens(rel))
        score = 0
        for token in wanted:
            if token in haystack:
                score += 2 if len(token) >= 5 else 1
        if score:
            scored.append((score, rel))
    scored.sort(key=lambda item: (-item[0], item[1]))
    return [rel for _, rel in scored[:limit]]


def _priority(chunk, visual_gap: bool, needs_real: bool) -> str:
    if not visual_gap:
        return "low"
    if chunk.kind == "overlay" or needs_real:
        return "high"
    return "medium"


def suggest_broll(edit: Edit, root: Path) -> list[BrollSuggestion]:
    suggestions: list[BrollSuggestion] = []
    for beat_id in edit.order:
        beat = edit.beats[beat_id]
        title = beat.title or beat_id
        for idx, chunk in enumerate(beat.chunks):
            current = _scene_desc(chunk, beat)
            visual_gap = current == "solid"
            text = _chunk_text(chunk, beat)
            terms = _search_terms(text)
            needs_real = _needs_real_footage(text)
            suggestions.append(BrollSuggestion(
                beat_id=beat_id,
                beat_title=title,
                chunk_index=idx,
                words=f"{chunk.words[0]}-{chunk.words[1]}",
                chunk_kind=chunk.kind,
                current_visual=current,
                visual_gap=visual_gap,
                priority=_priority(chunk, visual_gap, needs_real),
                visual_idea=_visual_idea(text, terms, needs_real=needs_real),
                search_terms=terms,
                local_candidates=_local_candidates(root, text, terms),
                avoid=(
                    "generic stock; prefer real product/dev capture"
                    if needs_real else "long generic stock shots"
                ),
            ))
    return suggestions


def suggestions_to_json(suggestions: list[BrollSuggestion]) -> list[dict]:
    return [item.to_dict() for item in suggestions]


def suggestions_markdown(suggestions: list[BrollSuggestion]) -> str:
    lines = ["# B-roll suggestions", ""]
    current_beat = None
    for item in suggestions:
        if item.beat_id != current_beat:
            current_beat = item.beat_id
            lines.extend([f"## {item.beat_id} - {item.beat_title}", ""])
        gap = "gap" if item.visual_gap else "covered"
        lines.append(
            f"- c{item.chunk_index} words {item.words} - {item.priority} - "
            f"{gap} - {item.current_visual}"
        )
        lines.append(f"  idea: {item.visual_idea}")
        lines.append(f"  search: {', '.join(item.search_terms)}")
        if item.local_candidates:
            lines.append(f"  local: {', '.join(item.local_candidates)}")
        lines.append(f"  avoid: {item.avoid}")
    return "\n".join(lines).rstrip() + "\n"
