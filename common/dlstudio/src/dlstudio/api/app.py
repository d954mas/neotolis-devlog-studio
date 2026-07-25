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

import hashlib
import importlib
import json
import math
import os
import re
import shutil
import sys
import threading
import uuid
from contextlib import asynccontextmanager
from datetime import datetime
from pathlib import Path
from typing import Literal

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

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


class ProductionOverviewInfo(BaseModel):
    id: str
    kind: str
    date: str
    orientation: str
    studio_ref: str
    current: bool


class ProductOverviewInfo(BaseModel):
    id: str
    title: str
    current_production_id: str
    productions: list[ProductionOverviewInfo]


class ProjectInfo(BaseModel):
    edit_name: str
    output: str
    design: DesignInfo
    beats: list[BeatInfo]
    script_sha256: str
    script_approved: bool
    product: ProductOverviewInfo | None = None


class ScriptApprovalRequest(BaseModel):
    approved_by: str = "author"


class AutopilotApprovalRequest(BaseModel):
    approved_by: str = Field(default="author", min_length=1, max_length=120)


class AutopilotChangeRequest(BaseModel):
    action: Literal["replace_shot", "request_capture", "change_text"]
    shot_id: str = Field(min_length=1, max_length=200)
    reason: str = Field(min_length=1, max_length=4000)
    requested_by: str = Field(default="author", min_length=1, max_length=120)


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


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _enrich_feedback(node: object, root: Path, _depth: int = 0) -> None:
    """Stale-feedback protection (PLAN_STUDIO_V2 2.6): any feedback node
    that names an `artifact_path` gets `artifact_sha256` (of the file as it
    exists RIGHT NOW under the project root) and a `timestamp` stamped in,
    unless the reviewer already provided them. Consumers (skills/agents)
    recompute the hash before trusting a stored verdict — a mismatch means
    the MP4 changed since the review and the verdict is stale.

    Mutates `node` in place; silently skips paths that escape the project
    root or don't exist (nothing to hash — the consumer then treats the
    verdict as unverifiable, not as fresh). Depth-bounded like _deep_merge."""
    if _depth > _MAX_MERGE_DEPTH or not isinstance(node, dict):
        return
    ap = node.get("artifact_path")
    if isinstance(ap, str) and ap:
        if "artifact_sha256" not in node:
            f = safe_join(root, ap)
            if f is not None and f.is_file():
                node["artifact_sha256"] = _sha256_file(f)
        node.setdefault(
            "timestamp", datetime.now().isoformat(timespec="seconds"))
    for value in node.values():
        _enrich_feedback(value, root, _depth + 1)


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
    edit, root: Path, beat_lock: threading.Lock, beat_id: str, recording: Path,
    language: str | None, model: str | None,
) -> dict:
    """VO take -> loudness-normalized wav + word-timed transcript.

    Mirrors `dl2 audio` (cmd_audio): the processed wav + words.json are
    written to the beat's OWN declared `beat.audio` / `beat.words` paths, not
    a fixed `<id>_vo.wav` convention. That is what makes a subsequent render
    (and the UI's audio/karaoke) actually see the new take — the render cache
    keys off the asset the beat's chunks reference. Paths are resolved under
    `root` with the same containment guard as `GET /api/file`.

    Defect 0.7: the whole job runs under the beat's lock (two Process jobs of
    one beat serialize; a render job of the same beat can never read the wav/
    words mid-replacement), and both stages write to TEMP files that are
    os.replace()-promoted to the declared paths only after BOTH succeed — a
    crash mid-processing leaves the previous take fully intact."""
    from dlstudio import services

    beat = edit.beats[beat_id]
    audio_out = safe_join(root, beat.audio)
    words_out = safe_join(root, beat.words)
    if audio_out is None or words_out is None:
        raise ValueError(
            f"beat {beat_id!r} declares an audio/words path outside the project "
            f"root (audio={beat.audio!r}, words={beat.words!r})"
        )
    with beat_lock:
        audio_out.parent.mkdir(parents=True, exist_ok=True)
        words_out.parent.mkdir(parents=True, exist_ok=True)
        verdict_out = (
            root / "data" / "review" / "voice_takes" / f"{recording.stem}.json"
        )
        rejected_verdict_out = verdict_out.with_name(
            f"{verdict_out.stem}.rejected.json"
        )
        # Same-directory temp names keep os.replace atomic (same volume); the
        # real extensions are preserved because ffmpeg/whisper infer output
        # format from them.
        nonce = uuid.uuid4().hex[:8]
        tmp_audio = audio_out.with_name(
            f".{audio_out.stem}.tmp-{nonce}{audio_out.suffix or '.wav'}")
        tmp_words = words_out.with_name(
            f".{words_out.stem}.tmp-{nonce}{words_out.suffix or '.json'}")
        tmp_verdict: Path | None = None
        try:
            try:
                result = services.process_take(recording, tmp_audio)
            except services.VoiceTakeQualityError as exc:
                services.write_voice_take_verdict(
                    exc.verdict,
                    rejected_verdict_out,
                )
                raise
            kwargs: dict = {}
            if language:
                kwargs["language"] = language
            if model:
                kwargs["model"] = model
            services.transcribe(tmp_audio, tmp_words, **kwargs)
            result_verdict = getattr(result, "verdict", None)
            replacements = [(tmp_audio, audio_out), (tmp_words, words_out)]
            if result_verdict is not None:
                tmp_verdict = verdict_out.with_name(
                    f".{verdict_out.stem}.tmp-{nonce}{verdict_out.suffix}"
                )
                services.write_voice_take_verdict(result_verdict, tmp_verdict)
                replacements.append((tmp_verdict, verdict_out))
            services.promote_bundle(replacements)
        finally:
            tmp_audio.unlink(missing_ok=True)
            tmp_words.unlink(missing_ok=True)
            if tmp_verdict is not None:
                tmp_verdict.unlink(missing_ok=True)
    return {
        "audio": _rel(root, audio_out),
        "words": _rel(root, words_out),
        "measured_lufs": result.input_i,
        "duration": result.duration,
        "voice_take_verdict": (
            _rel(root, verdict_out) if verdict_out.exists() else None
        ),
        "voice_take_status": (
            result_verdict.get("verdict") if result_verdict else None
        ),
        "voice_take_action": (
            result_verdict.get("recommended_action") if result_verdict else None
        ),
        "voice_take_issues": (
            result_verdict.get("issues", []) if result_verdict else []
        ),
    }


