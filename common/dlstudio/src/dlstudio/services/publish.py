"""publish: YouTube upload package generation (title/description/tags/chapters).

Ports the shape of the hand-written legacy packages (see e.g.
neotolis_diary/data/publish/youtube_package.md) into a generated artifact:
`generate_youtube_package()` writes a single markdown file an author (or the
publish-packager agent) fills in / trims before upload.

Chapters are derived from two sources on purpose, not one:
  - `chapters_from_timeline` (a compiled `Timeline`) supplies the absolute
    placement (`BeatPlacement.t0`) of every beat on the edit's timeline --
    the IR is the only place that knows real, post-compile timing.
  - `edit.beats[beat_id].title` supplies the human chapter label. Titles
    live on the model `Beat`, not the IR `IRBeat` (the IR carries no
    display text at all), so both `edit` and `chapters_from_timeline` are
    needed together; a beat with no `title` falls back to its id.

No YouTube-side validation (minimum chapter count/spacing, character
limits, etc.) is enforced here -- this module only assembles the package;
the upload checklist section names the VQ rules a human/agent still has to
apply before hitting publish.
"""
from __future__ import annotations

from pathlib import Path

from dlstudio.ir import Timeline
from dlstudio.model import Edit

# Only these four VQ rules apply at the publish/upload stage per
# common/quality/README.md's "by ship stage" table ("Ship / final / upload
# render" hard-gates all ten, but the four below are the ones specifically
# about the shipped artifact itself rather than mid-production judgment
# calls) -- the checklist must reference these ids and no others.
_CHECKLIST_RULES: tuple[tuple[str, str], ...] = (
    ("VQ-SYNC", "audio/video duration match -- `dl2 check` is clean, no drift between VO and picture."),
    ("VQ-AUDIO", "final mix hits the -14 LUFS / -1 dBTP targets and ducking reads clean under VO."),
    ("VQ-END", "the video has a deliberate ending -- no abrupt cut, no dead air after the last beat."),
    ("VQ-PROOF", "any shot claiming to be the real product/site/game is actually real, no stand-ins."),
)


def _format_timestamp(seconds: float) -> str:
    """`seconds` -> "mm:ss", floored to whole seconds (YouTube chapter
    timestamps are whole-second; sub-second precision would just be
    truncated by YouTube anyway). Negative/garbage input clamps to 0."""
    total = max(0, int(seconds))
    return f"{total // 60:02d}:{total % 60:02d}"


def _chapter_lines(edit: Edit, timeline: Timeline) -> list[str]:
    lines = []
    for placement in timeline.placements:
        beat = edit.beats.get(placement.beat_id)
        title = beat.title if beat is not None and beat.title else placement.beat_id
        lines.append(f"{_format_timestamp(placement.t0)} {title}")
    return lines


def _render_markdown(
    edit: Edit,
    *,
    title_variants: list[str] | None,
    description: str | None,
    tags: list[str] | None,
    chapters_from_timeline: Timeline | None,
) -> str:
    lines: list[str] = [f"# YouTube package: {edit.name}", ""]

    lines.append("## Title variants")
    if title_variants:
        lines.extend(f"{i}. {title}" for i, title in enumerate(title_variants, start=1))
    else:
        lines.append("_no title variants supplied_")
    lines.append("")

    lines.append("## Description")
    lines.append(description if description else "_no description supplied_")
    lines.append("")

    lines.append("## Tags")
    lines.append(", ".join(tags) if tags else "_no tags supplied_")
    lines.append("")

    lines.append("## Chapters")
    if chapters_from_timeline is not None:
        chapter_lines = _chapter_lines(edit, chapters_from_timeline)
        lines.extend(chapter_lines if chapter_lines else ["_timeline has no beats_"])
    else:
        lines.append("_no timeline supplied -- chapters unavailable_")
    lines.append("")

    lines.append("## Upload checklist")
    lines.extend(f"- [ ] {code}: {desc}" for code, desc in _CHECKLIST_RULES)
    lines.append("")

    return "\n".join(lines) + "\n"


def generate_youtube_package(
    edit: Edit,
    *,
    out_path: Path | str,
    title_variants: list[str] | None = None,
    description: str | None = None,
    tags: list[str] | None = None,
    chapters_from_timeline: Timeline | None = None,
) -> Path:
    """Write a youtube_package.md for `edit` to `out_path` (parent dirs
    created as needed) and return the resolved Path.

    All keyword args are optional -- omitting any of them writes an explicit
    "not supplied" placeholder in that section rather than leaving it out,
    so the generated file always has the same section shape whether it's
    hand-finished later or fully populated by the caller up front.
    """
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    text = _render_markdown(
        edit,
        title_variants=title_variants,
        description=description,
        tags=tags,
        chapters_from_timeline=chapters_from_timeline,
    )
    out_path.write_text(text, encoding="utf-8")
    return out_path
