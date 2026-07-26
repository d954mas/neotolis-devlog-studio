#!/usr/bin/env python3
"""Build compact, repeatable evidence packs for long-form devlog references.

The tool intentionally uses only Python's standard library plus ffmpeg/ffprobe.
It does not try to replace editorial judgment. It makes that judgment auditable:
exact hashes, media facts, scene-change timestamps, loudness, transcript pace,
and timestamped contact sheets.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable


SCHEMA = "devlog.reference_lab/v1"
TIME_RE = re.compile(
    r"(?P<h>\d{2}):(?P<m>\d{2}):(?P<s>\d{2})[,.](?P<ms>\d{3})"
)
PTS_RE = re.compile(r"pts_time:(?P<pts>-?\d+(?:\.\d+)?)")
SCENE_SCORE_RE = re.compile(
    r"lavfi\.scene_score[=:](?P<score>\d+(?:\.\d+)?)"
)
WORD_RE = re.compile(r"[A-Za-zА-Яа-яЁё0-9]+(?:['’\-][A-Za-zА-Яа-яЁё0-9]+)*")


@dataclass(frozen=True)
class Cue:
    start: float
    end: float
    text: str


def run(command: list[str], *, timeout: int = 1800) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        command,
        check=False,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=timeout,
    )


def require_tool(name: str) -> str:
    resolved = shutil.which(name)
    if not resolved:
        raise SystemExit(f"Required tool is missing from PATH: {name}")
    return resolved


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def parse_timestamp(value: str) -> float:
    match = TIME_RE.fullmatch(value.strip())
    if not match:
        raise ValueError(f"Unsupported subtitle timestamp: {value!r}")
    parts = {key: int(raw) for key, raw in match.groupdict().items()}
    return (
        parts["h"] * 3600
        + parts["m"] * 60
        + parts["s"]
        + parts["ms"] / 1000
    )


def parse_srt(path: Path) -> list[Cue]:
    raw = path.read_text(encoding="utf-8-sig", errors="replace")
    blocks = re.split(r"\r?\n\r?\n+", raw.strip())
    cues: list[Cue] = []
    for block in blocks:
        lines = [line.strip() for line in block.splitlines()]
        timing_index = next(
            (index for index, line in enumerate(lines) if " --> " in line),
            None,
        )
        if timing_index is None:
            continue
        left, right = lines[timing_index].split(" --> ", 1)
        text = " ".join(line for line in lines[timing_index + 1 :] if line)
        text = re.sub(r"<[^>]+>", "", text).strip()
        if not text:
            continue
        cues.append(Cue(parse_timestamp(left), parse_timestamp(right), text))
    return cues


def dedupe_autocaption(cues: Iterable[Cue]) -> tuple[str, int]:
    """Collapse YouTube's rolling auto-caption windows into a readable transcript."""
    transcript_words: list[str] = []
    transcript_keys: list[str] = []
    for cue in cues:
        words = WORD_RE.findall(cue.text)
        keys = [word.casefold() for word in words]
        if not keys:
            continue
        max_overlap = min(len(transcript_keys), len(keys), 80)
        overlap = 0
        for count in range(max_overlap, 0, -1):
            if transcript_keys[-count:] == keys[:count]:
                overlap = count
                break
        if overlap == 0 and len(keys) <= len(transcript_keys):
            # Ignore a fully repeated rolling window seen very recently.
            tail = transcript_keys[-min(len(transcript_keys), 120) :]
            needle = " ".join(keys)
            if needle and needle in " ".join(tail):
                continue
        transcript_words.extend(words[overlap:])
        transcript_keys.extend(keys[overlap:])
    return " ".join(transcript_words), len(transcript_words)


def discover_sidecar(video: Path, suffixes: tuple[str, ...]) -> Path | None:
    candidates: list[Path] = []
    for suffix in suffixes:
        candidates.extend(video.parent.glob(f"{video.stem}{suffix}"))
    return sorted(candidates, key=lambda item: item.name)[0] if candidates else None


def ffprobe(path: Path, executable: str) -> dict[str, Any]:
    process = run(
        [
            executable,
            "-v",
            "error",
            "-show_entries",
            "format=duration,size,bit_rate:stream=index,codec_type,codec_name,width,height,r_frame_rate,channels,sample_rate",
            "-of",
            "json",
            str(path),
        ]
    )
    if process.returncode != 0:
        raise RuntimeError(process.stderr.strip())
    return json.loads(process.stdout)


