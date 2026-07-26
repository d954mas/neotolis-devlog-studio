"""Deterministic glyph and frame preflight gates (no AI runtime)."""
from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import pytest
from PIL import Image, ImageDraw

from dlstudio.model import (
    Beat,
    Chunk,
    Design,
    Edit,
    Fonts,
    Overlay,
    Palette,
    Plate,
)


def _design(font: str) -> Design:
    return Design(
        resolution=(1080, 1920),
        palette=Palette(tokens={"bg": "#111111", "text": "#ffffff"}),
        fonts=Fonts(main=font),
    )


def _edit(design: Design, *chunks: Chunk) -> Edit:
    return Edit(
        name="visual-preflight",
        design=design,
        beats={
            "b01": Beat(
                audio="voice.wav",
                words="words.json",
                chunks=list(chunks),
            )
        },
        order=["b01"],
        output="draft.mp4",
    )


def test_glyph_check_blocks_a_real_missing_overlay_glyph(tmp_path):
    from _builders import find_system_font
    from dlstudio.services.visual_preflight import check_glyph_coverage

    font = find_system_font()
    if font is None:
        pytest.skip("no known system font")
    edit = _edit(
        _design(font),
        Chunk(words=(0, 0), content=Overlay(text="status \U0001fae0")),
    )
    timeline = SimpleNamespace(beats=[])

    issues = check_glyph_coverage(edit, timeline, tmp_path)

    assert len(issues) == 1
    assert issues[0].code == "VQ-GLYPH"
    assert issues[0].severity == "error"
    assert "U+1FAE0" in issues[0].message
    assert issues[0].where == "b01:0"


def test_glyph_check_warns_unknown_when_production_font_is_unavailable(tmp_path):
    from dlstudio.services.visual_preflight import check_glyph_coverage

    edit = _edit(
        _design("data/fonts/missing.ttf"),
        Chunk(words=(0, 0), content=Plate(text="This must not silently pass")),
    )

    issues = check_glyph_coverage(edit, SimpleNamespace(beats=[]), tmp_path)

    assert len(issues) == 1
    assert issues[0].code == "VQ-GLYPH"
    assert issues[0].severity == "warn"
    assert "unknown" in issues[0].message.casefold()
    assert "missing.ttf" in issues[0].message


def test_glyph_check_covers_compiled_caption_text(tmp_path):
    from _builders import find_system_font
    from dlstudio.services.visual_preflight import check_glyph_coverage

    font = find_system_font()
    if font is None:
        pytest.skip("no known system font")
    edit = _edit(_design(font))
    timeline = SimpleNamespace(
        beats=[
            SimpleNamespace(
                id="b01",
                captions=[SimpleNamespace(text="caption \U0001fae0")],
            )
        ]
    )

    issues = check_glyph_coverage(edit, timeline, tmp_path)

    assert [(issue.code, issue.severity, issue.where) for issue in issues] == [
        ("VQ-GLYPH", "error", "b01:caption"),
    ]


def _healthy_frame(path: Path) -> None:
    image = Image.new("RGB", (240, 180), "#1d3658")
    draw = ImageDraw.Draw(image)
    for x in range(0, 240, 12):
        draw.rectangle((x, 0, x + 6, 179), fill=(80 + x // 3, 60, 130))
    image.save(path)


def _empty_bottom_frame(path: Path) -> None:
    image = Image.new("RGB", (240, 180), "black")
    draw = ImageDraw.Draw(image)
    draw.rectangle((0, 0, 239, 105), fill="#496da8")
    for x in range(0, 240, 16):
        draw.line((x, 0, 239 - x, 105), fill="#f4c95d", width=3)
    image.save(path)


def test_frame_check_warns_for_gross_empty_area_in_draft(tmp_path):
    from dlstudio.services.visual_preflight import check_frame_occupancy

    source = tmp_path / "data" / "images" / "montage.png"
    source.parent.mkdir(parents=True)
    _empty_bottom_frame(source)
    shots = [{"id": "s01", "src": "data/images/montage.png", "intent": "montage"}]

    issues = check_frame_occupancy(tmp_path, shots=shots, final=False)

    assert len(issues) == 1
    assert issues[0].code == "VQ-FRAME"
    assert issues[0].severity == "warn"
    assert issues[0].where == "s01"
    assert "empty" in issues[0].message.casefold()


def test_frame_check_blocks_generated_montage_with_gross_empty_area_in_final(tmp_path):
    from dlstudio.services.visual_preflight import check_frame_occupancy

    source = tmp_path / "data" / "infographics" / "montage.png"
    source.parent.mkdir(parents=True)
    _empty_bottom_frame(source)
    shots = [
        {
            "id": "s01",
            "src": "data/infographics/montage.png",
            "intent": "montage",
            "source_role": "generated",
        }
    ]

    issues = check_frame_occupancy(tmp_path, shots=shots, final=True)

    assert len(issues) == 1
    assert issues[0].code == "VQ-FRAME"
    assert issues[0].severity == "error"


def test_frame_check_accepts_a_full_occupancy_image(tmp_path):
    from dlstudio.services.visual_preflight import check_frame_occupancy

    source = tmp_path / "data" / "images" / "healthy.png"
    source.parent.mkdir(parents=True)
    _healthy_frame(source)

    issues = check_frame_occupancy(
        tmp_path,
        shots=[{"id": "s01", "src": "data/images/healthy.png"}],
        final=True,
    )

    assert issues == []


def test_frame_check_uses_deterministic_video_sample_frames(tmp_path, monkeypatch):
    from dlstudio.services import visual_preflight

    source = tmp_path / "data" / "infographics" / "montage.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"fixture boundary; decoder is replaced")
    sample = tmp_path / "sample.png"
    _empty_bottom_frame(sample)
    image = Image.open(sample).copy()
    monkeypatch.setattr(
        visual_preflight,
        "_sample_video_frames",
        lambda path, duration: ([image, image, image], None),
    )

    issues = visual_preflight.check_frame_occupancy(
        tmp_path,
        shots=[
            {
                "id": "s01",
                "src": "data/infographics/montage.mp4",
                "intent": "montage",
                "source_role": "generated",
                "duration": 4.0,
            }
        ],
        final=True,
    )

    assert [(issue.code, issue.severity) for issue in issues] == [
        ("VQ-FRAME", "error"),
    ]
