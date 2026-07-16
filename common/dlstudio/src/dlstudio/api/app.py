"""FastAPI app factory for Studio v2.

`create_app(edit_module)` loads the edit via the shared CLI loader (which
chdirs into the project root so beats.py's relative paths resolve), then
wires the typed REST surface the Vite/TS webui codes against. The whole
surface is frozen (see the route docstrings / docs/ARCHITECTURE_V2.md); the
webui generates its TypeScript types from this app's OpenAPI schema.

Everything under the studio extra (fastapi/uvicorn) is imported here, so the
CLI can lazy-import `create_app` behind a clear "install [studio]" error.

The server binds 127.0.0.1 only (see cli.cmd_studio); CORS is permissive so
the Vite dev server on another localhost port can talk to it in `--dev`.
"""
from __future__ import annotations

import importlib
import json
import re
import shutil
import sys
import threading
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from dlstudio.check import run_checks
from dlstudio.compile import build_timeline

from .jobs import JobManager
from .paths import safe_component, safe_join

_STATIC_DIR = Path(__file__).parent / "static"

# Upload/feedback safety limits (single-user localhost studio, but a runaway
# recorder or a hostile client must not exhaust RAM/disk).
_MAX_UPLOAD_BYTES = 500 * 1024 * 1024      # 500 MB cap on a recorded take
_UPLOAD_CHUNK_BYTES = 1024 * 1024          # stream to disk 1 MB at a time
_MAX_FEEDBACK_BYTES = 1024 * 1024          # 1 MB cap on a feedback POST body
_MAX_MERGE_DEPTH = 32                      # recursion bound for _deep_merge

# CORS: only the Vite dev server (another localhost origin) needs cross-origin
# access; same-origin production (the built UI served by this app) needs none.
# `vite.config.ts` pins the dev server to 5175 (falling back off 5173), so
# both are allowlisted; wildcard "*" is deliberately NOT used.
_DEV_ORIGINS = [
    "http://localhost:5173", "http://127.0.0.1:5173",
    "http://localhost:5175", "http://127.0.0.1:5175",
]

_PLACEHOLDER_HTML = """<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Studio v2</title>
<style>
  body{font-family:system-ui,sans-serif;background:#101018;color:#e8e8f0;
       margin:0;display:flex;min-height:100vh;align-items:center;justify-content:center}
  main{max-width:34rem;padding:2rem;text-align:center}
  code{background:#1e1e2a;padding:.15rem .4rem;border-radius:.3rem}
  h1{font-size:1.4rem;margin:0 0 .8rem}
  p{color:#aab;line-height:1.5}
</style></head><body><main>
  <h1>Studio v2 backend is running</h1>
  <p>The web UI has not been built yet. Build it into
     <code>dlstudio/api/static/</code>, or run the Vite dev server
     (<code>dl2 studio --dev</code>) and load its URL.</p>
  <p>The API is live at <code>/api/project</code>,
     <code>/api/ir</code>, <code>/api/check</code>.</p>
</main></body></html>
"""


# ─── typed response models (feed the OpenAPI -> TS type generation) ──────────

class DesignInfo(BaseModel):
    resolution: tuple[int, int]
    fps: int


class BeatInfo(BaseModel):
    id: str
    title: str | None = None
    vo: str | None = None
    stage: str | None = None
    face: str
    duration: float | None = None
    n_chunks: int
    audio: str
    words: str
    rendered: bool


class ProjectInfo(BaseModel):
    edit_name: str
    output: str
    design: DesignInfo
    beats: list[BeatInfo]


# ─── small helpers ───────────────────────────────────────────────────────────

def _rel(root: Path, p: Path) -> str:
    """Project-root-relative posix path (what the API hands back to clients)."""
    try:
        return p.resolve().relative_to(root.resolve()).as_posix()
    except ValueError:
        return p.as_posix()


