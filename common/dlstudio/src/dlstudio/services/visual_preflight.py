"""Deterministic visual preflight gates.

``VQ-GLYPH`` reads the Unicode cmap of the exact production fonts used by
overlay/plate/decorative text and compiled captions.  ``VQ-FRAME`` samples
image/video sources and measures border-connected empty bands plus obviously
small foreground bounds.  Neither gate uses an AI runtime.
"""
from __future__ import annotations

import io
import math
import struct
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable

import numpy as np
from PIL import Image

from dlstudio.ir import CheckIssue, CheckReport
from dlstudio.model import CaptionPill, Label, Overlay, Plate


_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".webp", ".bmp"}
_VIDEO_EXTS = {".mp4", ".mov", ".webm", ".mkv", ".avi"}


@dataclass(frozen=True)
class _TextUse:
    text: str
    font_role: str
    where: str


@dataclass(frozen=True)
class _FrameSource:
    path: str
    where: str
    duration: float | None
    generated_montage: bool


def _resolved_path(root: Path, value: str) -> Path:
    path = Path(value)
    return path if path.is_absolute() else root / path


def _font_path(design: Any, role: str) -> str:
    fonts = design.fonts
    if role == "main":
        return fonts.main
    return getattr(fonts, role, None) or fonts.main


def _text_uses(edit: Any, timeline: Any) -> list[_TextUse]:
    uses: list[_TextUse] = []
    design = getattr(edit, "design", None)
    if design is None:
        return uses
    order = getattr(edit, "order", [])
    beats = getattr(edit, "beats", {})
    for beat_id in order:
        beat = beats.get(beat_id)
        if beat is None:
            continue
        for index, chunk in enumerate(getattr(beat, "chunks", [])):
            where = f"{beat_id}:{index}"
            content = chunk.content
            if isinstance(content, (Plate, Overlay)):
                style = design.style(content.style)
                text = content.text.upper() if style.caps else content.text
                uses.append(_TextUse(text, style.font, where))
                subtitle = getattr(content, "subtitle", None)
                if subtitle:
                    if style.caps:
                        subtitle = subtitle.upper()
                    uses.append(_TextUse(subtitle, style.font, where))
            for decoration in getattr(chunk, "decorations", []):
                if isinstance(decoration, (Label, CaptionPill)):
                    uses.append(_TextUse(decoration.text, "bold", where))

    caption_role = design.captions.font
    for beat in getattr(timeline, "beats", []):
        for caption in getattr(beat, "captions", []):
            uses.append(_TextUse(caption.text, caption_role, f"{beat.id}:caption"))
    return [use for use in uses if use.text]


def _u16(data: bytes, offset: int) -> int:
    return struct.unpack_from(">H", data, offset)[0]


def _u32(data: bytes, offset: int) -> int:
    return struct.unpack_from(">I", data, offset)[0]


def _unicode_cmap_offsets(data: bytes) -> list[int]:
    if len(data) < 12 or data[:4] == b"ttcf":
        raise ValueError("font collections are not supported by the cmap reader")
    num_tables = _u16(data, 4)
    cmap_offset = None
    for index in range(num_tables):
        record = 12 + index * 16
        if record + 16 > len(data):
            raise ValueError("truncated SFNT table directory")
        if data[record : record + 4] == b"cmap":
            cmap_offset = _u32(data, record + 8)
            break
    if cmap_offset is None or cmap_offset + 4 > len(data):
        raise ValueError("font has no readable cmap table")

    count = _u16(data, cmap_offset + 2)
    offsets: list[int] = []
    for index in range(count):
        record = cmap_offset + 4 + index * 8
        if record + 8 > len(data):
            raise ValueError("truncated cmap encoding records")
        platform = _u16(data, record)
        encoding = _u16(data, record + 2)
        if platform == 0 or (platform == 3 and encoding in {1, 10}):
            offsets.append(cmap_offset + _u32(data, record + 4))
    if not offsets:
        raise ValueError("font exposes no Unicode cmap")
    return offsets


