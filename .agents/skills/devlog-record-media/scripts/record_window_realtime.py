#!/usr/bin/env python3
"""Record a Windows process' visible client area as one real-time MP4 stream."""

from __future__ import annotations

import argparse
import ctypes
from ctypes import wintypes
from datetime import datetime, timezone
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time


_FINALIZATION_MARGIN_SECONDS = 0.25


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_bundle_api():
    """Load the stdlib-only bundle module without importing services package."""

    bundle_path = (
        Path(__file__).resolve().parents[4]
        / "common"
        / "dlstudio"
        / "src"
        / "dlstudio"
        / "services"
        / "bundle.py"
    )
    if bundle_path.is_file():
        spec = importlib.util.spec_from_file_location(
            "_dlstudio_capture_bundle",
            bundle_path,
        )
        if spec is None or spec.loader is None:
            raise RuntimeError(f"cannot load bundle service: {bundle_path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        return module.promote_bundle, module.recover_bundle_transactions
    try:
        from dlstudio.services.bundle import (
            promote_bundle,
            recover_bundle_transactions,
        )
    except ImportError as exc:
        raise RuntimeError(
            "Studio v2 bundle service is unavailable from this skill checkout"
        ) from exc
    return promote_bundle, recover_bundle_transactions


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


def _listener_pids(port: int) -> set[int]:
    """Return IPv4 listener owners from the Windows TCP owner table."""

    if os.name != "nt":
        raise RuntimeError("DevAPI process ownership check is Windows-only")

    class _TcpRowOwnerPid(ctypes.Structure):
        _fields_ = [
            ("state", wintypes.DWORD),
            ("local_addr", wintypes.DWORD),
            ("local_port", wintypes.DWORD),
            ("remote_addr", wintypes.DWORD),
            ("remote_port", wintypes.DWORD),
            ("owning_pid", wintypes.DWORD),
        ]

    iphlpapi = ctypes.windll.iphlpapi
    size = wintypes.DWORD(0)
    result = iphlpapi.GetExtendedTcpTable(
        None,
        ctypes.byref(size),
        False,
        socket.AF_INET,
        3,  # TCP_TABLE_OWNER_PID_LISTENER
        0,
    )
    if result not in {0, 122}:  # NO_ERROR / ERROR_INSUFFICIENT_BUFFER
        raise RuntimeError(f"GetExtendedTcpTable sizing failed: {result}")
    buffer = ctypes.create_string_buffer(size.value)
    result = iphlpapi.GetExtendedTcpTable(
        buffer,
        ctypes.byref(size),
        False,
        socket.AF_INET,
        3,
        0,
    )
    if result != 0:
        raise RuntimeError(f"GetExtendedTcpTable failed: {result}")
    count = ctypes.cast(buffer, ctypes.POINTER(wintypes.DWORD)).contents.value
    row_size = ctypes.sizeof(_TcpRowOwnerPid)
    base = ctypes.addressof(buffer) + ctypes.sizeof(wintypes.DWORD)
    owners: set[int] = set()
    for index in range(count):
        row = _TcpRowOwnerPid.from_address(base + index * row_size)
        if socket.ntohs(row.local_port & 0xFFFF) == port:
            owners.add(int(row.owning_pid))
    return owners


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
        if response.get("request_id") != request_id:
            raise RuntimeError(
                f"DevAPI {method} returned unexpected request id "
                f"{response.get('request_id')!r}"
            )
        if response.get("ok") is not True:
            raise RuntimeError(
                f"DevAPI {method} failed: {response.get('error', response)}"
            )
        result = response.get("result")
        if not isinstance(result, dict):
            raise RuntimeError(f"DevAPI {method} returned no object result")
        return result


class _FfmpegProgress:
    def __init__(self) -> None:
        self.first_frame = threading.Event()
        self.finished = threading.Event()
        self._lock = threading.Lock()
        self._pts_seconds = 0.0
        self.started_monotonic: float | None = None
        self.ended_monotonic: float | None = None

    @property
    def pts_seconds(self) -> float:
        with self._lock:
            return self._pts_seconds

    @property
    def elapsed_wall_seconds(self) -> float:
        with self._lock:
            started = self.started_monotonic
        return 0.0 if started is None else max(0.0, time.monotonic() - started)

    def consume(self, stream) -> None:
        for raw in stream:
            line = raw.strip()
            key, separator, value = line.partition("=")
            if not separator:
                continue
            if key in {"out_time_us", "out_time_ms"}:
                try:
                    pts = max(0.0, int(value) / 1_000_000.0)
                except ValueError:
                    continue
                with self._lock:
                    self._pts_seconds = max(self._pts_seconds, pts)
                    if self.started_monotonic is None and pts > 0:
                        self.started_monotonic = time.monotonic() - pts
                        self.first_frame.set()
            elif key == "progress" and value == "end":
                self.ended_monotonic = time.monotonic()
                self.finished.set()


def _required_capture_end(
    *,
    action_media_seconds: float | None,
    head_handle_seconds: float,
    content_seconds: float,
    tail_handle_seconds: float,
) -> float:
    if action_media_seconds is None:
        required = head_handle_seconds + content_seconds + tail_handle_seconds
    else:
        required = action_media_seconds + content_seconds + tail_handle_seconds
    # Stop after a small encoder/frame-quantization margin so ingest can keep
    # the requested handles strict instead of silently accepting a short tail.
    return required + _FINALIZATION_MARGIN_SECONDS


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Record a process window's client area with FFmpeg gdigrab."
    )
    parser.add_argument("--pid", type=int, required=True)
    parser.add_argument(
        "--probe-requests",
        type=Path,
        help=(
            "prepare one raw v2 capture request against the running game and "
            "atomically lock its expected semantic hashes; does not record"
        ),
    )
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
    parser.add_argument("--seed", type=int)
    parser.add_argument("--parameters", type=json.loads)
    parser.add_argument("--expected-initial-semantic-hash")
    parser.add_argument("--expected-action-semantic-hash")
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
            "build_id",
            "seed",
            "expected_initial_semantic_hash",
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
        args.parameters = {} if args.parameters is None else args.parameters
        if args.action_id and not args.expected_action_semantic_hash:
            raise SystemExit(
                "manual action capture requires --expected-action-semantic-hash"
            )
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
        "seed": task.get("seed"),
        "parameters": task.get("parameters") or {},
        "expected_initial_semantic_hash": task.get(
            "expected_initial_semantic_hash"
        ),
        "expected_action_semantic_hash": task.get(
            "expected_action_semantic_hash"
        ),
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
        args.results = (
            args.production_root
            / "data"
            / "plan"
            / "capture_results"
            / f"{args.request_id}.json"
        )
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