def _render_beat_job(
    edit, root: Path, render_lock, beat_lock: threading.Lock, beat_id: str,
    width: str | int | None, quality: str | None,
) -> dict:
    """Same code path as `dl2 compose`: compile -> resolver -> cache ->
    render_beat, in-process. Returns {output}. `render_lock` serializes the
    module-global chunk resolver against concurrent render jobs.

    Defect 0.9: the WHOLE job (compile -> cache check -> render -> cache put
    -> copy) runs under the beat's lock. The jobs executor is a ThreadPool in
    ONE process with no per-beat dedup, so two parallel render jobs of the
    same beat used to share the workdir MP4 and the cache tmp path and could
    publish a torn MP4 into the cache as a lasting hit. Serialized, the second job
    simply sees the first one's cache entry. (Also 0.7: holding the beat lock
    means a render can never read beat.audio/words mid-take-replacement.)"""
    from dlstudio import cache as dl_cache
    from dlstudio import compile as dl_compile
    from dlstudio import render as dl_render
    from dlstudio.cli import CliError, _resize_design, gate_pre_render_checks
    from dlstudio.render import beat as render_beat_mod

    with beat_lock:
        timeline = dl_compile.build_timeline(edit)
        beat = next((b for b in timeline.beats if b.id == beat_id), None)
        if beat is None:
            raise ValueError(
                f"beat {beat_id!r} not in edit {edit.name!r}; "
                f"available: {[b.id for b in timeline.beats]}"
            )

        design = _resize_design(timeline.design, width)
        quality = quality or "standard"
        try:
            gate_pre_render_checks(
                timeline,
                design,
                strict_assets=quality in {"upload", "master"},
            )   # defect 0.4: no gate, no render
        except CliError as e:
            raise ValueError(str(e)) from e
        width_px = design.resolution[0]

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
    from dlstudio.cli import load_edit, loaded_edit_module_name

    edit, root = load_edit(edit_module)
    edit_module = loaded_edit_module_name(edit_module)
    jobs = JobManager()
    render_lock = threading.Lock()

    # Per-beat job locks (defects 0.7/0.9): render and process-take jobs of
    # the SAME beat serialize; different beats stay parallel. Process-local
    # like the JobManager itself.
    beat_locks: dict[str, threading.Lock] = {}
    beat_locks_guard = threading.Lock()

    def _beat_lock(beat_id: str) -> threading.Lock:
        with beat_locks_guard:
            return beat_locks.setdefault(beat_id, threading.Lock())

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
        from dlstudio.production import production_module_files

        production_files = production_module_files(edit_module)
        if production_files:
            return production_files
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
        from dlstudio.production import production_module_files, reload_production_edit_module

        if production_module_files(edit_module):
            return reload_production_edit_module(edit_module).EDIT
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

    # Research projects are shared by every production opened from the same
    # workspace, rather than being buried inside the current edit's data.
    from dlstudio.api.research import create_research_router
    from dlstudio.cli import _find_workspace_root

    research_root = _find_workspace_root(root) or root
    app.include_router(create_research_router(research_root))

    def _feedback_path() -> Path:
        return root / "data" / "review" / "feedback.json"

    def _script_text(current_edit) -> str:
        from dlstudio.services.script_preflight import canonical_script_text

        return canonical_script_text(current_edit)

    def _script_approval_path() -> Path:
        return root / "data" / "plan" / "script_approval.json"

    def _script_status(current_edit) -> tuple[str, bool]:
        from dlstudio.services.script_preflight import (
            script_sha256,
            verify_script_approval,
        )

        script = _script_text(current_edit)
        digest = script_sha256(script)
        approval = _script_approval_path()
        if not approval.is_file():
            return digest, False
        try:
            verified = verify_script_approval(
                script, approval, script_id=current_edit.name
            )
        except (OSError, ValueError, json.JSONDecodeError):
            return digest, False
        return digest, verified.ok

    def _reject_stale_script_approval(current_edit) -> None:
        """Require approval of the exact current script before recording."""

        if not _script_status(current_edit)[1]:
            state = "stale" if _script_approval_path().is_file() else "missing"
            raise HTTPException(
                status_code=409,
                detail=f"script approval is {state}; approve the current script",
            )

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
        script_digest, script_approved = _script_status(edit)
        product_info = None
        if (root / "production.toml").is_file():
            from dlstudio.services.product_overview import build_product_overview

            overview = build_product_overview(root)
            product_info = ProductOverviewInfo(
                id=overview.product_id,
                title=overview.title,
                current_production_id=overview.current_production_id,
                productions=[
                    ProductionOverviewInfo(
                        id=item.id,
                        kind=item.kind,
                        date=item.date,
                        orientation=item.orientation,
                        studio_ref=item.studio_ref,
                        current=item.current,
                    )
                    for item in overview.productions
                ],
            )
        return ProjectInfo(
            edit_name=edit.name, output=edit.output,
            design=DesignInfo(resolution=edit.design.resolution, fps=edit.design.fps),
            beats=beats,
            script_sha256=script_digest,
            script_approved=script_approved,
            product=product_info,
        )

    @app.post("/api/script/approve")
    def approve_current_script(body: ScriptApprovalRequest) -> JSONResponse:
        from dlstudio.services.script_preflight import approve_script

        edit = _current_edit()
        approved_by = body.approved_by.strip()
        if not approved_by:
            raise HTTPException(status_code=400, detail="approved_by must be non-empty")
        script = _script_text(edit)
        approval = approve_script(
            script,
            script_id=edit.name,
            approved_by=approved_by,
            approved_at=datetime.now().isoformat(timespec="seconds"),
        )
        path = _script_approval_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps(approval.to_dict(), ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        return JSONResponse({
            "script_sha256": approval.script_sha256,
            "script_approved": True,
            "approved_by": approved_by,
        })

    # ── Autopilot single checkpoint ──
    @app.get("/api/autopilot/checkpoint")
    def get_autopilot_checkpoint() -> JSONResponse:
        from dlstudio.services.autopilot_checkpoint import load_checkpoint

        return JSONResponse(load_checkpoint(root))

    @app.post("/api/autopilot/checkpoint/approve")
    def approve_autopilot_checkpoint(body: AutopilotApprovalRequest) -> JSONResponse:
        from dlstudio.services.autopilot_checkpoint import approve_all

        try:
            return JSONResponse(approve_all(root, approved_by=body.approved_by))
        except ValueError as exc:
            # Approval with blockers is a state conflict, not an automatic fix.
            raise HTTPException(status_code=409, detail=str(exc)) from exc

    @app.post("/api/autopilot/checkpoint/request")
    def request_autopilot_change(body: AutopilotChangeRequest) -> JSONResponse:
        from dlstudio.services.autopilot_checkpoint import request_change

        try:
            result = request_change(
                root,
                action=body.action,
                shot_id=body.shot_id,
                reason=body.reason,
                requested_by=body.requested_by,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        return JSONResponse(result)

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
        _enrich_feedback(incoming, root)   # 2.6: pin verdicts to the exact MP4

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
    async def upload_take(
        beat_id: str,
        file: UploadFile = File(...),
        metadata: str | None = Form(default=None),
    ) -> dict:
        bid = safe_component(beat_id)
        if bid is None:
            raise HTTPException(status_code=400, detail="bad beat id")
        current_edit = _current_edit()
        if bid not in current_edit.beats:
            raise HTTPException(status_code=404, detail=f"unknown beat: {bid}")
        _reject_stale_script_approval(current_edit)
        metadata_payload: dict | None = None
        if metadata is not None:
            if len(metadata.encode("utf-8")) > 16 * 1024:
                raise HTTPException(status_code=413, detail="take metadata is too large")
            try:
                parsed = json.loads(metadata)
            except json.JSONDecodeError as exc:
                raise HTTPException(status_code=400, detail="invalid take metadata JSON") from exc
            if not isinstance(parsed, dict):
                raise HTTPException(status_code=400, detail="take metadata must be an object")
            if (
                parsed.get("schema") != "devlog.voice_take"
                or parsed.get("version") != 1
            ):
                raise HTTPException(status_code=400, detail="unsupported take metadata schema")
            numeric_fields = (
                "countdown_seconds",
                "room_tone_seconds",
                "speech_start_seconds",
                "stop_requested_seconds",
                "post_roll_end_seconds",
                "post_roll_target_seconds",
            )
            if any(
                not isinstance(parsed.get(name), (int, float))
                or isinstance(parsed.get(name), bool)
                or not math.isfinite(float(parsed[name]))
                or float(parsed[name]) < 0
                for name in numeric_fields
            ):
                raise HTTPException(status_code=400, detail="invalid take metadata timings")
            if not all(
                isinstance(parsed.get(name), bool)
                for name in ("post_roll_completed", "completed_lead_in")
            ):
                raise HTTPException(status_code=400, detail="invalid take metadata markers")
            expected_speech_start = (
                float(parsed["countdown_seconds"])
                + float(parsed["room_tone_seconds"])
            )
            if abs(float(parsed["speech_start_seconds"]) - expected_speech_start) > 0.01:
                raise HTTPException(
                    status_code=400,
                    detail="take speech marker does not match countdown + room tone",
                )
            if float(parsed["post_roll_end_seconds"]) < float(
                parsed["stop_requested_seconds"]
            ):
                raise HTTPException(status_code=400, detail="take metadata timings are unordered")
            metadata_payload = parsed
        ext = _safe_ext(file.filename)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        rec_dir = root / "data" / "recordings"
        rec_dir.mkdir(parents=True, exist_ok=True)
        dest = rec_dir / f"{bid}_{ts}{ext}"
        upload_staging = rec_dir / f".{dest.name}.{uuid.uuid4().hex}.upload"

        # Stream to disk in bounded chunks: never hold the whole take in RAM,
        # enforce a hard size cap, and reject an empty upload.
        total = 0
        over_cap = False
        with upload_staging.open("wb") as fh:
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
            upload_staging.unlink(missing_ok=True)
            raise HTTPException(status_code=413, detail="upload exceeds 500MB limit")
        if total == 0:
            upload_staging.unlink(missing_ok=True)
            raise HTTPException(status_code=400, detail="empty upload")
        replacements = [(upload_staging, dest)]
        metadata_dest: Path | None = None
        metadata_staging: Path | None = None
        try:
            if metadata_payload is not None:
                metadata_dest = dest.with_suffix(dest.suffix + ".recording.json")
                metadata_staging = rec_dir / (
                    f".{metadata_dest.name}.{uuid.uuid4().hex}.upload"
                )
                metadata_staging.write_text(
                    json.dumps(
                        metadata_payload,
                        ensure_ascii=False,
                        indent=2,
                    ),
                    encoding="utf-8",
                )
                replacements.append((metadata_staging, metadata_dest))
            from dlstudio.services.bundle import promote_bundle

            promote_bundle(replacements)
        finally:
            upload_staging.unlink(missing_ok=True)
            if metadata_staging is not None:
                metadata_staging.unlink(missing_ok=True)
        result = {"path": _rel(root, dest)}
        if metadata_dest is not None:
            result["metadata_path"] = _rel(root, metadata_dest)
        return result

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
        _reject_stale_script_approval(edit)
        rec_rel = body.get("recording_path")
        if not rec_rel:
            raise HTTPException(status_code=400, detail="recording_path is required")
        recording = safe_join(root, str(rec_rel))
        if recording is None:
            raise HTTPException(status_code=400, detail="recording_path escapes project root")
        if not recording.is_file():
            raise HTTPException(status_code=404, detail=f"recording not found: {rec_rel}")
        job_id = jobs.submit(
            _process_take_job, edit, root, _beat_lock(beat_id), beat_id, recording,
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
            _render_beat_job, edit, root, render_lock, _beat_lock(beat_id), beat_id,
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
    @app.get("/research", response_model=None)
    @app.get("/research/", response_model=None)
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
