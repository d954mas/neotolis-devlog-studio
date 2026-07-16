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

import json
import re
import shutil
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


def _deep_merge(base: dict, incoming: dict) -> dict:
    """Recursively merge `incoming` into `base` (both dicts). Nested dicts
    merge key-by-key; every other value (including lists) is replaced by the
    incoming value. Returns a new dict; inputs are not mutated."""
    out = dict(base)
    for k, v in incoming.items():
        if isinstance(out.get(k), dict) and isinstance(v, dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


# ─── long-running job bodies (run on the executor, off the request thread) ───

def _process_take_job(
    root: Path, beat_id: str, recording: Path,
    language: str | None, model: str | None,
) -> dict:
    """VO take -> loudness-normalized wav + word-timed transcript. Mirrors
    the `dl2 audio` path but writes to the API's fixed finalize locations."""
    from dlstudio import services

    audio_out = root / "data" / "finalize" / f"{beat_id}_vo.wav"
    words_out = root / "data" / "finalize" / f"{beat_id}_words.json"
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

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        yield
        jobs.shutdown()

    app = FastAPI(title="Studio v2", version="2.0.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
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
        timeline = build_timeline(edit)
        return JSONResponse(timeline.model_dump(mode="json"))

    # ── GET /api/check ───────────────────────────────────────────────────────
    @app.get("/api/check")
    def get_check() -> JSONResponse:
        timeline = build_timeline(edit)
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
        try:
            incoming = await request.json()
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
        merged = _deep_merge(store, incoming)
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
        dest.write_bytes(await file.read())
        return {"path": _rel(root, dest)}

    # ── POST /api/actions/process-take ───────────────────────────────────────
    @app.post("/api/actions/process-take")
    async def process_take_action(request: Request) -> dict:
        body = await _json_object(request)
        beat_id = safe_component(str(body.get("beat_id", "")))
        if beat_id is None:
            raise HTTPException(status_code=400, detail="bad or missing beat_id")
        rec_rel = body.get("recording_path")
        if not rec_rel:
            raise HTTPException(status_code=400, detail="recording_path is required")
        recording = safe_join(root, str(rec_rel))
        if recording is None:
            raise HTTPException(status_code=400, detail="recording_path escapes project root")
        if not recording.is_file():
            raise HTTPException(status_code=404, detail=f"recording not found: {rec_rel}")
        job_id = jobs.submit(
            _process_take_job, root, beat_id, recording,
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
        resolved = safe_join(root, path)
        if resolved is None or not resolved.is_file():
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
