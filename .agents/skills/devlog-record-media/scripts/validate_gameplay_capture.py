#!/usr/bin/env python3
"""Machine-first validation for gameplay capture contracts and artifacts."""

from __future__ import annotations

import argparse
from fractions import Fraction
import json
from pathlib import Path
import re
import shutil
import subprocess
import sys
from typing import Any


class Audit:
    def __init__(self) -> None:
        self.checks: list[dict[str, Any]] = []
        self.facts: dict[str, Any] = {}

    def add(self, status: str, code: str, message: str) -> None:
        self.checks.append({"status": status, "code": code, "message": message})

    def require(self, condition: bool, code: str, ok: str, error: str) -> None:
        self.add("pass" if condition else "error", code, ok if condition else error)

    @property
    def errors(self) -> int:
        return sum(item["status"] == "error" for item in self.checks)


def _load_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise ValueError(f"JSON file not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return value


def _result_for(path: Path, request_id: str) -> dict[str, Any]:
    payload = _load_json(path)
    results = payload.get("results")
    if not isinstance(results, list):
        raise ValueError("capture results must contain a results list")
    matches = [item for item in results if isinstance(item, dict) and item.get("request_id") == request_id]
    if len(matches) != 1:
        raise ValueError(f"expected exactly one result for {request_id}, found {len(matches)}")
    return matches[0]


def _method_from_result(result: dict[str, Any]) -> str | None:
    structured = result.get("capture_method")
    if isinstance(structured, str) and structured:
        return structured
    note = str(result.get("note", "")).casefold()
    if "devapi" in note and ("framebuffer" in note or "frame" in note):
        return "deterministic_devapi"
    if "real-time window" in note or "realtime window" in note:
        return "realtime_window"
    return None


def _resolve_artifact(
    contract: dict[str, Any],
    production_root: Path,
    result: dict[str, Any] | None,
) -> Path:
    raw = result.get("path") if result is not None else contract.get("artifact")
    if not isinstance(raw, str) or not raw:
        raise ValueError("artifact path is missing")
    path = Path(raw)
    return path.resolve() if path.is_absolute() else (production_root / path).resolve()


def _probe(video: Path, ffprobe: str) -> dict[str, Any]:
    command = [
        ffprobe,
        "-v",
        "error",
        "-select_streams",
        "v:0",
        "-show_entries",
        "stream=width,height,avg_frame_rate,r_frame_rate:format=duration",
        "-of",
        "json",
        str(video),
    ]
    run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8")
    if run.returncode != 0:
        raise ValueError(f"ffprobe failed: {run.stderr.strip()}")
    payload = json.loads(run.stdout)
    streams = payload.get("streams") or []
    if not streams:
        raise ValueError("artifact has no video stream")
    stream = streams[0]
    rate_raw = stream.get("avg_frame_rate") or stream.get("r_frame_rate") or "0/1"
    return {
        "width": int(stream["width"]),
        "height": int(stream["height"]),
        "fps": float(Fraction(rate_raw)),
        "duration": float(payload["format"]["duration"]),
    }


def _freeze_durations(video: Path, ffmpeg: str, threshold: float) -> list[float]:
    command = [
        ffmpeg,
        "-hide_banner",
        "-nostats",
        "-i",
        str(video),
        "-vf",
        f"freezedetect=noise=-50dB:d={threshold}",
        "-an",
        "-f",
        "null",
        "-",
    ]
    run = subprocess.run(command, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if run.returncode != 0:
        raise ValueError(f"FFmpeg freeze scan failed: {run.stderr[-500:]}")
    return [float(value) for value in re.findall(r"freeze_duration:\\s*([0-9.]+)", run.stderr)]


def _presentation_checks(
    audit: Audit,
    contract: dict[str, Any],
    width: int,
    height: int,
) -> None:
    presentation = contract.get("presentation")
    if not isinstance(presentation, dict):
        audit.add("error", "CAPTURE-PRESENTATION", "presentation contract is missing")
        return
    out_w = int(presentation.get("output_width", 0))
    out_h = int(presentation.get("output_height", 0))
    fit = presentation.get("fit")
    if out_w <= 0 or out_h <= 0 or fit not in {"cover", "contain"}:
        audit.add("error", "CAPTURE-PRESENTATION", "invalid output dimensions or fit")
        return

    if fit == "cover":
        scale = max(out_w / width, out_h / height)
        crop_w = out_w / scale
        crop_h = out_h / scale
        crop_x = (width - crop_w) / 2.0
        crop_y = (height - crop_h) / 2.0
    else:
        scale = min(out_w / width, out_h / height)
        crop_w, crop_h, crop_x, crop_y = float(width), float(height), 0.0, 0.0
    audit.facts["presentation"] = {
        "fit": fit,
        "scale": round(scale, 6),
        "source_crop": {
            "x": round(crop_x, 3),
            "y": round(crop_y, 3),
            "width": round(crop_w, 3),
            "height": round(crop_h, 3),
        },
    }
    audit.require(
        scale <= 1.000001,
        "CAPTURE-NO-UPSCALE",
        "Studio presentation does not upscale the source",
        f"presentation would upscale source by {scale:.3f}x",
    )

    focus_required = presentation.get("focus_center_required") is True
    focus = presentation.get("focus_rect")
    if focus_required and not isinstance(focus, dict):
        audit.add("error", "CAPTURE-FOCUS", "focus_center_required needs a game-owned focus_rect")
        return
    if not isinstance(focus, dict):
        return
    try:
        fx = float(focus["x"])
        fy = float(focus["y"])
        fw = float(focus["width"])
        fh = float(focus["height"])
    except (KeyError, TypeError, ValueError):
        audit.add("error", "CAPTURE-FOCUS", "focus_rect must contain numeric x/y/width/height")
        return
    focus_cx, focus_cy = fx + fw / 2.0, fy + fh / 2.0
    crop_cx, crop_cy = crop_x + crop_w / 2.0, crop_y + crop_h / 2.0
    dx = abs(focus_cx - crop_cx) / crop_w
    dy = abs(focus_cy - crop_cy) / crop_h
    tolerance = float(presentation.get("focus_tolerance_ratio", 0.05))
    inside = fx >= crop_x and fy >= crop_y and fx + fw <= crop_x + crop_w and fy + fh <= crop_y + crop_h
    audit.require(
        inside,
        "CAPTURE-FOCUS-VISIBLE",
        "focus rectangle stays inside the centered crop",
        "focus rectangle is clipped by the centered crop",
    )
    audit.require(
        max(dx, dy) <= tolerance,
        "CAPTURE-FOCUS-CENTER",
        f"focus center is within {tolerance:.1%} tolerance",
        f"focus is off-center: dx={dx:.1%}, dy={dy:.1%}, tolerance={tolerance:.1%}",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Validate a gameplay capture before Studio ingest.")
    parser.add_argument("--contract", type=Path, required=True)
    parser.add_argument("--production-root", type=Path, required=True)
    parser.add_argument("--result", type=Path)
    parser.add_argument("--request-id")
    parser.add_argument("--report", type=Path)
    parser.add_argument("--ffprobe", default="ffprobe")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--skip-freeze-scan", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
    audit = Audit()
    try:
        contract = _load_json(args.contract)
        audit.require(
            contract.get("schema") == "devlog.gameplay_capture" and contract.get("version") == 1,
            "CAPTURE-SCHEMA",
            "capture contract schema is valid",
            "capture contract requires schema=devlog.gameplay_capture and version=1",
        )
        request_id = args.request_id or contract.get("request_id")
        if not isinstance(request_id, str) or not request_id:
            raise ValueError("request id is missing")
        result = _result_for(args.result, request_id) if args.result else None
        artifact = _resolve_artifact(contract, args.production_root.resolve(), result)
        audit.facts["artifact"] = str(artifact)
        audit.require(artifact.is_file(), "CAPTURE-FILE", "artifact exists", f"artifact is missing: {artifact}")
        if not artifact.is_file():
            raise ValueError("cannot inspect missing artifact")

        role = contract.get("editorial_role")
        expected_method = contract.get("capture_method")
        audit.require(
            role in {"gameplay", "debug_proof", "presentation"},
            "CAPTURE-ROLE",
            f"editorial role is {role}",
            f"unsupported editorial role: {role!r}",
        )
        audit.require(
            not (role == "gameplay" and expected_method != "realtime_window"),
            "CAPTURE-METHOD-ROLE",
            "gameplay requires a real-time window stream",
            f"gameplay cannot use capture_method={expected_method!r}",
        )

        sidecar_path = artifact.with_suffix(artifact.suffix + ".capture.json")
        sidecar = _load_json(sidecar_path) if sidecar_path.is_file() else {}
        actual_method = sidecar.get("capture_method")
        if not actual_method and result is not None:
            actual_method = _method_from_result(result)
        audit.require(
            isinstance(actual_method, str) and actual_method == expected_method,
            "CAPTURE-METHOD",
            f"actual capture method matches {expected_method}",
            f"actual capture method {actual_method!r} does not match {expected_method!r}",
        )
        if expected_method == "realtime_window":
            audit.require(
                bool(sidecar),
                "CAPTURE-RECORDER-METADATA",
                "real-time recorder metadata exists",
                f"real-time gameplay requires recorder metadata: {sidecar_path}",
            )
            if sidecar:
                audit.require(sidecar.get("client_area") is True, "CAPTURE-CLIENT",
                              "only the client area was recorded", "capture was not proven client-area-only")
                audit.require(sidecar.get("cursor_visible") is False, "CAPTURE-CURSOR",
                              "cursor was excluded", "cursor exclusion was not proven")

        state_id = contract.get("state_id")
        build_id = contract.get("build_id")
        audit.require(isinstance(state_id, str) and bool(state_id), "CAPTURE-STATE-ID",
                      "state id is declared", "state_id is missing")
        audit.require(isinstance(build_id, str) and bool(build_id), "CAPTURE-BUILD-ID",
                      "build id is declared", "build_id is missing")
        actual_state = sidecar.get("state_id") or (result or {}).get("state_id")
        actual_build = sidecar.get("build_id") or (result or {}).get("build_id")
        audit.require(actual_state == state_id, "CAPTURE-STATE-MATCH",
                      "recorded state matches the request",
                      f"recorded state {actual_state!r} != {state_id!r}")
        audit.require(actual_build == build_id, "CAPTURE-BUILD-MATCH",
                      "recorded build matches the request",
                      f"recorded build {actual_build!r} != {build_id!r}")

        ffprobe = shutil.which(args.ffprobe)
        if ffprobe is None:
            raise ValueError(f"ffprobe not found: {args.ffprobe}")
        probe = _probe(artifact, ffprobe)
        audit.facts["probe"] = probe
        width, height = probe["width"], probe["height"]
        orientation = "landscape" if width > height else "vertical" if height > width else "square"
        audit.require(orientation == contract.get("orientation"), "CAPTURE-ORIENTATION",
                      f"orientation is {orientation}",
                      f"orientation {orientation} != {contract.get('orientation')!r}")
        audit.require(width >= int(contract.get("min_width", 0)) and height >= int(contract.get("min_height", 0)),
                      "CAPTURE-RESOLUTION", f"native resolution is {width}x{height}",
                      f"resolution {width}x{height} is below contract")
        audit.require(probe["fps"] + 1e-6 >= float(contract.get("min_fps", 0)),
                      "CAPTURE-FPS", f"frame rate is {probe['fps']:.3f}",
                      f"frame rate {probe['fps']:.3f} is below contract")

        head = float(contract.get("head_handle_seconds", 0))
        tail = float(contract.get("tail_handle_seconds", 0))
        content = float(contract.get("content_seconds", 0))
        audit.require(head >= 5 and tail >= 5, "CAPTURE-HANDLES",
                      f"edit handles are {head:.1f}s / {tail:.1f}s",
                      f"gameplay needs >=5s head and tail handles, got {head:.1f}s / {tail:.1f}s")
        required_duration = head + content + tail
        audit.require(probe["duration"] + 0.05 >= required_duration, "CAPTURE-DURATION",
                      f"duration {probe['duration']:.3f}s covers content and handles",
                      f"duration {probe['duration']:.3f}s < required {required_duration:.3f}s")
        planned = contract.get("planned_use")
        if isinstance(planned, dict):
            start = float(planned.get("start", -1))
            end = float(planned.get("end", -1))
            audit.require(start >= head and end <= probe["duration"] - tail + 0.05 and end > start,
                          "CAPTURE-USE-WINDOW", "planned edit stays inside both handles",
                          f"planned use {start:.3f}-{end:.3f}s consumes a handle")

        audit.require(contract.get("simulation_rate") == 1.0, "CAPTURE-SIM-RATE",
                      "simulation rate is exactly 1x", "editorial gameplay must use simulation_rate=1.0")
        audit.require(contract.get("continuous") is True, "CAPTURE-CONTINUOUS",
                      "continuous take is required", "continuous=true is required")
        audit.require(contract.get("clean_ui") is True, "CAPTURE-CLEAN-UI",
                      "clean UI is required", "clean_ui=true is required")

        if sidecar:
            rect = sidecar.get("client_rect")
            rect_ok = (
                isinstance(rect, dict)
                and rect.get("width") == width
                and rect.get("height") == height
            )
            audit.require(rect_ok, "CAPTURE-RECT",
                          "encoded frame matches the recorded client rectangle",
                          "encoded frame and recorded client rectangle differ")

        _presentation_checks(audit, contract, width, height)

        if contract.get("continuous") is True and not args.skip_freeze_scan:
            ffmpeg = shutil.which(args.ffmpeg)
            if ffmpeg is None:
                raise ValueError(f"ffmpeg not found: {args.ffmpeg}")
            durations = _freeze_durations(artifact, ffmpeg, 1.0)
            longest = max(durations, default=0.0)
            audit.facts["longest_freeze_seconds"] = longest
            audit.require(longest <= 1.05, "CAPTURE-FREEZE",
                          "no freeze longer than 1 second was detected",
                          f"detected a {longest:.3f}s freeze in continuous gameplay")
    except (ValueError, OSError, KeyError, TypeError, json.JSONDecodeError) as exc:
        audit.add("error", "CAPTURE-AUDIT", str(exc))

    payload = {
        "schema": "devlog.gameplay_capture.audit",
        "version": 1,
        "verdict": "pass" if audit.errors == 0 else "block",
        "error_count": audit.errors,
        "facts": audit.facts,
        "checks": audit.checks,
    }
    rendered = json.dumps(payload, ensure_ascii=False, indent=2) + "\n"
    if args.report:
        args.report.parent.mkdir(parents=True, exist_ok=True)
        args.report.write_text(rendered, encoding="utf-8")
    sys.stdout.write(rendered)
    return 0 if audit.errors == 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