def _prepare_game_scene(
    devapi: _DevApi,
    *,
    scene_id: str,
    seed: int,
    parameters: dict,
    action_id: str | None,
    trigger_action: bool,
) -> tuple[dict, dict, list[dict], dict, dict | None]:
    descriptor = devapi.result(
        "game.capture_scene.describe",
        {"scene": scene_id},
    )
    scene = descriptor.get("scene")
    capabilities = scene.get("capabilities") if isinstance(scene, dict) else None
    actions = scene.get("actions") if isinstance(scene, dict) else None
    if (
        not isinstance(scene, dict)
        or scene.get("id") != scene_id
        or not isinstance(capabilities, dict)
        or capabilities.get("hidesGameUi") is not True
        or capabilities.get("semanticHash") is not True
    ):
        raise RuntimeError("capture scene lacks clean-UI semantic proof")
    if action_id and action_id not in {
        item.get("id") for item in actions or [] if isinstance(item, dict)
    }:
        raise RuntimeError(f"action {action_id!r} is absent from capture scene")

    load_result = devapi.result(
        "game.capture_scene.load",
        {"scene": scene_id, "seed": seed},
    )
    parameter_results: list[dict] = []
    for parameter, value in parameters.items():
        result = devapi.result(
            "game.capture_scene.set_parameter",
            {
                "scene": scene_id,
                "parameter": parameter,
                "value": value,
            },
        )
        if (
            result.get("parameter") != parameter
            or result.get("value") != value
            or not isinstance(result.get("status"), dict)
        ):
            raise RuntimeError(
                f"capture scene returned invalid parameter result for {parameter}"
            )
        parameter_results.append(result)
    before = devapi.result("game.capture_scene.status")
    if before.get("activeScene") != scene_id or before.get("ready") is not True:
        raise RuntimeError("requested capture scene is not active and ready")
    initial_hash = str(before.get("semanticHash") or "")
    if len(initial_hash) != 8:
        raise RuntimeError("capture scene returned no valid initial semantic hash")

    action_result: dict | None = None
    if trigger_action and action_id:
        action_result = devapi.result(
            "game.capture_scene.trigger_action",
            {"scene": scene_id, "action": action_id, "arguments": {}},
        )
        action_hash = str(action_result.get("semanticHash") or "")
        if len(action_hash) != 8:
            raise RuntimeError("capture scene returned no valid action semantic hash")
    return descriptor, load_result, parameter_results, before, action_result


