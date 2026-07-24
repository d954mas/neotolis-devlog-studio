from __future__ import annotations

import json

from _builders import mk_design
from dlstudio.ir import BeatPlacement, IRBeat, IRMix, IRSegment, Timeline
from dlstudio.services.boundary_report import write_boundary_report


def test_boundary_report_exposes_restart_and_missing_intent(tmp_path):
    beat = IRBeat(
        id="day7",
        duration=4.0,
        audio="voice.wav",
        words_path="words.json",
        words=[],
        overlays=[],
        segments=[
            IRSegment(
                kind="video",
                src="data/footage/day7.mp4",
                asset_id="capture:day7",
                editorial_role="gameplay",
                offset=0.0,
                t0=0.0,
                t1=2.0,
            ),
            IRSegment(
                kind="video",
                src="data/footage/day7.mp4",
                asset_id="capture:day7",
                editorial_role="gameplay",
                offset=0.0,
                t0=2.0,
                t1=4.0,
            ),
        ],
    )
    timeline = Timeline(
        edit_name="devlog",
        design=mk_design(),
        beats=[beat],
        placements=[BeatPlacement(beat_id="day7", t0=0.0)],
        mix=IRMix(),
        assets={},
        output="out.mp4",
    )

    destination = write_boundary_report(timeline, tmp_path / "boundaries.json")
    payload = json.loads(destination.read_text(encoding="utf-8"))

    assert payload["summary"]["boundaries"] == 1
    assert payload["summary"]["undeclared_gameplay_boundaries"] == 1
    assert payload["summary"]["rewinds_or_restarts"] == 1
    boundary = payload["boundaries"][0]
    assert boundary["expected_right_offset"] == 2.0
    assert boundary["actual_right_offset"] == 0.0
