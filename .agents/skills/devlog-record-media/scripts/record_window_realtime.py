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


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record a process window's client area with FFmpeg gdigrab."
    )
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--state-id", required=True)
    parser.add_argument("--build-id", required=True)
    parser.add_argument("--content-seconds", type=float, required=True)
    parser.add_argument("--head-handle", type=float, default=5.0)
    parser.add_argument("--tail-handle", type=float, default=5.0)
    parser.add_argument("--min-width", type=int, default=1920)
    parser.add_argument("--min-height", type=int, default=1080)
    parser.add_argument("--fps", type=int, default=60)
    parser.add_argument("--crf", type=int, default=16)
    parser.add_argument("--preset", default="veryfast")
    parser.add_argument("--ffmpeg", default="ffmpeg")
    parser.add_argument("--no-topmost", action="store_true")
    return parser


def main() -> int:
    args = _parser().parse_args()
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

    started_at = _utc_now()
    made_topmost = False
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
        return_code = process.wait()
        if return_code != 0:
            raise RuntimeError(f"FFmpeg failed with exit code {return_code}; partial kept at {partial}")
    finally:
        if made_topmost:
            try:
                _set_topmost(hwnd, False)
            except RuntimeError as exc:
                print(f"warning: could not release topmost state: {exc}", file=sys.stderr)

    if not partial.is_file() or partial.stat().st_size == 0:
        raise RuntimeError("FFmpeg reported success but produced no capture")
    partial.replace(output)
    ended_at = _utc_now()
    metadata = {
        "schema": "devlog.realtime_window_capture",
        "version": 1,
        "capture_method": "realtime_window",
        "editorial_role": "gameplay",
        "state_id": args.state_id,
        "build_id": actual_build_id,
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
    }
    metadata_path = output.with_suffix(output.suffix + ".capture.json")
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"CAPTURE_OK artifact={output} metadata={metadata_path}", flush=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
