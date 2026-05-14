"""Local web server for the devlog recorder + preview tools.

Endpoints:
    GET  /                                  static files from project root
    GET  /api/project                       JSON dump of current Edit (beats + meta)
    GET  /api/list                          list recordings in data/recordings/
    GET  /api/file/<name>                   stream a single recording (for inline player)
    POST /api/save/<name>                   upload a webm/m4a/opus recording
    DELETE /api/file/<name>                 delete a recording

Started via `devlog serve <edit_module>`. Run from project root so static
paths resolve correctly. The Edit object is loaded lazily on /api/project
so the server picks up beats.py edits without restart (for static-served
HTML — recorder/preview pages need a refresh).
"""
from __future__ import annotations
import http.server
import json
import socketserver
import sys
import urllib.parse
from dataclasses import asdict, is_dataclass
from pathlib import Path

from devlog.types import Edit


def _safe_filename(name: str) -> str | None:
    """Reject path traversal, slashes, control chars, length > 200."""
    if not name:
        return None
    if ".." in name or "/" in name or "\\" in name or "\x00" in name:
        return None
    if len(name) > 200:
        return None
    return name


def _edit_to_dict(edit: Edit) -> dict:
    """Serialize an Edit to a JSON-safe dict.

    The frontend (recorder.html, preview.html) reads this to populate its
    BEATS array, replacing the inline const BEATS = [...] of the old setup.
    """
    out = {
        "name": edit.name,
        "design": {
            "resolution": list(edit.design.resolution),
            "fps": edit.design.fps,
        },
        "output": edit.output,
        "order": list(edit.order),
        "beats": {},
    }
    for bid, beat in edit.beats.items():
        # Chunks and scene contain nested dataclasses → asdict handles recursion
        beat_d = {
            "audio": beat.audio,
            "words": beat.words,
            "title": beat.title,
            "vo": beat.vo,
            "stage": beat.stage,
            "face": beat.face,
            "scene": asdict(beat.scene) if beat.scene else None,
            "chunks": [asdict(c) for c in beat.chunks],
        }
        out["beats"][bid] = beat_d
    return out


