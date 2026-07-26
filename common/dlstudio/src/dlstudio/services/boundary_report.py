"""Machine-first table of every compiled visual boundary."""
from __future__ import annotations

import json
import os
from pathlib import Path

from dlstudio.ir import Timeline

BOUNDARY_OFFSET_TOLERANCE = 0.12


def build_boundary_report(timeline: Timeline) -> dict:
    placement_by_beat = {item.beat_id: item.t0 for item in timeline.placements}
    entries: list[dict] = []
    for beat in timeline.beats:
        beat_start = placement_by_beat.get(beat.id, 0.0)
        for index, segment in enumerate(beat.segments):
            entries.append({
                "at": beat_start + segment.t0,
                "beat_id": beat.id,
                "segment_index": index,
                "src": segment.src,
                "asset_id": segment.asset_id,
                "editorial_role": segment.editorial_role,
                "offset": segment.offset,
                "duration": max(0.0, segment.t1 - segment.t0),
                "transition_intent": segment.transition_intent,
            })
    entries.sort(key=lambda item: item["at"])

    boundaries: list[dict] = []
    last_source_end: dict[str, float] = {}
    for index, right in enumerate(entries):
        right_key = right["asset_id"] or right["src"]
        prior_end = last_source_end.get(right_key)
        if index > 0:
            left = entries[index - 1]
            left_key = left["asset_id"] or left["src"]
            expected_offset = (
                left["offset"] + left["duration"]
                if left_key == right_key
                else None
            )
            boundaries.append({
                "at": right["at"],
                "left": {
                    "beat_id": left["beat_id"],
                    "segment_index": left["segment_index"],
                    "asset_id": left["asset_id"],
                    "src": left["src"],
                },
                "right": {
                    "beat_id": right["beat_id"],
                    "segment_index": right["segment_index"],
                    "asset_id": right["asset_id"],
                    "src": right["src"],
                },
                "gameplay": (
                    left["editorial_role"] == "gameplay"
                    or right["editorial_role"] == "gameplay"
                ),
                "transition_intent": right["transition_intent"],
                "source_changed": left_key != right_key,
                "expected_right_offset": expected_offset,
                "actual_right_offset": right["offset"],
                "offset_delta": (
                    None
                    if expected_offset is None
                    else right["offset"] - expected_offset
                ),
                "prior_same_source_end": prior_end,
                "rewind_or_restart": (
                    prior_end is not None
                    and right["offset"] < prior_end - BOUNDARY_OFFSET_TOLERANCE
                ),
            })
        last_source_end[right_key] = right["offset"] + right["duration"]

    return {
        "schema_version": 1,
        "edit_name": timeline.edit_name,
        "segments": entries,
        "boundaries": boundaries,
        "summary": {
            "segments": len(entries),
            "boundaries": len(boundaries),
            "gameplay_boundaries": sum(
                1 for item in boundaries if item["gameplay"]
            ),
            "undeclared_gameplay_boundaries": sum(
                1
                for item in boundaries
                if item["gameplay"] and item["transition_intent"] is None
            ),
            "rewinds_or_restarts": sum(
                1 for item in boundaries if item["rewind_or_restart"]
            ),
        },
    }


def write_boundary_report(
    timeline: Timeline,
    path: str | Path = "data/review/boundary_report.json",
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.parent / f"{destination.name}.tmp-{os.getpid()}"
    try:
        temp.write_text(
            json.dumps(build_boundary_report(timeline), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    return destination


__all__ = [
    "BOUNDARY_OFFSET_TOLERANCE",
    "build_boundary_report",
    "write_boundary_report",
]
