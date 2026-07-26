"""Deterministic audience-copy and standalone-story gates.

The gate runs before storyboard rendering.  It intentionally checks only
facts that can be proven mechanically: a complete story contract exists and
viewer-visible HyperFrames text does not contain internal production labels.
"""
from __future__ import annotations

import json
import re
from html.parser import HTMLParser
from pathlib import Path
from typing import Any, Iterable

from dlstudio.ir import CheckIssue, CheckReport


_EDITORIAL_LABEL = re.compile(
    r"\b(?:REEL|PART|VERSION|CUT|РИЛС|ЧАСТЬ|ВЕРСИЯ)\s*(?:#|№)?\s*\d+\b",
    re.IGNORECASE,
)
_FALSE_STEAM_CLAIM = re.compile(
    r"(?:next\s+stop|следующая\s+остановка)\s*(?:—|-|:)?\s*steam",
    re.IGNORECASE,
)
_STORY_FIELDS = ("premise", "causal_turn", "payoff")


class _VisibleTextParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_body = False
        self._hidden_depth = 0
        self.parts: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        name = tag.casefold()
        if name == "body":
            self._in_body = True
        elif self._in_body and name in {"script", "style", "template"}:
            self._hidden_depth += 1

    def handle_endtag(self, tag: str) -> None:
        name = tag.casefold()
        if name == "body":
            self._in_body = False
        elif self._in_body and name in {"script", "style", "template"}:
            self._hidden_depth = max(0, self._hidden_depth - 1)

    def handle_data(self, data: str) -> None:
        if self._in_body and not self._hidden_depth and data.strip():
            self.parts.append(data.strip())


def _visible_html_text(path: Path) -> str:
    parser = _VisibleTextParser()
    parser.feed(path.read_text(encoding="utf-8"))
    return " ".join(parser.parts)


def visible_html_text(path: str | Path) -> str:
    return _visible_html_text(Path(path))


def viewer_html_paths(root: str | Path) -> tuple[Path, ...]:
    """Resolve only HyperFrames sources used by the shot manifest."""
    base = Path(root).resolve()
    manifest_path = base / "data" / "plan" / "shot_manifest.json"
    try:
        payload = json.loads(manifest_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return ()
    shots = payload.get("shots") if isinstance(payload, dict) else None
    if not isinstance(shots, list):
        return ()
    paths: set[Path] = set()
    for shot in shots:
        if not isinstance(shot, dict):
            continue
        src = Path(str(shot.get("src") or "").replace("\\", "/"))
        parts = tuple(part.casefold() for part in src.parts)
        if "infographics" in parts and src.stem:
            paths.add(base / "data" / "hyperframes" / src.stem / "index.html")
        elif "hyperframes" in parts:
            index = parts.index("hyperframes")
            if len(src.parts) > index + 1:
                paths.add(base / "data" / "hyperframes" / src.parts[index + 1] / "index.html")
    return tuple(sorted(path for path in paths if path.is_file()))


def _allowed_editorial_labels(root: Path) -> set[str]:
    contract_path = root / "data" / "plan" / "story_contract.json"
    try:
        payload = json.loads(contract_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError, OSError):
        return set()
    values = payload.get("allow_editorial_labels") if isinstance(payload, dict) else None
    if not isinstance(values, list):
        return set()
    return {
        value.strip().casefold()
        for value in values
        if isinstance(value, str) and value.strip()
    }


def public_copy_issues(
    root: str | Path,
    texts: Iterable[tuple[str, str]],
) -> list[CheckIssue]:
    """Check exact viewer-visible strings, independent of visual inspection."""
    base = Path(root).resolve()
    allow = _allowed_editorial_labels(base)
    issues: list[CheckIssue] = []
    for where, text in texts:
        for match in _EDITORIAL_LABEL.finditer(text):
            label = match.group(0).strip()
            if label.casefold() in allow:
                continue
            issues.append(CheckIssue(
                severity="error",
                code="VQ-EDITORIAL-LABEL",
                message=f"internal production label is viewer-visible: {label!r}",
                where=where,
            ))
        if _FALSE_STEAM_CLAIM.search(text):
            issues.append(CheckIssue(
                severity="error",
                code="VQ-PUBLIC-CLAIM",
                message=(
                    "viewer-visible copy says Steam is a future stop; "
                    "use the canonical wishlist CTA"
                ),
                where=where,
            ))
    return issues


def run_editorial_preflight(
    root: str | Path,
    *,
    require_story_contract: bool,
) -> CheckReport:
    base = Path(root).resolve()
    issues: list[CheckIssue] = []
    contract_path = base / "data" / "plan" / "story_contract.json"
    contract: dict[str, Any] = {}

    if contract_path.is_file():
        try:
            payload = json.loads(contract_path.read_text(encoding="utf-8"))
            if not isinstance(payload, dict):
                raise ValueError("root must be a JSON object")
            contract = payload
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            issues.append(CheckIssue(
                severity="error", code="VQ-STANDALONE",
                message=f"invalid story contract: {exc}",
                where="data/plan/story_contract.json",
            ))
    elif require_story_contract:
        issues.append(CheckIssue(
            severity="error", code="VQ-STANDALONE",
            message="vertical production requires data/plan/story_contract.json",
            where="data/plan/story_contract.json",
        ))

    if require_story_contract and contract:
        story = contract.get("standalone_story")
        if not isinstance(story, dict):
            story = {}
        missing = [
            field for field in _STORY_FIELDS
            if not isinstance(story.get(field), str) or not story[field].strip()
        ]
        if missing:
            issues.append(CheckIssue(
                severity="error", code="VQ-STANDALONE",
                message=f"standalone story is incomplete: {', '.join(missing)}",
                where="data/plan/story_contract.json",
            ))

    for html_path in viewer_html_paths(base):
        try:
            visible = _visible_html_text(html_path)
        except (OSError, UnicodeError) as exc:
            issues.append(CheckIssue(
                severity="error", code="VQ-EDITORIAL-LABEL",
                message=f"cannot inspect viewer-visible HTML text: {exc}",
                where=html_path.relative_to(base).as_posix(),
            ))
            continue
        issues.extend(public_copy_issues(
            base,
            [(html_path.relative_to(base).as_posix(), visible)],
        ))

    return CheckReport(issues=issues)


__all__ = [
    "public_copy_issues",
    "run_editorial_preflight",
    "viewer_html_paths",
    "visible_html_text",
]
