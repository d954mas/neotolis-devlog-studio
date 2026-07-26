"""Tests for dlstudio.services.publish -- youtube_package.md generation.

Chapters need two things together: a Timeline (for BeatPlacement.t0 -- real
compiled placement seconds) and the source Edit (for Beat.title -- the IR
carries no display text). The fixture below builds both by hand, matching
`_builders.py`/`conftest.py`'s make_design/make_ir_beat/make_timeline style
used elsewhere in this suite, plus a matching model.Edit for the titles.
"""
from __future__ import annotations

from dlstudio.model import Beat, Chunk, Design, Edit, Fonts, Palette, Plate
from dlstudio.services import publish

from conftest import make_design, make_ir_beat, make_timeline


def _make_edit_and_timeline():
    # Beats are >= 10s apart (b01 dur 10.0, b02 dur 130.0) so this fixture
    # is a "valid chapters" case -- no adjacent-gap warning. See F3/F5:
    # a 5s gap used to sit here uncaught; that's now exactly what
    # _chapter_warnings flags, so the "no warnings" fixture must clear the
    # 10s floor on purpose.
    design = make_design(1920, 1080)
    beats_ir = [
        make_ir_beat("b01", duration=10.0),
        make_ir_beat("b02", duration=130.0),
        make_ir_beat("b03", duration=65.0),
    ]
    timeline = make_timeline(beats_ir, design=design, name="fixture-edit")

    edit = Edit(
        name="fixture-edit",
        design=design,
        beats={
            "b01": Beat(audio="a.wav", words="a.json", title="Hook",
                        chunks=[Chunk(words=(0, 1), content=Plate(text="X"))]),
            "b02": Beat(audio="b.wav", words="b.json", title="The Build",
                        chunks=[Chunk(words=(0, 1), content=Plate(text="Y"))]),
            "b03": Beat(audio="c.wav", words="c.json", title=None,
                        chunks=[Chunk(words=(0, 1), content=Plate(text="Z"))]),
        },
        order=["b01", "b02", "b03"],
        output="data/finalize/output.mp4",
    )
    return edit, timeline


# ─── timestamp formatting ───────────────────────────────────────────────

def test_format_timestamp_basic():
    assert publish._format_timestamp(0) == "00:00"
    assert publish._format_timestamp(5) == "00:05"
    assert publish._format_timestamp(65) == "01:05"
    assert publish._format_timestamp(135) == "02:15"


def test_format_timestamp_floors_fractional_seconds():
    assert publish._format_timestamp(125.9) == "02:05"


def test_format_timestamp_clamps_negative_to_zero():
    assert publish._format_timestamp(-3) == "00:00"


def test_format_timestamp_switches_to_hmmss_past_one_hour():
    # 61 minutes 5 seconds = 3665s -> "1:01:05" (F3: below 3600s stays mm:ss)
    assert publish._format_timestamp(3665) == "1:01:05"
    assert publish._format_timestamp(3600) == "1:00:00"
    assert publish._format_timestamp(3599) == "59:59"


# ─── chapters math ──────────────────────────────────────────────────────

def test_chapter_lines_use_placements_and_titles():
    edit, timeline = _make_edit_and_timeline()
    lines = publish._chapter_lines(edit, timeline)
    # b01@0s (dur 10) -> b02@10s (dur 130) -> b03@140s (dur 65)
    assert lines == [
        "00:00 Hook",
        "00:10 The Build",
        "02:20 b03",  # no title on b03 -> falls back to beat id
    ]


# ─── generate_youtube_package: content assertions ──────────────────────

def test_generate_package_writes_all_sections(tmp_path):
    edit, timeline = _make_edit_and_timeline()
    out_path = tmp_path / "youtube_package.md"

    result = publish.generate_youtube_package(
        edit,
        out_path=out_path,
        title_variants=["Title A", "Title B", "Title C"],
        thumbnail_variants=[
            "thumbnail_curiosity.png",
            "thumbnail_number.png",
            "thumbnail_outcome.png",
        ],
        description="A short description of the video.",
        tags=["devlog", "gamedev", "python"],
        chapters_from_timeline=timeline,
    )

    assert result == out_path
    text = out_path.read_text(encoding="utf-8")

    assert "# YouTube package: fixture-edit" in text
    assert "## Title variants" in text
    assert "1. Title A" in text
    assert "2. Title B" in text
    assert "3. Title C" in text
    assert "## A/B test plan" in text
    assert "thumbnail_curiosity.png" in text
    assert "thumbnail_number.png" in text
    assert "thumbnail_outcome.png" in text
    assert "watch time" in text
    assert "## Description" in text
    assert "A short description of the video." in text
    assert "## Tags" in text
    assert "devlog, gamedev, python" in text
    assert "## Chapters" in text
    assert "00:00 Hook" in text
    assert "00:10 The Build" in text
    assert "02:20 b03" in text
    # beats are >= 10s apart and there are 3 of them -- no chapter warning
    assert "WARNING" not in text
    assert "## Upload checklist" in text
    assert "VQ-SYNC" in text
    assert "VQ-AUDIO" in text
    assert "VQ-END" in text
    assert "VQ-PROOF" in text
    assert "Chapters valid: yes" in text
    # only these four VQ ids belong in the publish checklist
    assert "VQ-HOOK" not in text
    assert "VQ-SAFE" not in text
    assert "VQ-MOTION" not in text
    assert "VQ-ASSET" not in text
    assert "VQ-RES" not in text
    assert "VQ-WORDS" not in text


