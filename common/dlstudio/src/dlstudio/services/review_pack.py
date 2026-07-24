"""Build a compact, exact-video-bound packet for model and human review."""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw


class ReviewPackError(RuntimeError):
    pass


_FREEZE_AT_RE = re.compile(r"^freeze@(?P<time>\d+(?:\.\d+)?)s$")
_FREEZE_DURATION_RE = re.compile(
    r"whole-frame freeze candidate (?P<duration>\d+(?:\.\d+)?)s\b"
)
_CADENCE_RANGE_RE = re.compile(
    r"\[(?P<start>\d+(?:\.\d+)?),(?P<end>\d+(?:\.\d+)?)\)"
)


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1 << 20), b""):
            digest.update(block)
    return digest.hexdigest()


def _probe_video(path: Path) -> dict[str, Any]:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-print_format", "json",
                "-show_streams", "-show_format", str(path),
            ],
            capture_output=True, text=True, encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as exc:
        raise ReviewPackError("ffprobe is required for review-pack") from exc
    if result.returncode:
        raise ReviewPackError(f"ffprobe failed: {result.stderr[-500:]}")
    payload = json.loads(result.stdout)
    stream = next(
        (item for item in payload.get("streams", []) if item.get("codec_type") == "video"),
        None,
    )
    if not isinstance(stream, dict):
        raise ReviewPackError(f"video stream is missing: {path}")
    try:
        duration = float(payload["format"]["duration"])
        width = int(stream["width"])
        height = int(stream["height"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ReviewPackError(f"incomplete video facts: {path}") from exc
    rate = str(stream.get("avg_frame_rate", "0/1"))
    try:
        numerator, denominator = rate.split("/", 1)
        fps = float(numerator) / float(denominator)
    except (ValueError, ZeroDivisionError):
        fps = 0.0
    return {"duration": duration, "width": width, "height": height, "fps": fps}


def _read_object(path: Path, default: dict[str, Any]) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError:
        return default
    except json.JSONDecodeError as exc:
        raise ReviewPackError(f"invalid JSON in {path}: {exc}") from exc
    return value if isinstance(value, dict) else default


def _shot_boundaries(root: Path, duration: float) -> tuple[list[dict[str, Any]], list[float]]:
    manifest = _read_object(root / "data/plan/shot_manifest.json", {})
    shots = manifest.get("shots", [])
    if not isinstance(shots, list):
        shots = []
    clean = [item for item in shots if isinstance(item, dict)]
    cuts: list[float] = []
    for shot in clean[:-1]:
        try:
            cut = float(shot.get("t1"))
        except (TypeError, ValueError):
            continue
        if 0.0 < cut < duration:
            cuts.append(cut)
    return clean, cuts


def _sample_times(duration: float, cuts: list[float], count: int) -> list[tuple[float, str]]:
    candidates: list[tuple[float, str]] = []
    for cut in cuts:
        candidates.extend(((max(0.0, cut - 0.08), "boundary"), (min(duration, cut + 0.08), "boundary")))
    even_count = max(4, count - len(candidates))
    candidates.extend(
        (duration * (index + 0.5) / even_count, "sample")
        for index in range(even_count)
    )
    selected: list[tuple[float, str]] = []
    for timestamp, kind in sorted(candidates):
        if any(abs(timestamp - existing) < 0.04 for existing, _ in selected):
            continue
        selected.append((timestamp, kind))
    if len(selected) <= count:
        return selected
    boundary = [item for item in selected if item[1] == "boundary"]
    regular = [item for item in selected if item[1] != "boundary"]
    return sorted((boundary + regular[: max(0, count - len(boundary))])[:count])


def _extract_thumbnail(video: Path, timestamp: float, out: Path, width: int, height: int) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-ss", f"{timestamp:.3f}",
            "-i", str(video), "-frames:v", "1", "-vf", f"scale={width}:{height}",
            "-q:v", "4", str(out),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode or not out.is_file():
        raise ReviewPackError(f"thumbnail extraction failed at {timestamp:.3f}s: {result.stderr[-500:]}")


def _freeze_candidates(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for issue in preflight.get("issues", []):
        if not isinstance(issue, dict) or issue.get("code") != "VQ-FREEZE":
            continue
        time_match = _FREEZE_AT_RE.match(str(issue.get("where") or ""))
        duration_match = _FREEZE_DURATION_RE.search(str(issue.get("message") or ""))
        if time_match is None or duration_match is None:
            continue
        candidates.append({
            "time": float(time_match.group("time")),
            "duration": float(duration_match.group("duration")),
            "severity": str(issue.get("severity") or "warn"),
        })
    return candidates


def _cadence_candidates(preflight: dict[str, Any]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for issue in preflight.get("issues", []):
        if not isinstance(issue, dict) or issue.get("code") != "VQ-CADENCE":
            continue
        range_match = _CADENCE_RANGE_RE.search(str(issue.get("message") or ""))
        if range_match is None:
            continue
        start = float(range_match.group("start"))
        end = float(range_match.group("end"))
        if end <= start:
            continue
        candidates.append({
            "time": start,
            "duration": end - start,
            "severity": str(issue.get("severity") or "warn"),
        })
    return candidates


def _extract_freeze_clip(
    video: Path,
    start: float,
    duration: float,
    out: Path,
    width: int,
) -> None:
    out.parent.mkdir(parents=True, exist_ok=True)
    result = subprocess.run(
        [
            "ffmpeg", "-v", "error", "-y", "-ss", f"{start:.3f}",
            "-i", str(video), "-t", f"{duration:.3f}",
            "-map", "0:v:0", "-map", "0:a?", "-vf", f"scale={width}:-2",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", "23",
            "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "96k",
            "-movflags", "+faststart", str(out),
        ],
        capture_output=True, text=True, encoding="utf-8", errors="replace",
    )
    if result.returncode or not out.is_file():
        raise ReviewPackError(
            f"freeze evidence extraction failed at {start:.3f}s: {result.stderr[-500:]}"
        )


def _make_sheet(samples: list[dict[str, Any]], root: Path, out: Path) -> None:
    if not samples:
        raise ReviewPackError("review-pack has no thumbnails")
    images = [Image.open(root / item["path"]).convert("RGB") for item in samples]
    try:
        cell_w = max(image.width for image in images)
        cell_h = max(image.height for image in images) + 24
        columns = min(4, len(images))
        rows = (len(images) + columns - 1) // columns
        sheet = Image.new("RGB", (columns * cell_w, rows * cell_h), "#111111")
        draw = ImageDraw.Draw(sheet)
        for index, (image, sample) in enumerate(zip(images, samples)):
            x = (index % columns) * cell_w
            y = (index // columns) * cell_h
            sheet.paste(image, (x + (cell_w - image.width) // 2, y))
            draw.text((x + 6, y + image.height + 4), f"{sample['time']:.2f}s {sample['kind']}", fill="white")
        out.parent.mkdir(parents=True, exist_ok=True)
        sheet.save(out, quality=82, optimize=True)
    finally:
        for image in images:
            image.close()


def build_review_pack(
    root: str | Path,
    video_path: str | Path,
    *,
    max_frames: int = 16,
    thumb_width: int = 320,
) -> tuple[Path, Path]:
    base = Path(root).resolve()
    video = Path(video_path)
    video = video.resolve() if video.is_absolute() else (base / video).resolve()
    if not video.is_file():
        raise ReviewPackError(f"review video is missing: {video}")
    facts = _probe_video(video)
    source_w, source_h = facts["width"], facts["height"]
    width = min(thumb_width, source_w)
    height = max(2, round(source_h * width / source_w))
    if height % 2:
        height += 1
    shots, cuts = _shot_boundaries(base, facts["duration"])
    times = _sample_times(facts["duration"], cuts, max(4, max_frames))

    pack_dir = base / "data/review/review_pack"
    samples: list[dict[str, Any]] = []
    for index, (timestamp, kind) in enumerate(times, start=1):
        path = pack_dir / f"frame_{index:02d}.jpg"
        _extract_thumbnail(video, timestamp, path, width, height)
        samples.append({
            "id": f"frame_{index:02d}", "time": round(timestamp, 3), "kind": kind,
            "path": path.relative_to(base).as_posix(), "bytes": path.stat().st_size,
        })

    sheet_path = base / "data/review/review_pack_sheet.jpg"
    _make_sheet(samples, base, sheet_path)
    preflight = _read_object(base / "data/review/preflight.json", {})
    freeze_evidence: list[dict[str, Any]] = []
    evidence_width = min(540, source_w)
    if evidence_width % 2:
        evidence_width -= 1
    for index, candidate in enumerate(_freeze_candidates(preflight), start=1):
        candidate_time = candidate["time"]
        candidate_duration = candidate["duration"]
        clip_start = max(0.0, candidate_time - 0.35)
        clip_duration = min(
            facts["duration"] - clip_start,
            candidate_duration + 0.70,
        )
        clip_path = base / "data/review/freeze_candidates" / f"freeze_{index:02d}.mp4"
        _extract_freeze_clip(video, clip_start, clip_duration, clip_path, evidence_width)
        freeze_evidence.append({
            "id": f"freeze_{index:02d}",
            "time": round(candidate_time, 3),
            "duration": round(candidate_duration, 3),
            "severity": candidate["severity"],
            "clip": clip_path.relative_to(base).as_posix(),
        })
    cadence_evidence: list[dict[str, Any]] = []
    for index, candidate in enumerate(_cadence_candidates(preflight), start=1):
        candidate_time = candidate["time"]
        candidate_duration = candidate["duration"]
        clip_start = max(0.0, candidate_time - 0.15)
        clip_duration = min(
            facts["duration"] - clip_start,
            candidate_duration + 0.30,
            3.5,
        )
        clip_path = base / "data/review/cadence_candidates" / f"cadence_{index:02d}.mp4"
        _extract_freeze_clip(video, clip_start, clip_duration, clip_path, evidence_width)
        cadence_evidence.append({
            "id": f"cadence_{index:02d}",
            "time": round(candidate_time, 3),
            "duration": round(candidate_duration, 3),
            "severity": candidate["severity"],
            "clip": clip_path.relative_to(base).as_posix(),
        })
    story = _read_object(base / "data/plan/story_contract.json", {})
    viewer_text = []
    from dlstudio.services.editorial_preflight import viewer_html_paths, visible_html_text
    for html in viewer_html_paths(base):
        text = " ".join(visible_html_text(html).split())
        viewer_text.append({
            "path": html.relative_to(base).as_posix(),
            "text": text[:1500],
            "truncated": len(text) > 1500,
        })
    payload = {
        "version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "artifact": {
            "path": str(video), "sha256": _sha256(video),
            "duration_seconds": round(facts["duration"], 3),
            "width": source_w, "height": source_h, "fps": round(facts["fps"], 3),
        },
        "compact_review": {
            "sheet": sheet_path.relative_to(base).as_posix(),
            "thumbnail_width": width, "frames": samples,
            "freeze_candidates": freeze_evidence,
            "cadence_candidates": cadence_evidence,
            "open_full_resolution_only_when_anomaly_found": True,
        },
        "shots": [{
            "id": shot.get("id"), "purpose": shot.get("purpose"),
            "src": shot.get("src"), "t0": shot.get("t0"), "t1": shot.get("t1"),
        } for shot in shots],
        "story_contract": story,
        "viewer_text": viewer_text,
        "preflight": {
            "ok": preflight.get("ok"), "errors": preflight.get("errors"),
            "warnings": preflight.get("warnings"),
            "issues": [
                {key: issue.get(key) for key in ("severity", "code", "where")}
                for issue in preflight.get("issues", []) if isinstance(issue, dict)
            ],
        },
    }
    out = base / "data/review/review_pack.json"
    out.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return out, sheet_path


__all__ = ["ReviewPackError", "build_review_pack"]