def detect_scenes(path: Path, executable: str, threshold: float) -> list[dict[str, float]]:
    process = run(
        [
            executable,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-an",
            "-vf",
            f"select=gt(scene\\,{threshold}),metadata=print",
            "-fps_mode",
            "vfr",
            "-f",
            "null",
            os.devnull,
        ]
    )
    combined = f"{process.stdout}\n{process.stderr}"
    events: list[dict[str, float]] = []
    pending_pts: float | None = None
    for line in combined.splitlines():
        pts_match = PTS_RE.search(line)
        if pts_match:
            pending_pts = float(pts_match.group("pts"))
        score_match = SCENE_SCORE_RE.search(line)
        if score_match and pending_pts is not None:
            events.append(
                {
                    "time": round(pending_pts, 3),
                    "score": round(float(score_match.group("score")), 6),
                }
            )
            pending_pts = None
    return events


def loudness(path: Path, executable: str) -> dict[str, float | str] | None:
    process = run(
        [
            executable,
            "-hide_banner",
            "-nostats",
            "-i",
            str(path),
            "-vn",
            "-af",
            "loudnorm=I=-14:TP=-1:LRA=11:print_format=json",
            "-f",
            "null",
            os.devnull,
        ]
    )
    matches = re.findall(r"\{\s*\"input_i\".*?\}", process.stderr, flags=re.S)
    if not matches:
        return None
    try:
        raw = json.loads(matches[-1])
    except json.JSONDecodeError:
        return None
    result: dict[str, float | str] = {}
    for key, value in raw.items():
        try:
            result[key] = float(value)
        except (TypeError, ValueError):
            result[key] = value
    return result


def make_contact_sheets(
    path: Path,
    executable: str,
    output_directory: Path,
    *,
    interval: float,
    duration: float,
) -> None:
    output_directory.mkdir(parents=True, exist_ok=True)
    for stale in output_directory.glob("contact_10s_*.jpg"):
        stale.unlink()
    page_span = interval * 16
    page_count = max(1, math.ceil(duration / page_span))
    for page_index in range(page_count):
        start = page_index * page_span
        output_path = output_directory / f"contact_10s_{page_index + 1:03d}.jpg"
        timestamps = [
            min(start + index * interval, max(0.0, duration - 0.05))
            for index in range(16)
        ]
        with tempfile.TemporaryDirectory(
            prefix=f"contact_{page_index + 1:03d}_",
            dir=output_directory,
        ) as temporary:
            frame_root = Path(temporary)
            for frame_index, timestamp_value in enumerate(timestamps):
                timestamp_label = format_timestamp(timestamp_value)
                frame_path = frame_root / f"frame_{frame_index:03d}.jpg"
                drawtext = (
                    "scale=400:-2,"
                    "drawtext=fontcolor=white:fontsize=24:box=1:"
                    "boxcolor=black@0.70:x=8:y=h-th-8:"
                    f"text='{timestamp_label}'"
                )
                process = run(
                    [
                        executable,
                        "-hide_banner",
                        "-loglevel",
                        "error",
                        "-y",
                        "-ss",
                        str(timestamp_value),
                        "-i",
                        str(path),
                        "-vf",
                        drawtext,
                        "-frames:v",
                        "1",
                        "-q:v",
                        "3",
                        str(frame_path),
                    ]
                )
                if process.returncode != 0:
                    raise RuntimeError(process.stderr.strip())
            process = run(
                [
                    executable,
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-y",
                    "-framerate",
                    "1",
                    "-i",
                    str(frame_root / "frame_%03d.jpg"),
                    "-vf",
                    "tile=4x4:nb_frames=16:padding=4:margin=4:color=black",
                    "-frames:v",
                    "1",
                    "-q:v",
                    "3",
                    str(output_path),
                ]
            )
            if process.returncode != 0:
                raise RuntimeError(process.stderr.strip())


def video_stream(probe: dict[str, Any]) -> dict[str, Any]:
    return next(
        (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "video"),
        {},
    )


def audio_stream(probe: dict[str, Any]) -> dict[str, Any]:
    return next(
        (stream for stream in probe.get("streams", []) if stream.get("codec_type") == "audio"),
        {},
    )


