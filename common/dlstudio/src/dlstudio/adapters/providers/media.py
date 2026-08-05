"""FFprobe process adapter for the pure asset media-inspection port."""

from __future__ import annotations

import json
import subprocess
from fractions import Fraction
from pathlib import Path
from typing import Any

from dlstudio.application.api import MediaFacts


def _positive_int(value: Any) -> int | None:
    if value in (None, "", "N/A", 0, "0"):
        return None
    parsed = int(value)
    return parsed if parsed > 0 else None


class FfprobeMediaInspector:
    def __init__(self, executable: str = "ffprobe") -> None:
        self.executable = executable

    def _packet_duration_ns(self, path: Path) -> int | None:
        """Measure live WebM/Opus recordings that omit container duration."""

        completed = subprocess.run(
            [
                self.executable,
                "-v",
                "error",
                "-select_streams",
                "a:0",
                "-show_entries",
                "packet=pts_time,duration_time",
                "-of",
                "json",
                str(path.resolve()),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        packets = json.loads(completed.stdout).get("packets", [])
        ranges = tuple(
            (
                Fraction(str(packet["pts_time"])),
                Fraction(str(packet.get("duration_time") or 0)),
            )
            for packet in packets
            if packet.get("pts_time") not in (None, "N/A")
        )
        if not ranges:
            return None
        start = min(pts for pts, _duration in ranges)
        end = max(pts + duration for pts, duration in ranges)
        duration = end - start
        return int(duration * 1_000_000_000) if duration > 0 else None

    def __call__(self, path: Path) -> MediaFacts:
        completed = subprocess.run(
            [
                self.executable,
                "-v",
                "error",
                "-show_streams",
                "-show_format",
                "-of",
                "json",
                str(path.resolve()),
            ],
            check=True,
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        payload = json.loads(completed.stdout)
        streams = payload.get("streams", [])
        video = next(
            (item for item in streams if item.get("codec_type") == "video"),
            None,
        )
        audio = next(
            (item for item in streams if item.get("codec_type") == "audio"),
            None,
        )
        selected = video or audio
        if selected is None:
            raise ValueError("ffprobe found no audio/video stream")
        duration_text = selected.get("duration") or payload.get(
            "format", {}
        ).get("duration")
        duration_ns = (
            None
            if duration_text in (None, "N/A")
            else int(Fraction(str(duration_text)) * 1_000_000_000)
        )
        if duration_ns is None and audio is not None and video is None:
            duration_ns = self._packet_duration_ns(path)
        fps_num = fps_den = None
        if video is not None:
            rate = Fraction(video.get("avg_frame_rate") or "0/1")
            if rate > 0:
                fps_num, fps_den = rate.numerator, rate.denominator
        return MediaFacts(
            kind="video" if video is not None else "audio",
            format_name=str(
                payload.get("format", {}).get("format_name") or "unknown"
            ),
            duration_ns=duration_ns,
            width=_positive_int(selected.get("width")),
            height=_positive_int(selected.get("height")),
            fps_num=fps_num,
            fps_den=fps_den,
            sample_rate=_positive_int(
                None if audio is None else audio.get("sample_rate")
            ),
            channels=_positive_int(
                None if audio is None else audio.get("channels")
            ),
            codec=str(selected.get("codec_name") or "unknown"),
        )