def _clock_call(
    devapi: _DevApi,
    trace: list[dict],
    method: str,
    params: dict | None = None,
) -> dict:
    normalized_params = params or {}
    result = devapi.result(method, normalized_params)
    trace.append({
        "method": method,
        "params": normalized_params,
        "result": result,
    })
    return result


def _probe_request(args: argparse.Namespace) -> int:
    if args.batch is not None:
        raise SystemExit("--probe-requests cannot be combined with --batch")
    if not args.request_id:
        raise SystemExit("--probe-requests requires --request-id")
    requests_path = args.probe_requests.resolve()
    original = requests_path.read_bytes()
    payload = json.loads(original.decode("utf-8"))
    if not isinstance(payload, dict) or payload.get("version") != 2:
        raise SystemExit("semantic probe requires a version 2 capture request file")
    requests = payload.get("requests")
    matches = [
        item
        for item in requests or []
        if isinstance(item, dict) and item.get("id") == args.request_id
    ]
    if len(matches) != 1:
        raise SystemExit(
            f"capture requests need exactly one request {args.request_id!r}"
        )
    request = matches[0]
    if (
        request.get("editorial_role") != "gameplay"
        or request.get("capture_method") != "realtime_window"
    ):
        raise SystemExit("semantic probe accepts only real-time gameplay requests")
    scene_id = request.get("scene")
    if not isinstance(scene_id, str) or request.get("state_id") != scene_id:
        raise SystemExit("gameplay probe requires scene == state_id")
    seed = request.get("seed")
    if not isinstance(seed, int) or isinstance(seed, bool) or not 0 <= seed <= 0xFFFFFFFF:
        raise SystemExit("gameplay probe requires a uint32 seed")
    parameters = request.get("parameters") or {}
    if not isinstance(parameters, dict):
        raise SystemExit("gameplay probe parameters must be an object")
    action_id = request.get("action_id")
    if action_id is not None and not isinstance(action_id, str):
        raise SystemExit("gameplay probe action_id must be a string or null")

    executable = _executable_for_pid(args.pid)
    actual_build_id = f"exe-sha256:{_sha256(executable)}"
    if request.get("build_id") != actual_build_id:
        raise SystemExit(
            f"running build mismatch: {actual_build_id} != {request.get('build_id')}"
        )
    listener_pids = _listener_pids(args.devapi_port)
    if listener_pids != {args.pid}:
        raise RuntimeError(
            f"DevAPI port {args.devapi_port} belongs to {sorted(listener_pids)}, "
            f"not probed PID {args.pid}"
        )

    devapi = _DevApi(args.devapi_port)
    clock_trace: list[dict] = []
    try:
        _clock_call(devapi, clock_trace, "time.set_mode", {"mode": "manual"})
        _clock_call(devapi, clock_trace, "time.pause")
        _clock_call(devapi, clock_trace, "time.set_scale", {"scale": 1.0})
        _descriptor, _load, _parameters, before, action_result = (
            _prepare_game_scene(
                devapi,
                scene_id=scene_id,
                seed=seed,
                parameters=parameters,
                action_id=action_id,
                trigger_action=True,
            )
        )
    finally:
        try:
            _clock_call(devapi, clock_trace, "time.set_mode", {"mode": "run"})
            _clock_call(devapi, clock_trace, "time.set_scale", {"scale": 1.0})
            _clock_call(devapi, clock_trace, "time.resume")
        finally:
            devapi.close()
    request["expected_initial_semantic_hash"] = str(before["semanticHash"]).lower()
    request["expected_action_semantic_hash"] = (
        str(action_result["semanticHash"]).lower()
        if action_result is not None
        else None
    )
    if (
        action_result is not None
        and request["expected_action_semantic_hash"]
        == request["expected_initial_semantic_hash"]
    ):
        raise RuntimeError(
            "game-owned action did not change semantic state during probe"
        )

    if requests_path.read_bytes() != original:
        raise RuntimeError(
            "capture requests changed during the semantic probe; retry on the new file"
        )
    temporary = requests_path.with_name(
        f".{requests_path.name}.{os.getpid()}.probe.tmp"
    )
    try:
        with temporary.open("w", encoding="utf-8", newline="\n") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, requests_path)
    finally:
        if temporary.exists():
            temporary.unlink()
    print(
        "PROBE_OK "
        f"request={args.request_id} "
        f"initial={request['expected_initial_semantic_hash']} "
        f"action={request['expected_action_semantic_hash'] or 'passive'}",
        flush=True,
    )
    return 0


