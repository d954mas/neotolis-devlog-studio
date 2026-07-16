"""Shared fixtures/builders for dlstudio cache/cli tests.

compile/ and render/ are NotImplementedError stub bodies during Phase 1
(owned by parallel agents), so tests build IR/model objects directly here
instead of going through dlstudio.compile.build_timeline().
"""
from __future__ import annotations

import os

import pytest

from dlstudio.ir import (
    BeatPlacement,
    IRBeat,
    IRMix,
    IROverlayItem,
    IRSegment,
    IRSfx,
    Timeline,
)
from dlstudio.model import Design, Fonts, Palette


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line(
        "markers", "slow: real-subprocess / timing-sensitive test, slower than the unit suite"
    )


@pytest.fixture(autouse=True)
def _restore_cwd():
    """dlstudio.cli._load_edit() does a real os.chdir(); make sure every
    test starts and ends in the directory pytest was invoked from, no
    matter what the test under it does."""
    cwd = os.getcwd()
    yield
    os.chdir(cwd)


def make_design(width: int = 1920, height: int = 1080) -> Design:
    return Design(
        resolution=(width, height),
        palette=Palette(tokens={"bg": "#000000", "text": "#ffffff", "accent": "#ff2244"}),
        fonts=Fonts(main="fonts/main.ttf"),
    )


def make_ir_beat(
    beat_id: str = "b01",
    *,
    duration: float = 5.0,
    audio: str = "assets/b01.wav",
    words_path: str = "assets/b01_words.json",
    segments: list[IRSegment] | None = None,
    overlays: list[IROverlayItem] | None = None,
    sfx: list[IRSfx] | None = None,
) -> IRBeat:
    if segments is None:
        segments = [IRSegment(kind="image", src="assets/bg.png", offset=0.0, t0=0.0, t1=duration)]
    if sfx is None:
        sfx = []
    return IRBeat(
        id=beat_id,
        duration=duration,
        audio=audio,
        words_path=words_path,
        words=[],
        segments=segments,
        overlays=overlays or [],
        sfx=sfx,
    )


def make_timeline(
    beats: list[IRBeat], *, design: Design | None = None, name: str = "test-edit"
) -> Timeline:
    design = design or make_design()
    placements = []
    t = 0.0
    for b in beats:
        placements.append(BeatPlacement(beat_id=b.id, t0=t))
        t += b.duration
    return Timeline(
        edit_name=name,
        design=design,
        beats=beats,
        placements=placements,
        mix=IRMix(),
        assets={},
        output="data/finalize/output.mp4",
    )
