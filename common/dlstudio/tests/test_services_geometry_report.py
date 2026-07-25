from __future__ import annotations

import json

from _builders import mk_design
from dlstudio.ir import (
    BeatPlacement,
    IRBeat,
    IRMix,
    IRSegment,
    IRSegmentGeometry,
    Timeline,
)
from dlstudio.services.geometry_report import timeline_for_design, write_geometry_report


def test_geometry_report_persists_compact_resolved_transform(tmp_path):
    geometry = IRSegmentGeometry(
        fit="cover",
        anchor_x=0.5,
        anchor_y=0.5,
        source_width=200,
        source_height=100,
        scaled_width=200,
        scaled_height=100,
        output_width=100,
        output_height=100,
        crop_x=50,
        crop_y=0,
        crop_width=100,
        crop_height=100,
    )
    beat = IRBeat(
        id="day4",
        duration=5.0,
        audio="voice.wav",
        words_path="words.json",
        words=[],
        overlays=[],
        segments=[
            IRSegment(
                kind="video",
                src="data/footage/day4.mp4",
                asset_id="capture:day4",
                editorial_role="gameplay",
                offset=0.0,
                t0=0.0,
                t1=5.0,
                geometry=geometry,
            )
        ],
    )
    timeline = Timeline(
        edit_name="devlog",
        design=mk_design(resolution=(100, 100)),
        beats=[beat],
        placements=[BeatPlacement(beat_id="day4", t0=0.0)],
        mix=IRMix(),
        assets={},
        output="out.mp4",
    )

    destination = write_geometry_report(timeline, tmp_path / "geometry.json")
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert payload["summary"] == {"total": 1, "resolved": 1, "unresolved": 0}
    assert payload["segments"][0]["asset_id"] == "capture:day4"
    assert payload["segments"][0]["geometry"]["crop_x"] == 50

    effective = timeline_for_design(
        timeline,
        timeline.design.model_copy(update={"resolution": (50, 100)}),
    )
    projected = effective.beats[0].segments[0].geometry
    assert effective.design.resolution == (50, 100)
    assert projected is not None
    assert (projected.output_width, projected.output_height) == (50, 100)
    assert (projected.scaled_width, projected.scaled_height) == (200, 100)
    assert projected.crop_x == 75
