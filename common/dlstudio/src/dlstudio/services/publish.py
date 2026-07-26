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

Two YouTube-side chapter rules ARE enforced here (not left to the human to
discover after upload): YouTube silently disables the whole chapters
feature -- no error, no chapters shown -- when there are fewer than 3
timestamps, or when any two adjacent timestamps are less than 10s apart.
Both are objective and mechanical (not judgment calls), so `_chapter_warnings`
checks them at generation time and `_render_markdown` surfaces a visible
`> WARNING (chapters): ...` block plus a checklist line when either is
violated. The first chapter being at 0:00 is always true by construction
(the IR's first `BeatPlacement.t0` is always 0.0), so that rule needs no
runtime check. Everything else (title/description/tag quality, thumbnail,
character limits) remains outside this module's job -- the upload checklist
section names the VQ rules a human/agent still has to apply before hitting
publish.
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

# YouTube's own chapter feature silently disables itself (no error, no
# chapters shown at all) when either rule below is violated -- see
# _chapter_warnings.
_MIN_CHAPTER_COUNT = 3
_MIN_CHAPTER_GAP_SECONDS = 10.0


def _format_timestamp(seconds: float) -> str:
    """`seconds` -> "mm:ss", or "h:mm:ss" once the timestamp crosses one
    hour (total >= 3600s) -- YouTube chapter timestamps past the hour mark
    need the explicit hour component (a bare "65:00" is valid but "1:05:00"
    is the conventional/unambiguous form once hours are in play). Floored to
    whole seconds (YouTube chapter timestamps are whole-second; sub-second
    precision would just be truncated by YouTube anyway). Negative/garbage
    input clamps to 0."""
    total = max(0, int(seconds))
    hours, remainder = divmod(total, 3600)
    minutes, secs = divmod(remainder, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes:02d}:{secs:02d}"


def _chapter_lines(edit: Edit, timeline: Timeline) -> list[str]:
    lines = []
    for placement in timeline.placements:
        beat = edit.beats.get(placement.beat_id)
        title = beat.title if beat is not None and beat.title else placement.beat_id
        lines.append(f"{_format_timestamp(placement.t0)} {title}")
    return lines


def _chapter_warnings(timeline: Timeline) -> list[str]:
    """Check the two YouTube chapter rules that are objective/mechanical
    (not judgment calls): at least `_MIN_CHAPTER_COUNT` chapters, and no two
    adjacent chapters closer together than `_MIN_CHAPTER_GAP_SECONDS` --
    YouTube silently drops the ENTIRE chapters feature (no chapters shown at
    all, no error) if either is violated, so this is worth catching before
    upload rather than after. Returns human-readable warning strings, one
    per violation; empty when the timeline's chapters are valid.

    (The "first chapter must be at 0:00" rule is not checked here -- it's
    always true by construction: the IR's first `BeatPlacement.t0` is
    always 0.0.)
    """
    placements = timeline.placements
    warnings: list[str] = []

    if len(placements) < _MIN_CHAPTER_COUNT:
        warnings.append(
            f"only {len(placements)} chapter(s) -- YouTube requires at least "
            f"{_MIN_CHAPTER_COUNT} timestamps for chapters to appear at all."
        )

    for prev, curr in zip(placements, placements[1:]):
        gap = curr.t0 - prev.t0
        if gap < _MIN_CHAPTER_GAP_SECONDS:
            warnings.append(
                f"{prev.beat_id!r} -> {curr.beat_id!r} are only {gap:.1f}s apart -- "
                f"YouTube requires at least {_MIN_CHAPTER_GAP_SECONDS:.0f}s between "
                f"adjacent chapter timestamps."
            )

    return warnings


def _render_markdown(
    edit: Edit,
    *,
    title_variants: list[str] | None,
    thumbnail_variants: list[str] | None,
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

    lines.append("## A/B test plan")
    if thumbnail_variants:
        lines.extend(
            f"{i}. `{thumbnail}`"
            for i, thumbnail in enumerate(thumbnail_variants, start=1)
        )
    else:
        lines.append("_no thumbnail variants supplied_")
    lines.append("")
    lines.append(
        "Pair each thumbnail with a meaningfully different title hypothesis. "
        "Use YouTube's native A/B test for long-form and choose by watch time, "
        "not click-through rate alone."
    )
    lines.append("")

    lines.append("## Description")
    lines.append(description if description else "_no description supplied_")
    lines.append("")

    lines.append("## Tags")
    lines.append(", ".join(tags) if tags else "_no tags supplied_")
    lines.append("")

    lines.append("## Chapters")
    chapter_warnings: list[str] = []
    if chapters_from_timeline is not None:
        chapter_lines = _chapter_lines(edit, chapters_from_timeline)
        lines.extend(chapter_lines if chapter_lines else ["_timeline has no beats_"])
        chapter_warnings = _chapter_warnings(chapters_from_timeline)
        if chapter_warnings:
            lines.append("")
            for warning in chapter_warnings:
                lines.append(f"> WARNING (chapters): {warning}")
    else:
        lines.append("_no timeline supplied -- chapters unavailable_")
    lines.append("")

    lines.append("## Upload checklist")
    lines.extend(f"- [ ] {code}: {desc}" for code, desc in _CHECKLIST_RULES)
    if chapters_from_timeline is None:
        lines.append("- [ ] Chapters valid: unverified -- no timeline supplied")
    elif chapter_warnings:
        lines.append(
            f"- [ ] Chapters valid: NO -- {len(chapter_warnings)} issue(s), see WARNING block above"
        )
    else:
        lines.append(
            f"- [ ] Chapters valid: yes -- >= {_MIN_CHAPTER_COUNT} chapters, "
            f"no adjacent gap under {_MIN_CHAPTER_GAP_SECONDS:.0f}s"
        )
    lines.append("")

    return "\n".join(lines) + "\n"


def generate_youtube_package(
    edit: Edit,
    *,
    out_path: Path | str,
    title_variants: list[str] | None = None,
    thumbnail_variants: list[str] | None = None,
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
        thumbnail_variants=thumbnail_variants,
        description=description,
        tags=tags,
        chapters_from_timeline=chapters_from_timeline,
    )
    out_path.write_text(text, encoding="utf-8")
    return out_path
