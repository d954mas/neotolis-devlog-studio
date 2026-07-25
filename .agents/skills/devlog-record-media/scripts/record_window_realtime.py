#!/usr/bin/env python3
"""Record a Windows process' visible client area as one real-time MP4 stream."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import time


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _executable_for_pid(pid: int) -> Path:
    if os.name != "nt":
        raise RuntimeError("process executable lookup is Windows-only")
    kernel32 = ctypes.windll.kernel32
    process = kernel32.OpenProcess(0x1000, False, pid)
    if not process:
        raise RuntimeError(f"OpenProcess failed for PID {pid}")
    try:
        capacity = wintypes.DWORD(32768)
        buffer = ctypes.create_unicode_buffer(capacity.value)
        if not kernel32.QueryFullProcessImageNameW(
            process,
            0,
            buffer,
            ctypes.byref(capacity),
        ):
            raise RuntimeError(f"QueryFullProcessImageNameW failed for PID {pid}")
        path = Path(buffer.value).resolve()
        if not path.is_file():
            raise RuntimeError(f"process executable is missing: {path}")
        return path
    finally:
        kernel32.CloseHandle(process)


def _window_for_pid(pid: int) -> tuple[int, str, tuple[int, int, int, int]]:
    if os.name != "nt":
        raise RuntimeError("real-time client-area recording is Windows-only")

    user32 = ctypes.windll.user32
    dwmapi = ctypes.windll.dwmapi
    candidates: list[tuple[int, int, str, tuple[int, int, int, int]]] = []

    enum_proc = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND, wintypes.LPARAM)

    @enum_proc
    def visit(hwnd: int, _lparam: int) -> bool:
        if not user32.IsWindowVisible(hwnd):
            return True
        owner_pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(owner_pid))
        if owner_pid.value != pid:
            return True
        length = user32.GetWindowTextLengthW(hwnd)
        title_buffer = ctypes.create_unicode_buffer(max(1, length + 1))
        user32.GetWindowTextW(hwnd, title_buffer, len(title_buffer))
        rect = wintypes.RECT()
        if not user32.GetClientRect(hwnd, ctypes.byref(rect)):
            return True
        origin = wintypes.POINT(rect.left, rect.top)
        if not user32.ClientToScreen(hwnd, ctypes.byref(origin)):
            return True
        width = rect.right - rect.left
        height = rect.bottom - rect.top
        if width <= 0 or height <= 0:
            return True
        candidates.append(
            (width * height, int(hwnd), title_buffer.value, (origin.x, origin.y, width, height))
        )
        return True

    if not user32.EnumWindows(visit, 0):
        raise RuntimeError("EnumWindows failed")
    if not candidates:
        raise RuntimeError(f"no visible top-level window found for PID {pid}")
    candidates.sort(reverse=True)
    _area, hwnd, title, rect = candidates[0]

    # DWM is touched intentionally so missing desktop composition fails before
    # FFmpeg starts. The client rectangle, not the extended frame, is recorded.
    enabled = wintypes.BOOL()
    if dwmapi.DwmIsCompositionEnabled(ctypes.byref(enabled)) != 0:
        raise RuntimeError("DwmIsCompositionEnabled failed")
    return hwnd, title, rect


def _virtual_desktop() -> tuple[int, int, int, int]:
    user32 = ctypes.windll.user32
    return (
        user32.GetSystemMetrics(76),  # SM_XVIRTUALSCREEN
        user32.GetSystemMetrics(77),  # SM_YVIRTUALSCREEN
        user32.GetSystemMetrics(78),  # SM_CXVIRTUALSCREEN
        user32.GetSystemMetrics(79),  # SM_CYVIRTUALSCREEN
    )


def _set_topmost(hwnd: int, enabled: bool) -> None:
    user32 = ctypes.windll.user32
    insert_after = -1 if enabled else -2  # HWND_TOPMOST / HWND_NOTOPMOST
    flags = 0x0001 | 0x0002 | 0x0010  # NOSIZE | NOMOVE | NOACTIVATE
    if not user32.SetWindowPos(hwnd, insert_after, 0, 0, 0, 0, flags):
        raise RuntimeError("SetWindowPos failed")


class _DevApi:
    def __init__(self, port: int) -> None:
        self._socket = socket.create_connection(("127.0.0.1", port), timeout=5.0)
        self._stream = self._socket.makefile("rwb")
        self._request_id = 1

    def close(self) -> None:
        try:
            self._stream.close()
        finally:
            self._socket.close()

    def result(self, method: str, params: dict | None = None) -> dict:
        request_id = str(self._request_id)
        self._request_id += 1
        payload = {
            "request_id": request_id,
            "method": method,
            "params": params or {},
        }
        self._stream.write(
            (json.dumps(payload, separators=(",", ":")) + "\n").encode("utf-8")
        )
        self._stream.flush()
        raw = self._stream.readline()
        if not raw:
            raise RuntimeError(f"DevAPI closed while calling {method}")
        response = json.loads(raw.decode("utf-8"))
        if not isinstance(response, dict):
            raise RuntimeError(f"invalid DevAPI response for {method}")
        if response.get("error"):
            raise RuntimeError(f"DevAPI {method} failed: {response['error']}")
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"DevAPI {method} returned no object result")
        return result


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record a process window's client area with FFmpeg gdigrab."
    )
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--batch", type=Path)
    parser.add_argument("--request-id")
    parser.add_argument("--results", type=Path)
    parser.add_argument("--production-id")
    parser.add_argument("--output", type=Path)
    parser.add_argument("--production-root", type=Path)
    parser.add_argument("--state-id")
    parser.add_argument("--scene")
    parser.add_argument("--action-id")
    parser.add_argument("--build-id")
    parser.add_argument("--devapi-port", type=int, default=17890)
    parser.add_argument("--content-seconds", type=float)
    parser.add_argument("--head-handle", type=float)
    parser.add_argument("--tail-handle", type=float)
    parser.add_argument("--min-width", type=int)
    parser.add_argument("--min-height", type=int)
    parser.add_argument("--fps", type=int)
    parser.add_argument("--crf", type=int, default=16)
    parser.add_argument("--preset", default="veryfast")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--no-topmost", action="store_true")
    return parser


def _hydrate_from_batch(args: argparse.Namespace) -> str | None:
    if args.batch is None:
        required = (
            "output",
            "production_root",
            "state_id",
            "scene",
            "action_id",
            "build_id",
            "content_seconds",
        )
        missing = [name for name in required if getattr(args, name) in (None, "")]
        if missing:
            raise SystemExit(
                "manual mode requires " + ", ".join(f"--{name.replace('_', '-')}" for name in missing)
            )
        args.head_handle = 5.0 if args.head_handle is None else args.head_handle
        args.tail_handle = 5.0 if args.tail_handle is None else args.tail_handle
        args.min_width = 1920 if args.min_width is None else args.min_width
        args.min_height = 1080 if args.min_height is None else args.min_height
        args.fps = 60 if args.fps is None else args.fps
        return args.production_id
    if not args.request_id:
        raise SystemExit("--batch requires --request-id")
    payload = json.loads(args.batch.resolve().read_text(encoding="utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 2:
        raise SystemExit("capture batch must use version 2")
    requests = payload.get("requests")
    matches = [
        item
        for item in requests or []
        if isinstance(item, dict) and item.get("id") == args.request_id
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"capture batch needs exactly one request {args.request_id!r}"
        )
    task = matches[0]
    if (
        task.get("editorial_role") != "gameplay"
        or task.get("capture_method") != "realtime_window"
    ):
        raise SystemExit("real-time recorder accepts only gameplay requests")
    mappings = {
        "output": Path(str(task.get("target_absolute") or "")),
        "production_root": Path(str(payload.get("production_root") or "")),
        "state_id": task.get("state_id"),
        "scene": task.get("scene"),
        "action_id": task.get("action_id"),
        "build_id": task.get("build_id"),
        "content_seconds": task.get("content_seconds"),
        "head_handle": task.get("head_handle_seconds"),
        "tail_handle": task.get("tail_handle_seconds"),
        "min_width": task.get("min_width"),
        "min_height": task.get("min_height"),
        "fps": round(float(task.get("min_fps", 0))),
    }
    for field, value in mappings.items():
        explicit = getattr(args, field)
        if explicit is not None and explicit != value:
            raise SystemExit(
                f"--{field.replace('_', '-')} contradicts the capture batch"
            )
        setattr(args, field, value)
    if args.results is None:
        args.results = args.production_root / "data" / "plan" / "capture_results.json"
    return str(payload.get("production_id") or "")


def _write_result(
    path: Path,
    *,
    production_id: str,
    request_id: str,
    production_root: Path,
    output: Path,
    artifact_sha: str,
    metadata_path: Path,
    metadata_sha: str,
    game_report_path: Path,
    game_report_sha: str,
    state_id: str,
    build_id: str,
    captured_at: str,
) -> None:
    result = {
        "request_id": request_id,
        "status": "captured",
        "path": output.relative_to(production_root).as_posix(),
        "sha256": artifact_sha,
        "capture_method": "realtime_window",
        "state_id": state_id,
        "build_id": build_id,
        "recorder_metadata_path": metadata_path.relative_to(production_root).as_posix(),
        "recorder_metadata_sha256": metadata_sha,
        "game_report_path": game_report_path.relative_to(production_root).as_posix(),
        "game_report_sha256": game_report_sha,
        "captured_at": captured_at,
    }
    existing: dict = {}
    if path.is_file():
        existing = json.loads(path.read_text(encoding="utf-8"))
        if (
            not isinstance(existing, dict)
            or existing.get("version") != 2
            or existing.get("production_id") != production_id
        ):
            raise RuntimeError("existing capture results belong to another batch")
    results = [
        item
        for item in existing.get("results", [])
        if isinstance(item, dict) and item.get("request_id") != request_id
    ]
    results.append(result)
    results.sort(key=lambda item: str(item.get("request_id", "")))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(
            {
                "version": 2,
                "production_id": production_id,
                "results": results,
            },
            ensure_ascii=False,
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )


def main() -> int:
    args = _parser().parse_args()
    production_id = _hydrate_from_batch(args)
    if min(args.content_seconds, args.head_handle, args.tail_handle) < 0:
        raise SystemExit("durations must be non-negative")
    if args.content_seconds <= 0 or args.fps <= 0:
        raise SystemExit("content seconds and FPS must be positive")
    if args.head_handle < 5 or args.tail_handle < 5:
        raise SystemExit("gameplay requires at least 5 seconds of head and tail handles")

    ffmpeg = shutil.which(args.ffmpeg)
    if ffmpeg is None:
        raise SystemExit(f"FFmpeg not found: {args.ffmpeg}")
    output = args.output.resolve()
    production_root = args.production_root.resolve()
    try:
        output.relative_to((production_root / "data").resolve())
    except ValueError as exc:
        raise SystemExit("output must stay inside <production-root>/data") from exc
    if args.state_id != args.scene:
        raise SystemExit("state-id must equal the game-owned capture scene id")
    if output.suffix.casefold() != ".mp4":
        raise SystemExit("output must use the .mp4 extension")
    if output.exists():
        raise SystemExit(f"refusing to overwrite existing output: {output}")
    output.parent.mkdir(parents=True, exist_ok=True)
    partial = output.with_name(f"{output.stem}.partial{output.suffix}")
    if partial.exists():
        raise SystemExit(f"remove or preserve the previous partial file first: {partial}")

    executable = _executable_for_pid(args.pid)
    executable_sha = _sha256(executable)
    actual_build_id = f"exe-sha256:{executable_sha}"
    if args.build_id != actual_build_id:
        raise SystemExit(
            f"running build mismatch: {actual_build_id} != {args.build_id}"
        )

    hwnd, title, (x, y, width, height) = _window_for_pid(args.pid)
    if width < args.min_width or height < args.min_height:
        raise SystemExit(
            f"client area {width}x{height} is below required "
            f"{args.min_width}x{args.min_height}; do not upscale in post"
        )
    if width % 2 or height % 2:
        raise SystemExit(f"client area must have even dimensions for yuv420p: {width}x{height}")
    vx, vy, vw, vh = _virtual_desktop()
    if x < vx or y < vy or x + width > vx + vw or y + height > vy + vh:
        raise SystemExit(
            f"client area {(x, y, width, height)} is outside visible desktop "
            f"{(vx, vy, vw, vh)}; gdigrab would capture invalid pixels"
        )

    total = args.head_handle + args.content_seconds + args.tail_handle
    command = [
        ffmpeg,
        "-hide_banner",
        "-y",
        "-f",
        "gdigrab",
        "-framerate",
        str(args.fps),
        "-draw_mouse",
        "0",
        "-offset_x",
        str(x),
        "-offset_y",
        str(y),
        "-video_size",
        f"{width}x{height}",
        "-i",
        "desktop",
        "-t",
        f"{total:.3f}",
        "-an",
        "-c:v",
        "libx264",
        "-preset",
        args.preset,
        "-crf",
        str(args.crf),
        "-pix_fmt",
        "yuv420p",
        "-movflags",
        "+faststart",
        str(partial),
    ]

    devapi = _DevApi(args.devapi_port)
    try:
        descriptor = devapi.result(
            "game.capture_scene.describe",
            {"scene": args.scene},
        )
        scene = descriptor.get("scene")
        capabilities = scene.get("capabilities") if isinstance(scene, dict) else None
        actions = scene.get("actions") if isinstance(scene, dict) else None
        if (
            not isinstance(scene, dict)
            or scene.get("id") != args.scene
            or not isinstance(capabilities, dict)
            or capabilities.get("hidesGameUi") is not True
            or capabilities.get("semanticHash") is not True
        ):
            raise RuntimeError("capture scene lacks clean-UI semantic proof")
        if args.action_id not in {
            item.get("id") for item in actions or [] if isinstance(item, dict)
        }:
            raise RuntimeError(
                f"action {args.action_id!r} is absent from capture scene"
            )
        before = devapi.result("game.capture_scene.status")
        if before.get("activeScene") != args.scene or before.get("ready") is not True:
            raise RuntimeError("requested capture scene is not active and ready")
    except Exception:
        devapi.close()
        raise

    started_at = _utc_now()
    monotonic_started = time.monotonic()
    made_topmost = False
    action_result: dict | None = None
    after: dict | None = None
    try:
        if not args.no_topmost:
            _set_topmost(hwnd, True)
            made_topmost = True
        process = subprocess.Popen(command, stdin=subprocess.DEVNULL)
        print(f"RECORDING_STARTED client={width}x{height} total={total:.1f}s", flush=True)
        deadline = time.monotonic() + args.head_handle
        while process.poll() is None and time.monotonic() < deadline:
            remaining = max(0, int(deadline - time.monotonic() + 0.999))
            print(f"ACTION_WINDOW_IN={remaining}", flush=True)
            time.sleep(min(1.0, max(0.05, deadline - time.monotonic())))
        if process.poll() is None:
            print("ACTION_WINDOW_OPEN", flush=True)
            action_result = devapi.result(
                "game.capture_scene.trigger_action",
                {"scene": args.scene, "action": args.action_id, "arguments": {}},
            )
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"FFmpeg failed with exit code {return_code}; partial kept at {partial}")
        after = devapi.result("game.capture_scene.status")
    except Exception:
        if "process" in locals() and process.poll() is None:
            process.terminate()
            try:
                process.wait(timeout=5)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
        raise
    finally:
        if made_topmost:
            try:
                _set_topmost(hwnd, False)
            except RuntimeError as exc:
                print(f"warning: could not release topmost state: {exc}", file=sys.stderr)
        devapi.close()

    if not partial.is_file() or partial.stat().st_size == 0:
        raise RuntimeError("FFmpeg reported success but produced no capture")
    partial.replace(output)
    monotonic_ended = time.monotonic()
    ended_at = _utc_now()
    if action_result is None or after is None:
        raise RuntimeError("capture ended without game action/status evidence")
    game_report = {
        "schema": "devlog.game_capture_report",
        "version": 1,
        "status_endpoint": "game.capture_scene.status",
        "describe_endpoint": "game.capture_scene.describe",
        "action_endpoint": "game.capture_scene.trigger_action",
        "scene_id": args.scene,
        "action_id": args.action_id,
        "build_id": actual_build_id,
        "monotonic_started_seconds": monotonic_started,
        "monotonic_ended_seconds": monotonic_ended,
        "descriptor": descriptor,
        "before": before,
        "action_result": action_result,
        "after": after,
    }
    game_report_path = output.with_suffix(output.suffix + ".game.json")
    game_report_path.write_text(
        json.dumps(game_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    game_report_relative = game_report_path.relative_to(production_root).as_posix()
    game_report_sha = _sha256(game_report_path)
    metadata = {
        "schema": "devlog.realtime_window_capture",
        "version": 1,
        "capture_method": "realtime_window",
        "editorial_role": "gameplay",
        "state_id": args.state_id,
        "build_id": actual_build_id,
        "action_id": args.action_id,
        "executable_path": str(executable),
        "executable_sha256": executable_sha,
        "artifact": str(output),
        "sha256": _sha256(output),
        "pid": args.pid,
        "hwnd": hwnd,
        "window_title": title,
        "client_area": True,
        "cursor_visible": False,
        "client_rect": {"x": x, "y": y, "width": width, "height": height},
        "fps": args.fps,
        "simulation_rate": 1.0,
        "continuous": True,
        "clean_ui": True,
        "content_seconds": args.content_seconds,
        "head_handle_seconds": args.head_handle,
        "tail_handle_seconds": args.tail_handle,
        "requested_total_seconds": total,
        "started_at": started_at,
        "ended_at": ended_at,
        "game_report_path": game_report_relative,
        "game_report_sha256": game_report_sha,
    }
    metadata_path = output.with_suffix(output.suffix + ".capture.json")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metadata_sha = _sha256(metadata_path)
    if args.results is not None:
        if not production_id or not args.request_id:
            raise RuntimeError(
                "writing capture results requires production-id and request-id"
            )
        _write_result(
            args.results.resolve(),
            production_id=production_id,
            request_id=args.request_id,
            production_root=production_root,
            output=output,
            artifact_sha=metadata["sha256"],
            metadata_path=metadata_path,
            metadata_sha=metadata_sha,
            game_report_path=game_report_path,
            game_report_sha=game_report_sha,
            state_id=args.state_id,
            build_id=actual_build_id,
            captured_at=ended_at,
        )
    print(
        f"CAPTURE_OK artifact={output} metadata={metadata_path} "
        f"game_report={game_report_path}"
        + (f" results={args.results.resolve()}" if args.results else ""),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
