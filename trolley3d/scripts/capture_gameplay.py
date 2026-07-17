"""Reel gameplay capture bot for game-not-a-trolley-problem (Studio copy).

Deterministic frame-stepped capture: MANUAL lockstep mode + a PIPELINED
[capture.frame, time.step{count:2}] pair per frame -> PNG sequence ->
ffmpeg assembles at 30 fps (step_dt is fixed 1/60; count=2 == real time).

Hard-won rules (2026-07-17 session, reel #1):
  * ORIENTATION MATCHES THE REEL (lead feedback): vertical reel => PORTRAIT
    framebuffer AT OR ABOVE the target resolution. Launch small, then
    SetWindowPos with SWP_NOSENDCHANGING resizes the window BEYOND the
    screen (bypasses the WM max-track clamp): client 1080x1920 -> fb
    ~1622x2883 -> lanczos DOWNSCALE to 1080x1920 = supersampled, zero
    upscale. Landscape + center-crop (2.7x upscale) is forbidden; a VQ-RES
    error means re-capture, never ffmpeg pre-crop.
  * Pipeline capture BEFORE step in ONE send: deferred responses resolve only
    on sim frames, so capture-after-step deadlocks in manual-idle.
  * FastFile buffered reads are mandatory: the stock DevApiClient reads the
    socket byte-at-a-time; a dense frame's ~MB response drains seconds and
    trips the engine's 2s send timeout -> connection drop that looks like an
    engine crash (taskboard T0440).
  * Park the window off-screen (SetWindowPos, no activation) immediately
    after connect - a popping window gets minimized/closed by the human.
  * Do NOT re-enter the "game" scene via key "3" at boot (it is the default);
    hide the testbed menu with F1.

Run with the game repo venv:
  C:/projects/game-67-idle/.venv/Scripts/python.exe capture_gameplay.py walker
  C:/projects/game-67-idle/.venv/Scripts/python.exe capture_gameplay.py game

Assemble (supersampled downscale to delivery):
  ffmpeg -framerate 30 -i f_%04d.png -vf "scale=1080:1920:flags=lanczos"          -pix_fmt yuv420p -crf 17 out.mp4
"""
import json
import sys
import time
from pathlib import Path

REPO_ROOT = Path("C:/projects/game-67-idle")
sys.path.insert(0, str(REPO_ROOT / "ai_studio" / "runtime_automation"))
from devapi_client import DevApiError, running_game, write_engine_capture_payload_png  # noqa: E402

GAME = REPO_ROOT / "games" / "private" / "game-not-a-trolley-problem"
EXE = GAME / "build" / "devapi-debug" / "bin" / "game.exe"
OUTROOT = GAME / "tmp" / "captures" / "reel"

FPS = 30
# Launch small, then SetWindowPos with SWP_NOSENDCHANGING resizes the window
# BEYOND the screen (bypasses the WM max-track clamp): client 1080x1920 ->
# framebuffer ~1622x2883 (DPI 1.5x). Downscaled to 1080x1920 at assembly =
# supersampled portrait, zero upscale.
LAUNCH_SIZE = "800x600"
TARGET_W, TARGET_H = 1080, 1920   # client size requested via SetWindowPos
W, H = 1622, 2883                 # resulting fb estimate; wheel/pointer coords


class FastFile:
    """Buffered line I/O over the devapi socket. The stock client uses
    makefile(buffering=0) whose readline() is byte-at-a-time: a ~700KB
    capture response (dense 400-walker frame) drains for ~3.7s, tripping
    the engine's 2s send timeout -> close_client -> EOF mid-capture.
    recv(64KB) chunking reads the same line in ~0.1s."""

    def __init__(self, sock):
        self.sock = sock
        self.buf = b""

    def write(self, data):
        self.sock.sendall(data)
        return len(data)

    def flush(self):
        pass

    def readline(self):
        while b"\n" not in self.buf:
            chunk = self.sock.recv(65536)
            if not chunk:
                line, self.buf = self.buf, b""
                return line
            self.buf += chunk
        line, self.buf = self.buf.split(b"\n", 1)
        return line + b"\n"

    def close(self):
        pass


def key_tap(g, key):
    g.result("input.key", {"key": key, "hold": 2})