def test_generate_package_creates_parent_dirs(tmp_path):
    edit, timeline = _make_edit_and_timeline()
    out_path = tmp_path / "nested" / "dir" / "youtube_package.md"
    publish.generate_youtube_package(edit, out_path=out_path, chapters_from_timeline=timeline)
    assert out_path.exists()


def test_generate_package_without_optional_args_has_placeholders(tmp_path):
    edit, timeline = _make_edit_and_timeline()
    out_path = tmp_path / "youtube_package.md"
    publish.generate_youtube_package(edit, out_path=out_path)
    text = out_path.read_text(encoding="utf-8")

    assert "_no title variants supplied_" in text
    assert "_no thumbnail variants supplied_" in text
    assert "_no description supplied_" in text
    assert "_no tags supplied_" in text
    assert "_no timeline supplied" in text
    # checklist is always present regardless of what else was supplied
    assert "VQ-SYNC" in text
    # can't validate chapters without a timeline -- unverified, not a silent pass
    assert "Chapters valid: unverified" in text


def test_generate_package_empty_timeline_reports_no_beats(tmp_path):
    edit, _timeline = _make_edit_and_timeline()
    empty_timeline = make_timeline([], design=make_design())
    out_path = tmp_path / "youtube_package.md"
    publish.generate_youtube_package(edit, out_path=out_path, chapters_from_timeline=empty_timeline)
    text = out_path.read_text(encoding="utf-8")
    assert "_timeline has no beats_" in text


# ─── F3/F5: YouTube chapter validity (min count, min adjacent gap) ─────

def _make_edit_and_timeline_short_gap():
    """Two adjacent beats only 5s apart -- exercises the <10s-gap warning
    in isolation (3 beats total, so the chapter-count rule stays satisfied)."""
    design = make_design(1920, 1080)
    beats_ir = [
        make_ir_beat("b01", duration=5.0),
        make_ir_beat("b02", duration=20.0),
        make_ir_beat("b03", duration=20.0),
    ]
    timeline = make_timeline(beats_ir, design=design, name="short-gap-edit")
    edit = Edit(
        name="short-gap-edit",
        design=design,
        beats={
            "b01": Beat(audio="a.wav", words="a.json", title="Hook",
                        chunks=[Chunk(words=(0, 1), content=Plate(text="X"))]),
            "b02": Beat(audio="b.wav", words="b.json", title="Build",
                        chunks=[Chunk(words=(0, 1), content=Plate(text="Y"))]),
            "b03": Beat(audio="c.wav", words="c.json", title="End",
                        chunks=[Chunk(words=(0, 1), content=Plate(text="Z"))]),
        },
        order=["b01", "b02", "b03"],
        output="data/finalize/output.mp4",
    )
    return edit, timeline


def _make_edit_and_timeline_two_chapters():
    """Only 2 beats, each >= 10s apart -- exercises the <3-chapters warning
    in isolation (the gap rule stays satisfied)."""
    design = make_design(1920, 1080)
    beats_ir = [
        make_ir_beat("b01", duration=15.0),
        make_ir_beat("b02", duration=15.0),
    ]
    timeline = make_timeline(beats_ir, design=design, name="two-chapter-edit")
    edit = Edit(
        name="two-chapter-edit",
        design=design,
        beats={
            "b01": Beat(audio="a.wav", words="a.json", title="Hook",
                        chunks=[Chunk(words=(0, 1), content=Plate(text="X"))]),
            "b02": Beat(audio="b.wav", words="b.json", title="Outro",
                        chunks=[Chunk(words=(0, 1), content=Plate(text="Y"))]),
        },
        order=["b01", "b02"],
        output="data/finalize/output.mp4",
    )
    return edit, timeline


def test_chapter_warnings_empty_for_valid_timeline():
    _edit, timeline = _make_edit_and_timeline()
    assert publish._chapter_warnings(timeline) == []


def test_chapter_warnings_flags_short_adjacent_gap():
    _edit, timeline = _make_edit_and_timeline_short_gap()
    warnings = publish._chapter_warnings(timeline)
    assert len(warnings) == 1
    assert "5.0s apart" in warnings[0]
    assert "b01" in warnings[0] and "b02" in warnings[0]


def test_chapter_warnings_flags_fewer_than_three_chapters():
    _edit, timeline = _make_edit_and_timeline_two_chapters()
    warnings = publish._chapter_warnings(timeline)
    assert len(warnings) == 1
    assert "only 2 chapter" in warnings[0]


def test_generate_package_warns_on_short_chapter_gap(tmp_path):
    edit, timeline = _make_edit_and_timeline_short_gap()
    out_path = tmp_path / "youtube_package.md"
    publish.generate_youtube_package(edit, out_path=out_path, chapters_from_timeline=timeline)
    text = out_path.read_text(encoding="utf-8")

    assert "> WARNING (chapters):" in text
    assert "5.0s apart" in text
    assert "Chapters valid: NO" in text


def test_generate_package_warns_on_fewer_than_three_chapters(tmp_path):
    edit, timeline = _make_edit_and_timeline_two_chapters()
    out_path = tmp_path / "youtube_package.md"
    publish.generate_youtube_package(edit, out_path=out_path, chapters_from_timeline=timeline)
    text = out_path.read_text(encoding="utf-8")

    assert "> WARNING (chapters):" in text
    assert "only 2 chapter" in text
    assert "Chapters valid: NO" in text