def main() -> int:
    args = _parser().parse_args()
    if args.probe_requests is not None:
        return _probe_request(args)
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
        promote_bundle, recover_bundle_transactions = _load_bundle_api()
    except RuntimeError as exc:
        raise SystemExit(
            "Studio v2 environment is required for crash-safe capture promotion"
        ) from exc
    recover_bundle_transactions(production_root / "data")
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
        archive = (
            production_root
            / "data"
            / "recordings"
            / "incomplete"
            / datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
        )
        archive.mkdir(parents=True, exist_ok=False)
        for staged in (
            partial,
            partial.with_suffix(partial.suffix + ".game.json"),
            partial.with_suffix(partial.suffix + ".capture.json"),
        ):
            if staged.exists():
                os.replace(staged, archive / staged.name)
        print(f"RECOVERED_INCOMPLETE_CAPTURE archive={archive}", flush=True)

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
        "-nostats",
        "-progress",
        "pipe:1",
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

    listener_pids = _listener_pids(args.devapi_port)
    if listener_pids != {args.pid}:
        raise RuntimeError(
            f"DevAPI port {args.devapi_port} belongs to {sorted(listener_pids)}, "
            f"not recorded PID {args.pid}"
        )
    devapi = _DevApi(args.devapi_port)
    clock_trace: list[dict] = []
    try:
        _clock_call(devapi, clock_trace, "time.set_mode", {"mode": "manual"})
        _clock_call(devapi, clock_trace, "time.pause")
        _clock_call(devapi, clock_trace, "time.set_scale", {"scale": 1.0})
        descriptor, load_result, parameter_results, before, _unused_action = (
            _prepare_game_scene(
                devapi,
                scene_id=args.scene,
                seed=args.seed,
                parameters=args.parameters,
                action_id=args.action_id,
                trigger_action=False,
            )
        )
        if (
            str(before.get("semanticHash") or "").casefold()
            != args.expected_initial_semantic_hash.casefold()
        ):
            raise RuntimeError(
                "prepared capture scene semantic hash differs from the batch"
            )
        _clock_call(devapi, clock_trace, "time.set_mode", {"mode": "run"})
        _clock_call(devapi, clock_trace, "time.set_scale", {"scale": 1.0})
        _clock_call(devapi, clock_trace, "time.resume")
    except Exception:
        devapi.close()
        raise

    started_at = _utc_now()
    made_topmost = False
    pre_action: dict | None = None
    action_result: dict | None = None
    action_media_seconds: float | None = None
    after: dict | None = None
    try:
        if not args.no_topmost:
            _set_topmost(hwnd, True)
            made_topmost = True
        process = subprocess.Popen(
            command,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=None,
            text=True,
            encoding="utf-8",
            errors="replace",
        )
        if process.stdout is None:
            raise RuntimeError("FFmpeg progress pipe was not created")
        progress = _FfmpegProgress()
        progress_thread = threading.Thread(
            target=progress.consume,
            args=(process.stdout,),
            daemon=True,
        )
        progress_thread.start()
        print(f"RECORDING_STARTED client={width}x{height} total={total:.1f}s", flush=True)
        if not progress.first_frame.wait(timeout=10):
            raise RuntimeError("FFmpeg produced no first-frame progress")
        watchdog = time.monotonic() + total + 15.0
        while (
            process.poll() is None
            and progress.elapsed_wall_seconds < args.head_handle
        ):
            if time.monotonic() >= watchdog:
                raise RuntimeError("FFmpeg capture timed out before the action window")
            remaining = max(
                0,
                int(args.head_handle - progress.elapsed_wall_seconds + 0.999),
            )
            print(f"ACTION_WINDOW_IN={remaining}", flush=True)
            time.sleep(0.1)
        if process.poll() is None:
            print("ACTION_WINDOW_OPEN", flush=True)
            if args.action_id:
                _clock_call(devapi, clock_trace, "time.pause")
                try:
                    pre_action = devapi.result("game.capture_scene.status")
                    action_result = devapi.result(
                        "game.capture_scene.trigger_action",
                        {
                            "scene": args.scene,
                            "action": args.action_id,
                            "arguments": {},
                        },
                    )
                finally:
                    _clock_call(devapi, clock_trace, "time.resume")
                # Timestamp after the synchronous action response. This is
                # conservative: API latency cannot be miscounted as tail.
                action_media_seconds = progress.elapsed_wall_seconds
                if len(str(action_result.get("semanticHash") or "")) != 8:
                    raise RuntimeError(
                        "capture action returned no valid semantic hash"
                    )
            else:
                action_result = None
        target_end = _required_capture_end(
            action_media_seconds=action_media_seconds,
            head_handle_seconds=args.head_handle,
            content_seconds=args.content_seconds,
            tail_handle_seconds=args.tail_handle,
        )
        watchdog = time.monotonic() + max(
            15.0,
            target_end - progress.elapsed_wall_seconds + 15.0,
        )
        while (
            process.poll() is None
            and progress.elapsed_wall_seconds < target_end
        ):
            if time.monotonic() >= watchdog:
                raise RuntimeError("FFmpeg capture exceeded its tail watchdog")
            time.sleep(0.05)
        if process.poll() is not None:
            raise RuntimeError("FFmpeg ended before the required tail handle")
        if process.stdin is None:
            raise RuntimeError("FFmpeg control pipe was not created")
        process.stdin.write("q\n")
        process.stdin.flush()
        try:
            return_code = process.wait(timeout=15.0)
        except subprocess.TimeoutExpired as exc:
            raise RuntimeError("FFmpeg did not finalize after capture") from exc
        progress_thread.join(timeout=5)
        if return_code != 0:
            raise RuntimeError(f"FFmpeg failed with exit code {return_code}; partial kept at {partial}")
        if not progress.finished.is_set():
            raise RuntimeError("FFmpeg ended without final progress evidence")
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
    ended_at = _utc_now()
    if after is None:
        raise RuntimeError("capture ended without final game status evidence")
    if progress.started_monotonic is None or progress.ended_monotonic is None:
        raise RuntimeError("capture ended without monotonic FFmpeg timing")
    game_report = {
        "schema": "devlog.game_capture_report",
        "version": 1,
        "status_endpoint": "game.capture_scene.status",
        "describe_endpoint": "game.capture_scene.describe",
        "load_endpoint": "game.capture_scene.load",
        "parameter_endpoint": "game.capture_scene.set_parameter",
        "action_endpoint": (
            "game.capture_scene.trigger_action" if args.action_id else None
        ),
        "scene_id": args.scene,
        "action_id": args.action_id,
        "build_id": actual_build_id,
        "process_id": args.pid,
        "seed": args.seed,
        "parameters": args.parameters,
        "expected_initial_semantic_hash": args.expected_initial_semantic_hash,
        "expected_action_semantic_hash": args.expected_action_semantic_hash,
        "monotonic_started_seconds": progress.started_monotonic,
        "monotonic_ended_seconds": progress.ended_monotonic,
        "encoded_duration_seconds": progress.pts_seconds,
        "action_media_seconds": action_media_seconds,
        "clock_trace": clock_trace,
        "descriptor": descriptor,
        "load_result": load_result,
        "parameter_results": parameter_results,
        "before": before,
        "pre_action": pre_action,
        "action_result": action_result,
        "after": after,
    }
    artifact_sha = _sha256(partial)
    game_report_path = output.with_suffix(output.suffix + ".game.json")
    game_report_staging = partial.with_suffix(partial.suffix + ".game.json")
    game_report_staging.write_text(
        json.dumps(game_report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    game_report_relative = game_report_path.relative_to(production_root).as_posix()
    game_report_sha = _sha256(game_report_staging)
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
        "sha256": artifact_sha,
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
    metadata_staging = partial.with_suffix(partial.suffix + ".capture.json")
    metadata_staging.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    metadata_sha = _sha256(metadata_staging)
    replacements = [
        (game_report_staging, game_report_path),
        (metadata_staging, metadata_path),
        (partial, output),
    ]
    if args.results is not None:
        if not production_id or not args.request_id:
            raise RuntimeError(
                "writing capture results requires production-id and request-id"
            )
        results_path = args.results.resolve()
        results_staging = results_path.with_name(
            f".{results_path.name}.{os.getpid()}.staged"
        )
        _write_result(
            results_staging,
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
        replacements.append((results_staging, results_path))
    promote_bundle(replacements)
    print(
        f"CAPTURE_OK artifact={output} metadata={metadata_path} "
        f"game_report={game_report_path}"
        + (f" results={args.results.resolve()}" if args.results else ""),
        flush=True,
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
