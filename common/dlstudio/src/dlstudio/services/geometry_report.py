"""Compact machine-readable source geometry evidence for review."""
from __future__ import annotations

import hashlib
import json
import os
from fractions import Fraction
from pathlib import Path

from dlstudio.ir import Timeline
from dlstudio.model import Design


def timeline_for_design(timeline: Timeline, design: Design) -> Timeline:
    """Project every resolved segment transform onto the effective output size."""
    width, height = design.resolution
    beats = []
    for beat in timeline.beats:
        segments = [
            segment.model_copy(update={
                "geometry": (
                    segment.geometry.for_output(width, height)
                    if segment.geometry is not None
                    else None
                )
            })
            for segment in beat.segments
        ]
        beats.append(beat.model_copy(update={"segments": segments}))
    return timeline.model_copy(update={"design": design, "beats": beats})


def _geometry_payload(timeline: Timeline) -> dict:
    segments: list[dict] = []
    for beat in timeline.beats:
        for index, segment in enumerate(beat.segments):
            geometry = (
                segment.geometry.model_dump(mode="json")
                if segment.geometry is not None
                else None
            )
            resolved = bool(
                geometry
                and geometry["source_width"]
                and geometry["source_height"]
                and geometry["scaled_width"]
                and geometry["scaled_height"]
            )
            segments.append({
                "beat_id": beat.id,
                "segment_index": index,
                "t0": segment.t0,
                "t1": segment.t1,
                "src": segment.src,
                "asset_id": segment.asset_id,
                "editorial_role": segment.editorial_role,
                "resolved": resolved,
                "geometry": geometry,
            })
    return {
        "schema_version": 1,
        "edit_name": timeline.edit_name,
        "output_resolution": list(timeline.design.resolution),
        "segments": segments,
        "summary": {
            "total": len(segments),
            "resolved": sum(1 for item in segments if item["resolved"]),
            "unresolved": sum(1 for item in segments if not item["resolved"]),
        },
    }


def timeline_geometry_sha256(timeline: Timeline) -> str:
    """Return a profile-independent identity for the compiled transform.

    Draft and delivery profiles commonly differ only by a uniform resolution
    scale.  Their proof identity must stay equal while an aspect-ratio, source,
    timing, fit, or anchor change must invalidate it.
    """

    width, height = timeline.design.resolution
    canonical_aspect = Fraction(width, height).limit_denominator(32)
    segments: list[dict] = []
    for beat in timeline.beats:
        for index, segment in enumerate(beat.segments):
            geometry = segment.geometry
            segments.append({
                "beat_id": beat.id,
                "segment_index": index,
                "t0": segment.t0,
                "t1": segment.t1,
                "src": segment.src,
                "asset_id": segment.asset_id,
                "editorial_role": segment.editorial_role,
                "geometry": (
                    {
                        "fit": geometry.fit,
                        "anchor_x": geometry.anchor_x,
                        "anchor_y": geometry.anchor_y,
                        "source_width": geometry.source_width,
                        "source_height": geometry.source_height,
                    }
                    if geometry is not None
                    else None
                ),
            })
    identity = {
        "schema_version": 2,
        "edit_name": timeline.edit_name,
        "output_aspect": [
            canonical_aspect.numerator,
            canonical_aspect.denominator,
        ],
        "segments": segments,
    }
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def build_geometry_report(timeline: Timeline) -> dict:
    payload = _geometry_payload(timeline)
    payload["timeline_sha256"] = timeline_geometry_sha256(timeline)
    return payload


def write_geometry_report(
    timeline: Timeline,
    path: str | Path = "data/review/geometry_report.json",
) -> Path:
    destination = Path(path)
    destination.parent.mkdir(parents=True, exist_ok=True)
    temp = destination.parent / f"{destination.name}.tmp-{os.getpid()}"
    try:
        temp.write_text(
            json.dumps(build_geometry_report(timeline), ensure_ascii=False, indent=2),
            encoding="utf-8",
        )
        os.replace(temp, destination)
    finally:
        temp.unlink(missing_ok=True)
    return destination


__all__ = [
    "build_geometry_report",
    "timeline_for_design",
    "timeline_geometry_sha256",
    "write_geometry_report",
]