def _safe_ext(filename: str | None) -> str:
    """A sane lower-case file extension from an uploaded filename, else the
    recorder default `.webm`. Guards against a hostile/absent name (the
    extension is the only part of the client filename we keep — the stored
    name is `<beat_id>_<timestamp><ext>`)."""
    if filename:
        suffix = Path(filename).suffix.lower()
        if re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
            return suffix
    return ".webm"


class _MergeTooDeep(ValueError):
    """Raised when `_deep_merge` recurses past `_MAX_MERGE_DEPTH` — a guard
    against a hostile/degenerate deeply-nested feedback body blowing the
    Python recursion stack."""


def _deep_merge(base: dict, incoming: dict, _depth: int = 0) -> dict:
    """Recursively merge `incoming` into `base` (both dicts). Nested dicts
    merge key-by-key; every other value (including lists) is replaced by the
    incoming value. Returns a new dict; inputs are not mutated.

    Recursion is bounded by `_MAX_MERGE_DEPTH`; exceeding it raises
    `_MergeTooDeep` (the endpoint turns that into a 400)."""
    if _depth > _MAX_MERGE_DEPTH:
        raise _MergeTooDeep(f"feedback nesting exceeds {_MAX_MERGE_DEPTH} levels")
    out = dict(base)
    for k, v in incoming.items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v, _depth + 1)
        else:
            out[k] = v
    return out


# ─── long-running job bodies (run on the executor, off the request thread) ───

def _process_take_job(
    edit, root: Path, beat_id: str, recording: Path,
    language: str | None, model: str | None,
) -> dict:
    """VO take -> loudness-normalized wav + word-timed transcript.

    Mirrors `dl2 audio` (cmd_audio): the processed wav + words.json are
    written to the beat's OWN declared `beat.audio` / `beat.words` paths, not
    a fixed `<id>_vo.wav` convention. That is what makes a subsequent render
    (and the UI's audio/karaoke) actually see the new take — the render cache
    keys off the asset the beat's chunks reference. Paths are resolved under
    `root` with the same containment guard as `GET /api/file`."""
    from dlstudio import services

    beat = edit.beats[beat_id]
    audio_out = safe_join(root, beat.audio)
    words_out = safe_join(root, beat.words)
    if audio_out is None or words_out is None:
        raise ValueError(
            f"beat {beat_id!r} declares an audio/words path outside the project "
            f"root (audio={beat.audio!r}, words={beat.words!r})"
        )
    audio_out.parent.mkdir(parents=True, exist_ok=True)
    words_out.parent.mkdir(parents=True, exist_ok=True)
    result = services.process_take(recording, audio_out)
    kwargs: dict = {}
    if language:
        kwargs["language"] = language
    if model:
        kwargs["model"] = model
    services.transcribe(audio_out, words_out, **kwargs)
    return {
        "audio": _rel(root, audio_out),
        "words": _rel(root, words_out),
        "measured_lufs": result.input_i,
        "duration": result.duration,
    }


def _render_beat_job(
    edit, root: Path, render_lock, beat_id: str,
    width: str | int | None, quality: str | None,
) -> dict:
    """Same code path as `dl2 compose`: compile -> resolver -> cache ->
    render_beat, in-process. Returns {output}. `render_lock` serializes the
    module-global chunk resolver against concurrent render jobs."""
    from dlstudio import cache as dl_cache
    from dlstudio import compile as dl_compile
    from dlstudio import render as dl_render
    from dlstudio.cli import _resize_design
    from dlstudio.render import beat as render_beat_mod

    timeline = dl_compile.build_timeline(edit)
    beat = next((b for b in timeline.beats if b.id == beat_id), None)
    if beat is None:
        raise ValueError(
            f"beat {beat_id!r} not in edit {edit.name!r}; "
            f"available: {[b.id for b in timeline.beats]}"
        )

    design = _resize_design(timeline.design, width)
    width_px = design.resolution[0]
    quality = quality or "standard"

    out_dir = root / "data" / "finalize"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{beat_id}.mp4"

    key = dl_cache.beat_key(beat, design, quality=quality, width=width_px, gpu=False)
    if dl_cache.get(key, out_path):
        return {"output": _rel(root, out_path)}

    with render_lock:
        render_beat_mod.set_chunk_resolver(lambda bid, ci: edit.beats[bid].chunks[ci])
        try:
            opts = dl_render.RenderOpts(
                width=width_px, quality=quality, gpu=False, workdir=out_dir)
            rendered = Path(dl_render.render_beat(beat, design, None, opts))
        finally:
            render_beat_mod.set_chunk_resolver(None)

    dl_cache.put(key, rendered)
    if rendered != out_path:
        shutil.copyfile(rendered, out_path)
    return {"output": _rel(root, out_path)}