def metadata_summary(info_path: Path | None) -> dict[str, Any]:
    if not info_path:
        return {}
    raw = json.loads(info_path.read_text(encoding="utf-8", errors="replace"))
    keys = (
        "id",
        "title",
        "upload_date",
        "webpage_url",
        "view_count",
        "like_count",
        "comment_count",
        "channel",
        "channel_follower_count",
    )
    return {key: raw.get(key) for key in keys if raw.get(key) is not None}


def analyze_video(
    video: Path,
    output_root: Path,
    ffmpeg_exe: str,
    ffprobe_exe: str,
    *,
    scene_threshold: float,
    contact_interval: float,
    skip_sheets: bool,
) -> dict[str, Any]:
    item_id = re.search(r"_([A-Za-z0-9_-]{11})_", video.name)
    slug = item_id.group(1) if item_id else hashlib.sha1(str(video).encode()).hexdigest()[:11]
    item_root = output_root / slug
    item_root.mkdir(parents=True, exist_ok=True)

    probe = ffprobe(video, ffprobe_exe)
    duration = float(probe.get("format", {}).get("duration") or 0)
    scenes = detect_scenes(video, ffmpeg_exe, scene_threshold)
    loudness_result = loudness(video, ffmpeg_exe)
    info_path = discover_sidecar(video, (".info.json",))
    srt_path = discover_sidecar(video, (".en-orig.srt", ".en.srt", "*.srt"))

    transcript: dict[str, Any] = {}
    if srt_path:
        cues = parse_srt(srt_path)
        clean_text, word_count = dedupe_autocaption(cues)
        (item_root / "transcript_clean.txt").write_text(
            clean_text + "\n", encoding="utf-8"
        )
        speech_span = (cues[-1].end - cues[0].start) if cues else 0
        transcript = {
            "source": str(srt_path.resolve()),
            "cue_count": len(cues),
            "deduplicated_word_count": word_count,
            "speech_span_seconds": round(speech_span, 3),
            "words_per_minute": (
                round(word_count / speech_span * 60, 2) if speech_span > 0 else None
            ),
        }

    if not skip_sheets:
        make_contact_sheets(
            video,
            ffmpeg_exe,
            item_root,
            interval=contact_interval,
            duration=duration,
        )

    vstream = video_stream(probe)
    astream = audio_stream(probe)
    result: dict[str, Any] = {
        "schema": SCHEMA,
        "artifact_path": str(video.resolve()),
        "artifact_sha256": sha256(video),
        "file_size": video.stat().st_size,
        "duration_seconds": round(duration, 3),
        "video": {
            key: vstream.get(key)
            for key in ("codec_name", "width", "height", "r_frame_rate")
            if vstream.get(key) is not None
        },
        "audio": {
            key: astream.get(key)
            for key in ("codec_name", "channels", "sample_rate")
            if astream.get(key) is not None
        },
        "metadata": metadata_summary(info_path),
        "transcript": transcript,
        "scene_detection": {
            "threshold": scene_threshold,
            "event_count": len(scenes),
            "events_per_minute": (
                round(len(scenes) / duration * 60, 2) if duration > 0 else None
            ),
            "median_gap_seconds": median_gap([event["time"] for event in scenes], duration),
            "events": scenes,
        },
        "loudness": loudness_result,
    }
    (item_root / "report.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return result


def median_gap(events: list[float], duration: float) -> float | None:
    boundaries = [0.0, *events, duration]
    gaps = sorted(
        max(0.0, boundaries[index + 1] - boundaries[index])
        for index in range(len(boundaries) - 1)
    )
    if not gaps:
        return None
    middle = len(gaps) // 2
    value = gaps[middle] if len(gaps) % 2 else (gaps[middle - 1] + gaps[middle]) / 2
    return round(value, 3)


def write_summary(results: list[dict[str, Any]], output_root: Path) -> None:
    fields = (
        "id",
        "title",
        "duration_seconds",
        "views",
        "likes",
        "comments",
        "words_per_minute",
        "scene_events_per_minute",
        "median_scene_gap_seconds",
        "integrated_lufs",
        "true_peak_dbtp",
        "sha256",
        "artifact_path",
    )
    rows: list[dict[str, Any]] = []
    for result in results:
        metadata = result.get("metadata", {})
        transcript = result.get("transcript", {})
        scenes = result.get("scene_detection", {})
        audio = result.get("loudness") or {}
        rows.append(
            {
                "id": metadata.get("id", ""),
                "title": metadata.get("title", Path(result["artifact_path"]).stem),
                "duration_seconds": result.get("duration_seconds"),
                "views": metadata.get("view_count", ""),
                "likes": metadata.get("like_count", ""),
                "comments": metadata.get("comment_count", ""),
                "words_per_minute": transcript.get("words_per_minute", ""),
                "scene_events_per_minute": scenes.get("events_per_minute", ""),
                "median_scene_gap_seconds": scenes.get("median_gap_seconds", ""),
                "integrated_lufs": audio.get("input_i", ""),
                "true_peak_dbtp": audio.get("input_tp", ""),
                "sha256": result.get("artifact_sha256"),
                "artifact_path": result.get("artifact_path"),
            }
        )

    with (output_root / "summary.csv").open(
        "w", newline="", encoding="utf-8-sig"
    ) as handle:
        writer = csv.DictWriter(handle, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    headers = (
        "Video",
        "Length",
        "Views",
        "WPM",
        "Scene events/min",
        "Median gap",
        "LUFS",
    )
    markdown = [
        "# Reference-lab summary",
        "",
        f"Schema: `{SCHEMA}`. Scene events use a visual-change threshold, not a "
        "claim that every event is an editorial hard cut.",
        "",
        "| " + " | ".join(headers) + " |",
        "|" + "|".join("---" for _ in headers) + "|",
    ]
    for row in rows:
        length = format_duration(float(row["duration_seconds"] or 0))
        title = str(row["title"]).replace("|", "\\|")
        markdown.append(
            "| "
            + " | ".join(
                str(value)
                for value in (
                    title,
                    length,
                    row["views"],
                    row["words_per_minute"],
                    row["scene_events_per_minute"],
                    row["median_scene_gap_seconds"],
                    row["integrated_lufs"],
                )
            )
            + " |"
        )
    markdown.extend(
        [
            "",
            "Each per-video directory contains `report.json`, "
            "`transcript_clean.txt` when subtitles exist, and 10-second "
            "timestamped contact-sheet pages.",
            "",
        ]
    )
    (output_root / "summary.md").write_text(
        "\n".join(markdown), encoding="utf-8"
    )


def format_duration(seconds: float) -> str:
    rounded = int(round(seconds))
    return f"{rounded // 60}:{rounded % 60:02d}"


def format_timestamp(seconds: float) -> str:
    tenths = int(round(seconds * 10))
    hours, remainder = divmod(tenths, 36000)
    minutes, remainder = divmod(remainder, 600)
    whole_seconds, tenth = divmod(remainder, 10)
    return f"{hours:02d}\\:{minutes:02d}\\:{whole_seconds:02d}.{tenth}"


def collect_inputs(raw_inputs: list[str]) -> list[Path]:
    videos: list[Path] = []
    for raw in raw_inputs:
        path = Path(raw).resolve()
        if path.is_dir():
            videos.extend(sorted(path.glob("*.mp4")))
        elif path.suffix.casefold() == ".mp4" and path.exists():
            videos.append(path)
        else:
            raise SystemExit(f"Input is not an MP4 or directory: {path}")
    unique: dict[str, Path] = {str(video).casefold(): video for video in videos}
    if not unique:
        raise SystemExit("No MP4 files found.")
    return list(unique.values())


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "inputs",
        nargs="+",
        help="MP4 files or directories containing MP4 files.",
    )
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--scene-threshold", type=float, default=0.26)
    parser.add_argument("--contact-interval", type=float, default=10.0)
    parser.add_argument(
        "--skip-sheets",
        action="store_true",
        help="Collect numeric evidence without rendering contact sheets.",
    )
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    if hasattr(sys.stderr, "reconfigure"):
        sys.stderr.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    ffmpeg_exe = require_tool("ffmpeg")
    ffprobe_exe = require_tool("ffprobe")
    output_root = args.out.resolve()
    output_root.mkdir(parents=True, exist_ok=True)
    videos = collect_inputs(args.inputs)
    results: list[dict[str, Any]] = []
    for index, video in enumerate(videos, start=1):
        print(f"[{index}/{len(videos)}] {video.name}", flush=True)
        results.append(
            analyze_video(
                video,
                output_root,
                ffmpeg_exe,
                ffprobe_exe,
                scene_threshold=args.scene_threshold,
                contact_interval=args.contact_interval,
                skip_sheets=args.skip_sheets,
            )
        )
    write_summary(results, output_root)
    print(f"Wrote evidence pack: {output_root}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