def _format4_contains(data: bytes, base: int, codepoint: int) -> bool:
    if codepoint > 0xFFFF or base + 14 > len(data):
        return False
    seg_count = _u16(data, base + 6) // 2
    end_codes = base + 14
    start_codes = end_codes + seg_count * 2 + 2
    deltas = start_codes + seg_count * 2
    range_offsets = deltas + seg_count * 2
    if range_offsets + seg_count * 2 > len(data):
        raise ValueError("truncated cmap format 4")
    for index in range(seg_count):
        end = _u16(data, end_codes + index * 2)
        if codepoint > end:
            continue
        start = _u16(data, start_codes + index * 2)
        if codepoint < start:
            return False
        delta = _u16(data, deltas + index * 2)
        range_offset_pos = range_offsets + index * 2
        range_offset = _u16(data, range_offset_pos)
        if range_offset == 0:
            return ((codepoint + delta) & 0xFFFF) != 0
        glyph_pos = range_offset_pos + range_offset + (codepoint - start) * 2
        if glyph_pos + 2 > len(data):
            raise ValueError("truncated cmap format 4 glyph array")
        glyph = _u16(data, glyph_pos)
        return glyph != 0 and ((glyph + delta) & 0xFFFF) != 0
    return False


def _format12_or_13_contains(data: bytes, base: int, codepoint: int) -> bool:
    if base + 16 > len(data):
        raise ValueError("truncated cmap format 12/13")
    fmt = _u16(data, base)
    groups = _u32(data, base + 12)
    lo, hi = 0, groups
    while lo < hi:
        mid = (lo + hi) // 2
        pos = base + 16 + mid * 12
        if pos + 12 > len(data):
            raise ValueError("truncated cmap groups")
        start = _u32(data, pos)
        end = _u32(data, pos + 4)
        if codepoint < start:
            hi = mid
        elif codepoint > end:
            lo = mid + 1
        else:
            glyph = _u32(data, pos + 8)
            return glyph != 0 if fmt == 13 else glyph + codepoint - start != 0
    return False


def _font_has_codepoint(data: bytes, offsets: Iterable[int], codepoint: int) -> bool:
    for base in offsets:
        if base + 2 > len(data):
            raise ValueError("truncated cmap subtable")
        fmt = _u16(data, base)
        if fmt == 4 and _format4_contains(data, base, codepoint):
            return True
        if fmt in {12, 13} and _format12_or_13_contains(data, base, codepoint):
            return True
    return False


def check_glyph_coverage(edit: Any, timeline: Any, root: str | Path) -> list[CheckIssue]:
    """Check every rasterized text string against its actual production font."""
    base = Path(root)
    issues: list[CheckIssue] = []
    by_font: dict[str, list[_TextUse]] = {}
    for use in _text_uses(edit, timeline):
        font = _font_path(edit.design, use.font_role)
        by_font.setdefault(font, []).append(use)

    for font_ref, uses in by_font.items():
        font_path = _resolved_path(base, font_ref)
        try:
            data = font_path.read_bytes()
            offsets = _unicode_cmap_offsets(data)
            if not any(
                offset + 2 <= len(data) and _u16(data, offset) in {4, 12, 13}
                for offset in offsets
            ):
                raise ValueError("font has no supported Unicode cmap format")
        except (OSError, ValueError, struct.error) as exc:
            locations = ", ".join(sorted({use.where for use in uses}))
            issues.append(CheckIssue(
                severity="warn",
                code="VQ-GLYPH",
                message=(
                    f"glyph coverage unknown: cannot inspect production font "
                    f"{font_ref!r} ({exc})"
                ),
                where=locations,
            ))
            continue

        findings: list[tuple[_TextUse, list[int]]] = []
        try:
            for use in uses:
                missing = sorted({
                    ord(char)
                    for char in use.text
                    if not char.isspace()
                    and not _font_has_codepoint(data, offsets, ord(char))
                })
                findings.append((use, missing))
        except (ValueError, struct.error) as exc:
            locations = ", ".join(sorted({use.where for use in uses}))
            issues.append(CheckIssue(
                severity="warn",
                code="VQ-GLYPH",
                message=(
                    f"glyph coverage unknown: cannot inspect production font "
                    f"{font_ref!r} ({exc})"
                ),
                where=locations,
            ))
            continue

        for use, missing in findings:
            if not missing:
                continue
            display = ", ".join(f"U+{codepoint:04X}" for codepoint in missing)
            issues.append(CheckIssue(
                severity="error",
                code="VQ-GLYPH",
                message=f"production font {font_ref!r} is missing glyphs: {display}",
                where=use.where,
            ))
    return issues