def build_handler_class(edit: Edit, root: Path):
    """Closure over (edit, root) — needed because Handler is constructed per request."""

    class Handler(http.server.SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(root), **kwargs)

        def log_message(self, fmt, *args):
            msg = fmt % args
            # Trim default noisy logs, keep meaningful ones
            if any(s in msg for s in ["/api/", "GET /web/", "POST", "DELETE"]):
                sys.stderr.write(f"[devlog] {msg}\n")

        def _send_json(self, code: int, obj):
            data = json.dumps(obj, ensure_ascii=False).encode("utf-8")
            self.send_response(code)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Access-Control-Allow-Origin", "*")
            self.end_headers()
            self.wfile.write(data)

        def end_headers(self):
            # Disable caching for HTML/JS so changes propagate immediately during dev
            if self.path.endswith(".html") or self.path.endswith(".js"):
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0")
                self.send_header("Pragma", "no-cache")
                self.send_header("Expires", "0")
            super().end_headers()

        def do_OPTIONS(self):
            self.send_response(204)
            self.send_header("Access-Control-Allow-Origin", "*")
            self.send_header("Access-Control-Allow-Methods", "GET, POST, DELETE, OPTIONS")
            self.send_header("Access-Control-Allow-Headers", "Content-Type")
            self.end_headers()

        def do_GET(self):
            path = urllib.parse.unquote(self.path.split("?", 1)[0])

            # ── /devlog/* serves files from common/devlog/web/ (shared HTML tools) ──
            if path.startswith("/devlog/"):
                rel = path[len("/devlog/"):]
                fp = Path(__file__).parent / rel
                if not fp.is_file():
                    return self._send_json(404, {"error": f"not found: {rel}"})
                self.send_response(200)
                ext = fp.suffix.lower()
                ctype = {".html": "text/html; charset=utf-8",
                         ".js":   "application/javascript; charset=utf-8",
                         ".css":  "text/css; charset=utf-8",
                         ".json": "application/json; charset=utf-8"}.get(ext, "application/octet-stream")
                self.send_header("Content-Type", ctype)
                self.send_header("Content-Length", str(fp.stat().st_size))
                self.send_header("Cache-Control", "no-store, no-cache, must-revalidate")
                self.end_headers()
                self.wfile.write(fp.read_bytes())
                return

            if path == "/api/project":
                return self._send_json(200, _edit_to_dict(edit))

            if path == "/api/feedback":
                fb_path = root / "data" / "review" / "feedback.json"
                if not fb_path.exists():
                    return self._send_json(200, {})
                try:
                    return self._send_json(200, json.loads(fb_path.read_text(encoding="utf-8")))
                except Exception as e:
                    return self._send_json(500, {"error": f"feedback read: {e}"})

            if path == "/api/list":
                rec_dir = root / "data" / "recordings"
                rec_dir.mkdir(parents=True, exist_ok=True)
                files = []
                for f in sorted(rec_dir.iterdir()):
                    if f.is_file() and f.suffix.lower() in (".webm", ".mp4", ".m4a", ".opus", ".ogg"):
                        files.append({
                            "name": f.name,
                            "size": f.stat().st_size,
                            "mtime": int(f.stat().st_mtime * 1000),
                        })
                return self._send_json(200, files)

            if path.startswith("/api/file/"):
                name = _safe_filename(path[len("/api/file/"):])
                if not name:
                    return self._send_json(400, {"error": "bad filename"})
                fp = root / "data" / "recordings" / name
                if not fp.exists():
                    return self._send_json(404, {"error": "not found"})
                self.send_response(200)
                self.send_header("Content-Type", "video/webm" if fp.suffix == ".webm" else "application/octet-stream")
                self.send_header("Content-Length", str(fp.stat().st_size))
                self.send_header("Access-Control-Allow-Origin", "*")
                self.end_headers()
                with open(fp, "rb") as fh:
                    while True:
                        chunk = fh.read(64 * 1024)
                        if not chunk:
                            break
                        self.wfile.write(chunk)
                return

            super().do_GET()

        def do_POST(self):
            path = urllib.parse.unquote(self.path.split("?", 1)[0])

            if path.startswith("/api/feedback/"):
                bid = _safe_filename(path[len("/api/feedback/"):])
                if not bid:
                    return self._send_json(400, {"error": "bad beat id"})
                length = int(self.headers.get("Content-Length", 0))
                try:
                    body = json.loads(self.rfile.read(length).decode("utf-8"))
                except Exception as e:
                    return self._send_json(400, {"error": f"bad json: {e}"})
                fb_path = root / "data" / "review" / "feedback.json"
                fb_path.parent.mkdir(parents=True, exist_ok=True)
                store = {}
                if fb_path.exists():
                    try:
                        store = json.loads(fb_path.read_text(encoding="utf-8"))
                    except Exception:
                        store = {}
                store[bid] = body
                fb_path.write_text(json.dumps(store, ensure_ascii=False, indent=2), encoding="utf-8")
                return self._send_json(200, {"ok": True, "bid": bid})

            if path.startswith("/api/save/"):
                name = _safe_filename(path[len("/api/save/"):])
                if not name:
                    return self._send_json(400, {"error": "bad filename"})
                length = int(self.headers.get("Content-Length", 0))
                if length <= 0 or length > 500 * 1024 * 1024:                # 500 MB upload cap
                    return self._send_json(400, {"error": "bad content length"})
                data = self.rfile.read(length)
                fp = root / "data" / "recordings" / name
                fp.parent.mkdir(parents=True, exist_ok=True)
                fp.write_bytes(data)
                return self._send_json(200, {
                    "ok": True,
                    "name": name,
                    "size": len(data),
                    "path": str(fp.relative_to(root)).replace("\\", "/"),
                })
            self._send_json(404, {"error": "unknown endpoint"})

        def do_DELETE(self):
            path = urllib.parse.unquote(self.path.split("?", 1)[0])
            if path.startswith("/api/file/"):
                name = _safe_filename(path[len("/api/file/"):])
                if not name:
                    return self._send_json(400, {"error": "bad filename"})
                fp = root / "data" / "recordings" / name
                if fp.exists():
                    fp.unlink()
                    return self._send_json(200, {"ok": True})
                return self._send_json(404, {"error": "not found"})
            self._send_json(404, {"error": "unknown endpoint"})

    return Handler


class _ThreadedServer(socketserver.ThreadingMixIn, http.server.HTTPServer):
    daemon_threads = True


def serve(edit: Edit, port: int = 8080) -> None:
    """Start the local server for the given Edit. Blocks until Ctrl+C."""
    root = Path.cwd()
    Handler = build_handler_class(edit, root)
    print(f"Devlog server — edit: {edit.name}")
    print(f"  Root:       {root}")
    print(f"  Recorder:   http://localhost:{port}/devlog/recorder.html")
    print(f"  API:        http://localhost:{port}/api/project")
    print(f"  Custom UI:  http://localhost:{port}/web/<your-page>.html (from project's web/)")
    print(f"")
    print(f"Stop with Ctrl+C")
    try:
        with _ThreadedServer(("127.0.0.1", port), Handler) as srv:
            srv.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped")