# ─── app factory ─────────────────────────────────────────────────────────────

def create_app(edit_module: str) -> FastAPI:
    """Build the Studio FastAPI app for the dotted `edit_module`.

    Loading the edit chdirs the process into the project root (via the shared
    CLI loader); `root` below is that absolute root, used for every file
    operation so the endpoints never depend on cwd staying put."""
    from dlstudio.cli import load_edit

    edit, root = load_edit(edit_module)
    jobs = JobManager()
    render_lock = threading.Lock()

    # ── hot-reload: pick up beats.py edits without a server restart ───────────
    # The legacy recorder (common/devlog/web/serve.py `_reload_edit`) reloaded
    # the edit package per request so beats.py changes appeared live. We do the
    # same, but gate it on an mtime/size fast-path so an unchanged project is a
    # cheap stat, not a module reload, on every read.
    #
    # `_state["edit"]` is the live edit; the read endpoints and job submitters
    # go through `_current_edit()` so they always see the latest beats.
    _state: dict = {"edit": edit, "sig": None}

    def _edit_module_files() -> list[Path]:
        """Source files whose change should trigger a reload: the edit module
        itself plus its conventional `.beats` / `.design` submodules (real
        edits compose EDIT from those; the test fixtures inline it in
        __init__)."""
        files: list[Path] = []
        for name in (edit_module, f"{edit_module}.beats", f"{edit_module}.design"):
            mod = sys.modules.get(name)
            fp = getattr(mod, "__file__", None) if mod is not None else None
            if fp:
                files.append(Path(fp))
        return files

    def _mtime_sig() -> tuple:
        sig: list[tuple[str, int, int]] = []
        for fp in _edit_module_files():
            try:
                st = fp.stat()
            except OSError:
                continue
            sig.append((str(fp), st.st_mtime_ns, st.st_size))
        return tuple(sig)

    def _reload_edit_module():
        """Reload `.design`/`.beats` (if imported) then the edit module, in
        that order, so `from .beats import ...` in the edit __init__ rebinds
        the fresh objects. Mirrors legacy `_reload_edit` ordering."""
        importlib.invalidate_caches()
        for name in (f"{edit_module}.design", f"{edit_module}.beats"):
            if name in sys.modules:
                importlib.reload(sys.modules[name])
        if edit_module in sys.modules:
            mod = importlib.reload(sys.modules[edit_module])
        else:
            mod = importlib.import_module(edit_module)
        return mod.EDIT

    def _current_edit():
        """Return the live edit, reloading the module chain only when one of
        its source files changed (mtime or size)."""
        sig = _mtime_sig()
        if _state["edit"] is not None and sig == _state["sig"]:
            return _state["edit"]
        new_edit = _reload_edit_module()
        _state["edit"] = new_edit
        _state["sig"] = _mtime_sig()
        app.state.edit = new_edit
        return new_edit

    _state["sig"] = _mtime_sig()

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        jobs.shutdown()

    app = FastAPI(title="Studio v2", version="2.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=_DEV_ORIGINS, allow_methods=["*"], allow_headers=["*"],
    )
    app.state.edit = edit
    app.state.root = root
    app.state.jobs = jobs

    def _feedback_path() -> Path:
        return root / "data" / "review" / "feedback.json"

    # ── GET /api/project ─────────────────────────────────────────────────────
    @app.get("/api/project", response_model=ProjectInfo)
    def get_project() -> ProjectInfo:
        # Durations come from the compiled Timeline; a project mid-recording
        # may not compile yet (a beat with no audio), so fall back to
        # duration=None per beat rather than failing the whole listing.
        edit = _current_edit()
        dur_map: dict[str, float] = {}
        try:
            timeline = build_timeline(edit)
            dur_map = {b.id: b.duration for b in timeline.beats}
        except Exception:  # noqa: BLE001 — best-effort durations
            dur_map = {}

        beats: list[BeatInfo] = []
        for bid in edit.order:
            b = edit.beats[bid]
            beats.append(BeatInfo(
                id=bid, title=b.title, vo=b.vo, stage=b.stage, face=b.face,
                duration=dur_map.get(bid), n_chunks=len(b.chunks),
                audio=b.audio, words=b.words,
                rendered=(root / "data" / "finalize" / f"{bid}.mp4").is_file(),
            ))
        return ProjectInfo(
            edit_name=edit.name, output=edit.output,
            design=DesignInfo(resolution=edit.design.resolution, fps=edit.design.fps),
            beats=beats,
        )

    # ── GET /api/ir ──────────────────────────────────────────────────────────
    @app.get("/api/ir")
    def get_ir() -> JSONResponse:
        timeline = build_timeline(_current_edit())
        return JSONResponse(timeline.model_dump(mode="json"))

    # ── GET /api/check ───────────────────────────────────────────────────────
    @app.get("/api/check")
    def get_check() -> JSONResponse:
        timeline = build_timeline(_current_edit())
        report = run_checks(timeline)
        return JSONResponse(report.model_dump(mode="json"))

    # ── GET/POST /api/feedback ───────────────────────────────────────────────
    @app.get("/api/feedback")
    def get_feedback() -> JSONResponse:
        fb = _feedback_path()
        if not fb.exists():
            return JSONResponse({})
        try:
            return JSONResponse(json.loads(fb.read_text(encoding="utf-8")))
        except (json.JSONDecodeError, OSError):
            return JSONResponse({})

    @app.post("/api/feedback")
    async def post_feedback(request: Request) -> JSONResponse:
        raw = await request.body()
        if len(raw) > _MAX_FEEDBACK_BYTES:
            raise HTTPException(status_code=413, detail="feedback body too large")
        try:
            incoming = json.loads(raw)
        except Exception:  # noqa: BLE001
            raise HTTPException(status_code=400, detail="body is not valid JSON")
        if not isinstance(incoming, dict):
            raise HTTPException(status_code=400, detail="feedback body must be a JSON object")

        fb = _feedback_path()
        store: dict = {}
        if fb.exists():
            try:
                loaded = json.loads(fb.read_text(encoding="utf-8"))
                if isinstance(loaded, dict):
                    store = loaded
            except (json.JSONDecodeError, OSError):
                store = {}
        try:
            merged = _deep_merge(store, incoming)
        except _MergeTooDeep as e:
            raise HTTPException(status_code=400, detail=str(e))
        fb.parent.mkdir(parents=True, exist_ok=True)
        fb.write_text(json.dumps(merged, ensure_ascii=False, indent=2), encoding="utf-8")
        return JSONResponse(merged)

    # ── POST /api/takes/{beat_id} ────────────────────────────────────────────
    @app.post("/api/takes/{beat_id}")
    async def upload_take(beat_id: str, file: UploadFile = File(...)) -> dict:
        bid = safe_component(beat_id)
        if bid is None:
            raise HTTPException(status_code=400, detail="bad beat id")
        ext = _safe_ext(file.filename)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        rec_dir = root / "data" / "recordings"
        rec_dir.mkdir(parents=True, exist_ok=True)
        dest = rec_dir / f"{bid}_{ts}{ext}"

        # Stream to disk in bounded chunks: never hold the whole take in RAM,
        # enforce a hard size cap, and reject an empty upload.
        total = 0
        over_cap = False
        with dest.open("wb") as fh:
            while True:
                chunk = await file.read(_UPLOAD_CHUNK_BYTES)
                if not chunk:
                    break
                total += len(chunk)
                if total > _MAX_UPLOAD_BYTES:
                    over_cap = True
                    break
                fh.write(chunk)
        if over_cap:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail="upload exceeds 500MB limit")
        if total == 0:
            dest.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="empty upload")
        return {"path": _rel(root, dest)}

    # ── POST /api/actions/process-take ───────────────────────────────────────
    @app.post("/api/actions/process-take")
    async def process_take_action(request: Request) -> dict:
        body = await _json_object(request)
        beat_id = safe_component(str(body.get("beat_id", "")))
        if beat_id is None:
            raise HTTPException(status_code=400, detail="bad or missing beat_id")
        edit = _current_edit()
        if beat_id not in edit.beats:
            raise HTTPException(status_code=404, detail=f"unknown beat: {beat_id}")
        rec_rel = body.get("recording_path")
        if not rec_rel:
            raise HTTPException(status_code=400, detail="recording_path is required")
        recording = safe_join(root, str(rec_rel))
        if recording is None:
            raise HTTPException(status_code=400, detail="recording_path escapes project root")
        if not recording.is_file():
            raise HTTPException(status_code=404, detail=f"recording not found: {rec_rel}")
        job_id = jobs.submit(
            _process_take_job, edit, root, beat_id, recording,
            body.get("language"), body.get("model"),
        )
        return {"job_id": job_id}

    # ── POST /api/actions/render-beat ────────────────────────────────────────
    @app.post("/api/actions/render-beat")
    async def render_beat_action(request: Request) -> dict:
        body = await _json_object(request)
        beat_id = safe_component(str(body.get("beat_id", "")))
        if beat_id is None:
            raise HTTPException(status_code=400, detail="bad or missing beat_id")
        edit = _current_edit()
        if beat_id not in edit.beats:
            raise HTTPException(status_code=404, detail=f"unknown beat: {beat_id}")
        job_id = jobs.submit(
            _render_beat_job, edit, root, render_lock, beat_id,
            body.get("width"), body.get("quality"),
        )
        return {"job_id": job_id}

    # ── GET /api/jobs/{id} ───────────────────────────────────────────────────
    @app.get("/api/jobs/{job_id}")
    def get_job(job_id: str) -> JSONResponse:
        job = jobs.get(job_id)
        if job is None:
            raise HTTPException(status_code=404, detail="unknown job")
        return JSONResponse(job)

    # ── GET /api/file?path=... ───────────────────────────────────────────────
    @app.get("/api/file")
    def get_file(path: str) -> FileResponse:
        # safe_join guarantees the path stays under the project root; we
        # further restrict serving to the data/ subtree so source files
        # (beats.py, design.py, devlog.toml, ...) are never streamable, even
        # though they legitimately live under root.
        resolved = safe_join(root, path)
        if resolved is None:
            raise HTTPException(status_code=404, detail="not found")
        data_root = (root / "data").resolve()
        try:
            resolved.relative_to(data_root)
        except ValueError:
            raise HTTPException(status_code=404, detail="not found")
        if not resolved.is_file():
            raise HTTPException(status_code=404, detail="not found")
        return FileResponse(resolved)

    # ── static UI (built webui) or placeholder ───────────────────────────────
    assets_dir = _STATIC_DIR / "assets"
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=str(assets_dir)), name="assets")

    @app.get("/", response_model=None)
    def index() -> HTMLResponse | FileResponse:
        idx = _STATIC_DIR / "index.html"
        if idx.is_file():
            return FileResponse(idx)
        return HTMLResponse(_PLACEHOLDER_HTML)

    return app


async def _json_object(request: Request) -> dict:
    """Parse the request body as a JSON object, or 400."""
    try:
        body = await request.json()
    except Exception:  # noqa: BLE001
        raise HTTPException(status_code=400, detail="body is not valid JSON")
    if not isinstance(body, dict):
        raise HTTPException(status_code=400, detail="body must be a JSON object")
    return body