def _catalog_assets(catalog: Any | None) -> dict[str, Any]:
    return {
        str(asset.path).replace("\\", "/"): asset
        for asset in getattr(catalog, "assets", [])
    }


def _float_or_none(value: Any) -> float | None:
    try:
        result = float(value)
    except (TypeError, ValueError):
        return None
    return result if result > 0 else None


def _frame_sources(
    *, timeline: Any | None, shots: list[dict[str, Any]] | None, catalog: Any | None,
) -> list[_FrameSource]:
    assets = _catalog_assets(catalog)
    sources: list[_FrameSource] = []
    if shots is not None:
        for index, shot in enumerate(shots):
            src = str(shot.get("src") or "").replace("\\", "/")
            if Path(src).suffix.casefold() not in _IMAGE_EXTS | _VIDEO_EXTS:
                continue
            asset = assets.get(src)
            role = str(shot.get("source_role") or getattr(asset, "source_role", ""))
            generated = role == "generated" or any(
                token in f"/{src.casefold()}" for token in ("/infographics/", "/hyperframes/")
            )
            montage = str(shot.get("intent", "")).casefold() == "montage"
            duration = _float_or_none(shot.get("duration"))
            if duration is None:
                duration = _float_or_none(getattr(asset, "duration", None))
            sources.append(_FrameSource(
                path=src,
                where=str(shot.get("id") or f"shot-{index}"),
                duration=duration,
                generated_montage=generated and montage,
            ))
    elif timeline is not None:
        durations = {
            str(path).replace("\\", "/"): _float_or_none(getattr(probe, "duration", None))
            for path, probe in getattr(timeline, "assets", {}).items()
        }
        for beat in getattr(timeline, "beats", []):
            for segment in getattr(beat, "segments", []):
                src = str(segment.src).replace("\\", "/")
                sources.append(_FrameSource(
                    path=src,
                    where=f"{beat.id}:{src}",
                    duration=durations.get(src),
                    generated_montage=False,
                ))

    unique: dict[tuple[str, str], _FrameSource] = {}
    for source in sources:
        unique.setdefault((source.path, source.where), source)
    return list(unique.values())


def _probe_video_duration(path: Path) -> float | None:
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "error", "-show_entries", "format=duration",
                "-of", "default=noprint_wrappers=1:nokey=1", str(path),
            ],
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
    except OSError:
        return None
    return _float_or_none(result.stdout.strip()) if result.returncode == 0 else None


def _sample_video_frames(
    path: Path, duration: float | None,
) -> tuple[list[Image.Image], str | None]:
    duration = duration or _probe_video_duration(path)
    times = [0.0] if duration is None else [duration * value for value in (0.1, 0.5, 0.9)]
    frames: list[Image.Image] = []
    for timestamp in times:
        try:
            result = subprocess.run(
                [
                    "ffmpeg", "-v", "error", "-ss", f"{timestamp:.6f}",
                    "-i", str(path), "-frames:v", "1", "-f", "image2pipe",
                    "-vcodec", "png", "pipe:1",
                ],
                capture_output=True,
            )
        except OSError as exc:
            return frames, str(exc)
        if result.returncode or not result.stdout:
            detail = result.stderr.decode("utf-8", errors="replace").strip()
            return frames, detail or "ffmpeg returned no frame"
        try:
            with Image.open(io.BytesIO(result.stdout)) as image:
                frames.append(image.convert("RGB").copy())
        except OSError as exc:
            return frames, f"invalid decoded frame: {exc}"
    return frames, None


def _edge_band_fraction(array: np.ndarray, *, axis: int, reverse: bool) -> float:
    lines = np.moveaxis(array, axis, 0)
    if reverse:
        lines = lines[::-1]
    edge = lines[0].reshape(-1, 3)
    if float(edge.std(axis=0).max()) > 14.0:
        return 0.0
    edge_color = edge.mean(axis=0)
    count = 0
    for line in lines:
        pixels = line.reshape(-1, 3)
        if float(pixels.std(axis=0).max()) > 14.0:
            break
        if float(np.abs(pixels.mean(axis=0) - edge_color).max()) > 18.0:
            break
        count += 1
    return count / len(lines)