def step_and_capture(g, out_path, count=2):
    """MANUAL-mode safe: pipeline capture.frame + time.step in one send, then
    read both responses. capture.frame alone deadlocks in manual-idle (no
    pre-swap ever comes); the queued step provides the frame it resolves on.
    step_dt is fixed at 1/60 (set_fps does not change it), so count=2 gives
    1/30s of sim time per captured frame -> real-time speed at 30fps assembly."""
    rid_cap = str(g.next_request_id)
    rid_step = str(g.next_request_id + 1)
    g.next_request_id += 2
    payload = (
        json.dumps({"request_id": rid_cap, "method": "capture.frame", "params": {}},
                   separators=(",", ":")) + "\n" +
        json.dumps({"request_id": rid_step, "method": "time.step", "params": {"count": count}},
                   separators=(",", ":")) + "\n"
    ).encode("utf-8")
    g.file.write(payload)
    g.file.flush()
    responses = {}
    for _ in range(2):
        line = g.file.readline().decode("utf-8", "replace").strip()
        if not line:
            raise DevApiError("empty response during pipelined step+capture")
        r = json.loads(line)
        responses[str(r.get("request_id"))] = r
    cap = responses.get(rid_cap)
    step = responses.get(rid_step)
    if not cap or cap.get("ok") is not True:
        raise DevApiError(f"pipelined capture failed: {cap}")
    if not step or step.get("ok") is not True:
        raise DevApiError(f"pipelined step failed: {step}")
    write_engine_capture_payload_png(cap["result"], out_path)


def capture_seq(g, name, frames, on_frame=None):
    outdir = OUTROOT / name
    outdir.mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    for i in range(frames):
        if on_frame is not None:
            on_frame(g, i)
        step_and_capture(g, str(outdir / f"f_{i:04d}.png"))
        if i % 30 == 0:
            print(f"{name}: {i}/{frames} ({time.time()-t0:.0f}s)", flush=True)
    print(f"{name}: done {frames} frames in {time.time()-t0:.0f}s -> {outdir}", flush=True)
    return outdir


def enter_scene_clean(g, scene_key, warmup_frames):
    """RUN mode: hide testbed menu, switch scene, let the sim settle."""
    g.result("time.set_mode", {"mode": "run"})
    key_tap(g, scene_key)
    g.wait_frames(warmup_frames)


def to_manual(g):
    g.result("time.set_fps", {"fps": FPS})
    g.result("time.set_mode", {"mode": "manual"})
    # settle: a full non-deferred round-trip between the mode switch and the
    # first pipelined capture+step pair (walker runs always had one; game-mode
    # runs without it die with a closed connection on the first pair)
    g.result("ping")


def zoom_in(g, i, dy=-0.12):
    # slow continuous zoom-in; wheel scrolls AT (x,y) so no prior move needed
    g.result("input.wheel", {"dy": dy, "x": W / 2, "y": H / 2})


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else "smoke"
    OUTROOT.mkdir(parents=True, exist_ok=True)

    with running_game(exe=str(EXE), cwd=str(GAME), window_size=LAUNCH_SIZE) as g:
        g.file.close()
        g.file = FastFile(g.sock)  # buffered reads (see FastFile docstring)
        # Park the window off-screen IMMEDIATELY and WITHOUT activating it:
        # a centred window pops over the user's work and gets closed by hand,
        # which shows up here as a clean engine shutdown mid-capture.
        # capture.frame reads the engine framebuffer pre-swap, so an
        # off-screen (but not minimized) window still captures fine.
        if g.process_id:
            try:
                import ctypes
                from capture_window import find_window_for_pid
                hwnd = find_window_for_pid(g.process_id)
                if hwnd:
                    user32 = ctypes.windll.user32
                    SW_RESTORE = 9
                    user32.ShowWindow(hwnd, SW_RESTORE)

                    class RECT(ctypes.Structure):
                        _fields_ = [("l", ctypes.c_long), ("t", ctypes.c_long),
                                    ("r", ctypes.c_long), ("b", ctypes.c_long)]

                    rect = RECT(0, 0, TARGET_W, TARGET_H)
                    style = user32.GetWindowLongW(hwnd, -16)
                    user32.AdjustWindowRect(ctypes.byref(rect), style, False)
                    ow, oh = rect.r - rect.l, rect.b - rect.t
                    # NOZORDER | NOACTIVATE | NOSENDCHANGING (skips max-track clamp)
                    user32.SetWindowPos(hwnd, 0, 2000, -30, ow, oh, 0x4 | 0x10 | 0x400)
                    print(f"window parked off-screen, outer {ow}x{oh}", flush=True)
            except Exception as e:
                print("window parking failed:", e, flush=True)
        g.wait_frames(30)
        key_tap(g, "F1")  # hide testbed menu
        g.wait_frames(5)

        if mode == "smoke":
            enter_scene_clean(g, "1", 30)
            to_manual(g)
            capture_seq(g, "smoke_zoom", 30, on_frame=lambda gg, i: zoom_in(gg, i))
            print("SMOKE OK")
        elif mode == "walker":
            enter_scene_clean(g, "1", 60)
            to_manual(g)
            capture_seq(g, "walker", 8 * FPS, on_frame=lambda gg, i: zoom_in(gg, i, -0.015))
        elif mode == "game":
            # scene "game" is the boot default; re-entering via key "3" reliably
            # kills the engine right after (pinned-pack re-init bug) - don't.
            g.wait_frames(150)
            to_manual(g)
            capture_seq(g, "game", 12 * FPS)
        else:
            raise SystemExit(f"unknown mode {mode}")


if __name__ == "__main__":
    main()