def _frame_metrics(image: Image.Image) -> tuple[float, float]:
    frame = image.convert("RGB")
    frame.thumbnail((320, 320), Image.Resampling.BILINEAR)
    array = np.asarray(frame, dtype=np.int16)
    if array.size == 0:
        return 1.0, 0.0
    top = _edge_band_fraction(array, axis=0, reverse=False)
    bottom = _edge_band_fraction(array, axis=0, reverse=True)
    left = _edge_band_fraction(array, axis=1, reverse=False)
    right = _edge_band_fraction(array, axis=1, reverse=True)
    empty_band = max(top + bottom, left + right)

    height, width = array.shape[:2]
    patch = max(1, min(height, width) // 20)
    corners = np.concatenate([
        array[:patch, :patch].reshape(-1, 3),
        array[:patch, -patch:].reshape(-1, 3),
        array[-patch:, :patch].reshape(-1, 3),
        array[-patch:, -patch:].reshape(-1, 3),
    ])
    if float(corners.std(axis=0).max()) > 18.0:
        return empty_band, 1.0
    background = np.median(corners, axis=0)
    foreground = np.max(np.abs(array - background), axis=2) > 24
    ys, xs = np.nonzero(foreground)
    if len(xs) == 0:
        return max(empty_band, 1.0), 0.0
    bbox_fraction = ((xs.max() - xs.min() + 1) * (ys.max() - ys.min() + 1)) / (width * height)
    return empty_band, float(bbox_fraction)


def check_frame_occupancy(
    root: str | Path,
    *,
    timeline: Any | None = None,
    shots: list[dict[str, Any]] | None = None,
    catalog: Any | None = None,
    final: bool = False,
) -> list[CheckIssue]:
    """Inspect source frames for gross empty bands/letterbox/small content."""
    base = Path(root)
    issues: list[CheckIssue] = []
    for source in _frame_sources(timeline=timeline, shots=shots, catalog=catalog):
        path = _resolved_path(base, source.path)
        frames: list[Image.Image] = []
        error: str | None = None
        if path.suffix.casefold() in _IMAGE_EXTS:
            try:
                with Image.open(path) as image:
                    frames = [image.convert("RGB").copy()]
            except OSError as exc:
                error = str(exc)
        else:
            frames, error = _sample_video_frames(path, source.duration)
        if error is not None or not frames:
            issues.append(CheckIssue(
                severity="warn",
                code="VQ-FRAME",
                message=f"frame occupancy unknown for {source.path!r}: {error or 'no sample frame'}",
                where=source.where,
            ))
            continue

        metrics = [_frame_metrics(frame) for frame in frames]
        bad = [
            (empty, bbox)
            for empty, bbox in metrics
            if empty >= 0.20 or bbox < 0.45
        ]
        if len(bad) < math.ceil(len(metrics) / 2):
            continue
        empty = max(value[0] for value in bad)
        bbox = min(value[1] for value in bad)
        severity = "error" if final and source.generated_montage else "warn"
        issues.append(CheckIssue(
            severity=severity,
            code="VQ-FRAME",
            message=(
                f"gross empty/letterbox area detected in {len(bad)}/{len(metrics)} "
                f"sample frames (edge_empty={empty:.1%}, content_bbox={bbox:.1%})"
            ),
            where=source.where,
        ))
    return issues


def run_visual_preflight(
    edit: Any,
    timeline: Any,
    root: str | Path,
    *,
    shots: list[dict[str, Any]] | None = None,
    catalog: Any | None = None,
    final: bool = False,
) -> CheckReport:
    issues = check_glyph_coverage(edit, timeline, root)
    issues.extend(check_frame_occupancy(
        root,
        timeline=timeline,
        shots=shots,
        catalog=catalog,
        final=final,
    ))
    return CheckReport(issues=issues)


__all__ = [
    "check_frame_occupancy",
    "check_glyph_coverage",
    "run_visual_preflight",
]
