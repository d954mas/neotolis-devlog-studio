"""cli — the `dl2` command.

OWNER: cli-agent.

Phase 1 commands:
  dl2 check <edit>                 compile + run_checks, human-readable report
  dl2 ir <edit> [--out ir.json]    dump the Timeline IR (agents' ground truth)
  dl2 compose <edit> <beat>        render one beat (cache-aware)
  dl2 iter <edit> [--stale]        draft-quality render of all/stale beats
  dl2 beats <edit>                 durations, chunk counts, render status
  dl2 doctor                       ffmpeg/ffprobe/python/pydantic diagnostics

Phase 2 commands (full mix assemble — music/ducking/SFX/transitions/loudnorm):
  dl2 render <edit>                full render + mix assemble (default 1080p/standard)
  dl2 final <edit>                 shipping render + mix ([v2.final] defaults, else 1080p/upload)

Phase 3 commands (services + Studio backend):
  dl2 audio <edit> <beat> <rec>    process a take -> beat VO wav + words.json
  dl2 transcribe <wav> <out.json>  standalone word-level transcription
  dl2 scratch-tts <edit> <beat>    scratch VO from beat.vo -> data/scratch/
  dl2 studio [edit] [--port]       serve the FastAPI Studio backend (127.0.0.1)

Phase 4 commands (stock/publish services + owner-domain verification):
  dl2 publish [edit] [--out]       generate youtube_package.md (title/desc/tags/chapters)
  dl2 stock search "<q>" [--out]   thin Pexels/Pixabay b-roll search -> JSON results
  dl2 stock download <manifest>    download search results -> files + manifest.json
    --out <dir>
  dl2 verify --changed [--full]    map changed paths -> owning domain -> its
                                   tests only (see cli/verify.py); --full runs
                                   the whole suite

Conventions (v1 parity where sensible):
- <edit> is a dotted module path exposing EDIT (dlstudio.model.Edit);
  CLI auto-detects project root from module location and chdirs there so
  beats.py paths stay relative. Port the loader idea from legacy cli.py.
- Import compile/render lazily INSIDE handlers (stubs may be unimplemented).
- Top-level error boundary in main(): pretty one-line error + exit 1;
  --debug re-raises with traceback. No raw tracebacks by default (v1 gap).
- Defaults read from workspace devlog.toml [v2] table when present.
"""
from __future__ import annotations

import argparse
import concurrent.futures
import importlib
import os
import shutil
import subprocess
import sys
import tomllib
from dataclasses import dataclass
from pathlib import Path

from dlstudio.ir import IRBeat
from dlstudio.model import Design, Edit

from . import genhtml as dl_genhtml
from . import newvideo as dl_newvideo
from . import verify as dl_verify

CONFIG_NAME = "devlog.toml"

# Named resolution profiles (defect 0.6). CLI, Studio API and webui resolve
# presets through this ONE table logic so they can never disagree:
#
#   draft tiers anchor the output HEIGHT (a 540-tall preview in either
#   orientation — matches the Studio webui's preview size):
#     landscape 540p = 960x540      vertical 540p = 304x540
#   delivery tiers anchor the LONG side to the standard 16:9 long dimension
#   (a vertical final is the transposed standard, NEVER "width 3840" — the
#   3840x6826 x264 OOM class):
#     landscape 1080p = 1920x1080   vertical 1080p = 1080x1920
#     landscape 4k    = 3840x2160   vertical 4k    = 2160x3840
_HEIGHT_ANCHORED_PRESETS = {"360p": 360, "540p": 540, "720p": 720}
_LONG_SIDE_PRESETS = {"1080p": 1920, "1440p": 2560, "4k": 3840}
_ALL_PRESETS = sorted({**_HEIGHT_ANCHORED_PRESETS, **_LONG_SIDE_PRESETS})

_QUALITY_PRESETS = ("draft", "preview", "standard", "upload", "master")


class CliError(Exception):
    """User-facing CLI error. main() prints this as a single line and
    exits 1 instead of showing a traceback (unless --debug is passed)."""


# ─── workspace / config ──────────────────────────────────────────────────

def _find_workspace_root(start: Path | None = None) -> Path | None:
    """Search upward from `start` (default cwd) for a workspace marker:
    devlog.toml first, then a .git directory. Returns None if neither is
    found before hitting the filesystem root."""
    cur = (start or Path.cwd()).resolve()
    if cur.is_file():
        cur = cur.parent
    for parent in (cur, *cur.parents):
        if (parent / CONFIG_NAME).exists():
            return parent
    for parent in (cur, *cur.parents):
        if (parent / ".git").exists():
            return parent
    return None


def _load_v2_config(workspace_root: Path | None) -> dict:
    """Read the [v2] table from workspace devlog.toml, if present."""
    if workspace_root is None:
        return {}
    cfg_path = workspace_root / CONFIG_NAME
    if not cfg_path.exists():
        return {}
    data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    return dict(data.get("v2", {}))


def _load_v2_final_config(workspace_root: Path | None) -> dict:
    """Read the [v2.final] table from workspace devlog.toml, if present.
    Supplies `dl2 final`'s default width/quality (an inline table under [v2]
    also works: `[v2.final]` with `width`/`quality` keys)."""
    if workspace_root is None:
        return {}
    cfg_path = workspace_root / CONFIG_NAME
    if not cfg_path.exists():
        return {}
    data = tomllib.loads(cfg_path.read_text(encoding="utf-8"))
    return dict(data.get("v2", {}).get("final", {}))


def _resolve_edit_arg(edit_arg: str | None, v2_config: dict) -> str:
    dotted = edit_arg or v2_config.get("default_edit")
    if not dotted:
        raise CliError(
            "edit module is required: pass it explicitly or set "
            "[v2] default_edit in devlog.toml"
        )
    return dotted


# ─── edit loader ──────────────────────────────────────────────────────────

def _project_root_for_module(module_file: Path, workspace_root: Path | None) -> Path:
    """First parent of the module's directory that is a direct child of
    `workspace_root`. Falls back to the legacy fixed-depth heuristic
    (edits/<name>/__init__.py is two directories below the project root)
    when no workspace root marker was found."""
    module_dir = module_file.resolve().parent
    if workspace_root is not None:
        ws = workspace_root.resolve()
        cur = module_dir
        while cur.parent != cur and cur.parent != ws:
            cur = cur.parent
        if cur.parent == ws:
            return cur
    return module_dir.parent.parent


def load_edit(dotted: str) -> tuple[Edit, Path]:
    """Import `dotted`, read its EDIT attribute, validate it, find the
    project root (mirrors legacy loader semantics), and os.chdir there so
    beats.py paths stay relative. Returns (edit, project_root).

    Shared by the CLI handlers (via `_load_edit`) and the API app factory
    (`dlstudio.api.create_app`), which also needs the resolved project root
    for its file-serving/recording endpoints."""
    try:
        mod = importlib.import_module(dotted)
    except ImportError as e:
        raise CliError(f"cannot import edit module {dotted!r}: {e}") from e
    if not hasattr(mod, "EDIT"):
        raise CliError(
            f"module {dotted!r} has no EDIT object — expected `EDIT = Edit(...)`"
        )
    edit = mod.EDIT
    if not isinstance(edit, Edit):
        raise CliError(f"{dotted}.EDIT is a {type(edit).__name__}, not dlstudio.model.Edit")
    module_file = getattr(mod, "__file__", None)
    if not module_file:
        raise CliError(f"module {dotted!r} has no __file__ (namespace package?)")
    workspace_root = _find_workspace_root()
    project_root = _project_root_for_module(Path(module_file), workspace_root)
    os.chdir(project_root)
    print(f"[dl2] cwd -> {project_root}")
    return edit, project_root


def _load_edit(dotted: str) -> Edit:
    """Load + chdir (see `load_edit`), returning just the Edit — the shape
    the existing render/check handlers expect."""
    edit, _root = load_edit(dotted)
    return edit


# ─── render option helpers ────────────────────────────────────────────────

def _resize_design(design: Design, width_spec: str | int | None) -> Design:
    """Return a copy of `design` scaled to `width_spec`, aspect preserved.

    `width_spec` is a preset name (resolved orientation-aware through the
    profile table above — see the 0.6 note) or a literal pixel WIDTH.
    None returns `design` unchanged. Dimensions are rounded to even pixels
    (x264 requirement).
    """
    if width_spec is None:
        return design
    orig_w, orig_h = design.resolution
    if isinstance(width_spec, str) and width_spec in _HEIGHT_ANCHORED_PRESETS:
        new_h = float(_HEIGHT_ANCHORED_PRESETS[width_spec])
        new_w = new_h * orig_w / orig_h
    elif isinstance(width_spec, str) and width_spec in _LONG_SIDE_PRESETS:
        long_side = float(_LONG_SIDE_PRESETS[width_spec])
        if orig_w >= orig_h:                     # landscape/square
            new_w, new_h = long_side, long_side * orig_h / orig_w
        else:                                    # vertical
            new_h, new_w = long_side, long_side * orig_w / orig_h
    else:
        try:
            new_w = float(int(width_spec))
        except (TypeError, ValueError):
            raise CliError(
                f"--width must be an int or one of {_ALL_PRESETS}, got {width_spec!r}"
            )
        new_h = new_w * orig_h / orig_w
    even_w = (round(new_w) // 2) * 2
    even_h = (round(new_h) // 2) * 2
    return design.model_copy(update={"resolution": (even_w, even_h)})


def _add_render_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--width", help="preset (360p/540p/720p/1080p/1440p/4k) or literal pixel width")
    p.add_argument("--quality", choices=_QUALITY_PRESETS, help="render quality tier")
    p.add_argument("--gpu", action="store_true", help="use GPU (NVENC) encoding")
    p.add_argument("--no-cache", action="store_true", help="bypass the render cache")


def gate_pre_render_checks(timeline, design: Design) -> None:
    """Defect 0.4: the mechanical gate every render path MUST pass first —
    `resolve profile -> compile -> run checks -> render -> verify output`.

    Checks run on the EFFECTIVE timeline (the design swapped for the resolved
    render resolution) so VQ-RES judges the real target, not the native size.
    Errors always block, at every quality tier (a draft built on a missing
    asset or an unloadable font is a wrong video, not a fast one); warnings
    are printed and never block. Shared with the Studio API render job."""
    from dlstudio import check as dl_check

    effective = timeline.model_copy(update={"design": design})
    report = dl_check.run_checks(effective)
    for issue in report.issues:
        print(f"[dl2] [{issue.severity.upper()}] {issue.code} {issue.where}: {issue.message}")
    errors = report.errors
    if errors:
        raise CliError(
            f"pre-render checks failed with {len(errors)} error(s) — "
            f"fix the errors above (see `dl2 check`); nothing was rendered"
        )


# ─── compose worker (top-level so it's picklable for -j N) ────────────────

def _compose_worker(
    beat: IRBeat,
    design: Design,
    quality: str,
    gpu: bool,
    width_px: int | None,
    out_path: str,
    cache_dir_override: str | None,
    beat_chunks: list | None = None,
    no_cache: bool = False,
) -> str:
    """Render one beat to `out_path`, cache-aware unless `no_cache` is set.
    Runs in a worker process under -j N (each worker is a fresh interpreter;
    the cache's atomic publish makes concurrent workers safe even on a
    shared key).

    No `timeline` parameter on purpose: render_beat's `timeline` argument is
    unused (see render/beat.py), so shipping the whole Timeline to every
    worker was pure O(N^2) IPC overhead (N workers each pickling all N
    beats) for nothing. render_beat is called with `None` in its place.

    `beat_chunks` is this beat's source Chunk list — workers are fresh
    interpreters, so the chunk resolver must be re-registered here, not in
    the parent process.

    `no_cache`, when set, bypasses BOTH the cache read and the cache write
    entirely (matches `dl2 compose --no-cache`'s bypass semantics) — every
    call renders fresh and nothing is published to the cache."""
    if cache_dir_override:
        os.environ[_cache_dir_env_var()] = cache_dir_override
    from dlstudio import cache as dl_cache
    from dlstudio import render as dl_render

    if beat_chunks is not None:
        from dlstudio.render import beat as render_beat_mod

        render_beat_mod.set_chunk_resolver(lambda _bid, ci: beat_chunks[ci])

    # width is redundant with design.resolution (already hashed via
    # design.model_dump_json() inside beat_key) -- normalize to the resolved
    # resolution so a caller-supplied None vs an explicit-but-equal pixel
    # width never produce two different cache keys for identical output.
    width_px = design.resolution[0]
    out = Path(out_path)

    if no_cache:
        opts = dl_render.RenderOpts(width=width_px, quality=quality, gpu=gpu, workdir=out.parent)
        rendered = dl_render.render_beat(beat, design, None, opts)
        # render_beat writes workdir/<beat>.mp4 — with workdir = out.parent
        # that IS `out` already; copying a file onto itself raises
        # shutil.SameFileError (defect 0.3).
        if Path(rendered).resolve() != out.resolve():
            shutil.copyfile(rendered, out)
        return f"rendered (no-cache) -> {out}"

    key = dl_cache.beat_key(beat, design, quality=quality, width=width_px, gpu=gpu)
    if dl_cache.get(key, out):
        return f"cache hit {key} -> {out}"
    opts = dl_render.RenderOpts(width=width_px, quality=quality, gpu=gpu, workdir=out.parent)
    rendered = dl_render.render_beat(beat, design, None, opts)
    dl_cache.put(key, rendered)
    dl_cache.get(key, out)
    return f"rendered {key} -> {out}"


def _cache_dir_env_var() -> str:
    from dlstudio import cache as dl_cache

    return dl_cache.CACHE_DIR_ENV_VAR


def _render_targets(
    targets: list[IRBeat],
    design: Design,
    *,
    quality: str,
    gpu: bool,
    width_px: int | None,
    beat_files: dict[str, Path],
    jobs: int,
    chunks_by_beat: dict[str, list] | None = None,
    no_cache: bool = False,
) -> None:
    """Render every beat in `targets` to beat_files[beat.id]. Serial when
    jobs <= 1 or there's nothing to parallelize; otherwise fans out across
    `jobs` worker processes via ProcessPoolExecutor.

    No `timeline` parameter on purpose (see _compose_worker): it was never
    used by render_beat, so pickling the whole Timeline out to every worker
    was O(N^2) IPC for nothing.

    `no_cache` is forwarded to every worker call unchanged; `dl2 iter
    --no-cache` (cmd_iter) is what threads it in here."""
    cache_dir_override = os.environ.get(_cache_dir_env_var())
    by_beat = chunks_by_beat or {}
    if jobs > 1 and len(targets) > 1:
        print(f"[dl2] launching {jobs} workers for {len(targets)} beats")
        with concurrent.futures.ProcessPoolExecutor(max_workers=jobs) as pool:
            futures = {
                pool.submit(
                    _compose_worker, b, design, quality, gpu, width_px,
                    str(beat_files[b.id]), cache_dir_override, by_beat.get(b.id),
                    no_cache,
                ): b.id
                for b in targets
            }
            for fut in concurrent.futures.as_completed(futures):
                bid = futures[fut]
                msg = fut.result()
                print(f"[dl2] {bid}: {msg}")
    else:
        for b in targets:
            msg = _compose_worker(
                b, design, quality, gpu, width_px,
                str(beat_files[b.id]), cache_dir_override, by_beat.get(b.id),
                no_cache,
            )
            print(f"[dl2] {b.id}: {msg}")


# ─── commands ──────────────────────────────────────────────────────────

def cmd_check(args: argparse.Namespace) -> int:
    v2_config = _load_v2_config(_find_workspace_root())
    dotted = _resolve_edit_arg(args.edit, v2_config)
    edit = _load_edit(dotted)

    from dlstudio import check as dl_check
    from dlstudio import compile as dl_compile

    timeline = dl_compile.build_timeline(edit)
    report = dl_check.run_checks(timeline)
    for issue in report.issues:
        print(f"[{issue.severity.upper()}] {issue.code} {issue.where}: {issue.message}")
    errors = report.errors
    warnings = [i for i in report.issues if i.severity == "warn"]
    print(f"[dl2] check: {len(errors)} errors, {len(warnings)} warnings")
    return 1 if errors else 0


def cmd_ir(args: argparse.Namespace) -> int:
    v2_config = _load_v2_config(_find_workspace_root())
    dotted = _resolve_edit_arg(args.edit, v2_config)
    edit = _load_edit(dotted)

    from dlstudio import compile as dl_compile

    timeline = dl_compile.build_timeline(edit)
    text = timeline.model_dump_json(indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(text, encoding="utf-8")
        print(f"[dl2] wrote {out_path}")
    else:
        print(text)
    return 0


def _resolve_compose_args(args: argparse.Namespace, v2_config: dict) -> tuple[str, str]:
    """`edit_or_beat` + optional `beat_id` (v1-style disambiguation): when
    beat_id is omitted, edit_or_beat IS the beat id and the edit comes from
    config/default_edit."""
    if args.beat_id is None:
        dotted = _resolve_edit_arg(None, v2_config)
        beat_id = args.edit_or_beat
    else:
        dotted = _resolve_edit_arg(args.edit_or_beat, v2_config)
        beat_id = args.beat_id
    return dotted, beat_id


def cmd_compose(args: argparse.Namespace) -> int:
    v2_config = _load_v2_config(_find_workspace_root())
    dotted, beat_id = _resolve_compose_args(args, v2_config)
    edit = _load_edit(dotted)

    from dlstudio import cache as dl_cache
    from dlstudio import compile as dl_compile
    from dlstudio import render as dl_render

    timeline = dl_compile.build_timeline(edit)
    beat = next((b for b in timeline.beats if b.id == beat_id), None)
    if beat is None:
        available = [b.id for b in timeline.beats]
        raise CliError(f"beat {beat_id!r} not in edit {edit.name!r}; available: {available}")

    design = _resize_design(timeline.design, args.width)
    gate_pre_render_checks(timeline, design)
    # width is redundant with design.resolution (already hashed inside
    # beat_key via design.model_dump_json()) -- always use the resolved
    # value so identical resolutions hash identically whether or not
    # --width was explicit (e.g. native resolution vs an equal explicit
    # --width no longer produce two different cache entries for the same
    # output; see beat_key in dlstudio.cache).
    width_px = design.resolution[0]
    quality = args.quality or "standard"

    out_dir = Path("data/finalize")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{beat_id}.mp4"

    cache_enabled = not args.no_cache
    key = dl_cache.beat_key(beat, design, quality=quality, width=width_px, gpu=args.gpu)
    if cache_enabled and dl_cache.get(key, out_path):
        print(f"[dl2] cache hit {key} -> {out_path}")
        return 0

    from dlstudio.render import beat as render_beat_mod

    render_beat_mod.set_chunk_resolver(lambda bid, ci: edit.beats[bid].chunks[ci])

    opts = dl_render.RenderOpts(width=width_px, quality=quality, gpu=args.gpu, workdir=out_dir)
    rendered = dl_render.render_beat(beat, design, None, opts)
    if cache_enabled:
        dl_cache.put(key, rendered)
        dl_cache.get(key, out_path)
    elif Path(rendered).resolve() != out_path.resolve():
        # workdir == out_dir, so render_beat usually wrote out_path itself;
        # a same-file copy would raise shutil.SameFileError (defect 0.3).
        shutil.copyfile(rendered, out_path)
    print(f"[dl2] rendered {beat_id} -> {out_path}")
    return 0


def _iterate_render(
    edit: Edit,
    timeline,
    *,
    width_spec: str | int | None,
    quality: str,
    gpu: bool,
    no_cache: bool,
    stale: bool,
    jobs: int | None,
) -> int:
    """Shared render+assemble machinery behind `iter`/`render`/`final`.

    Renders all (or, with `stale`, only cache-miss) beats to data/finalize at
    the resolved width/quality, then runs the FULL mix assemble (music beds,
    ducking, SFX, transitions, loudnorm — assemble picks its fast pure-concat
    path automatically when the edit has none of those). The three commands
    differ ONLY in their default width/quality; everything below is identical."""
    from dlstudio import cache as dl_cache
    from dlstudio import render as dl_render

    design = _resize_design(timeline.design, width_spec)
    gate_pre_render_checks(timeline, design)
    width_px = design.resolution[0]

    all_beats = list(timeline.beats)
    out_dir = Path("data/finalize")
    out_dir.mkdir(parents=True, exist_ok=True)
    beat_files = {b.id: out_dir / f"{b.id}.mp4" for b in all_beats}

    if stale:
        targets = []
        for b in all_beats:
            key = dl_cache.beat_key(b, design, quality=quality, width=width_px, gpu=gpu)
            if dl_cache.has(key):
                # Cache hit: ALWAYS materialize from the cache (defect 0.1).
                # An existing data/finalize/<beat>.mp4 proves nothing — it
                # may be a leftover from another resolution/quality/edit and
                # would silently reach assemble. The only file --stale may
                # trust is the exact cache artifact for THIS key.
                dl_cache.get(key, beat_files[b.id])
            else:
                targets.append(b)
        print(f"[dl2] stale beats: {len(targets)}/{len(all_beats)}")
        if not targets:
            print("[dl2] nothing to render")
    else:
        targets = all_beats

    jobs = max(1, jobs or 1)
    _render_targets(
        targets, design,
        quality=quality, gpu=gpu, width_px=width_px,
        beat_files=beat_files, jobs=jobs,
        chunks_by_beat={bid: b.chunks for bid, b in edit.beats.items()},
        no_cache=no_cache,
    )

    missing = [bid for bid, p in beat_files.items() if not p.exists()]
    if missing:
        raise CliError(
            f"missing rendered beats (no prior render to reuse for --stale): {missing}"
        )

    opts = dl_render.RenderOpts(width=width_px, quality=quality, gpu=gpu, workdir=out_dir)
    final = dl_render.assemble(timeline, beat_files, opts)
    print(f"[dl2] assembled -> {final}")
    return 0


def cmd_iter(args: argparse.Namespace) -> int:
    v2_config = _load_v2_config(_find_workspace_root())
    dotted = _resolve_edit_arg(args.edit, v2_config)
    edit = _load_edit(dotted)

    from dlstudio import compile as dl_compile

    timeline = dl_compile.build_timeline(edit)
    return _iterate_render(
        edit, timeline,
        width_spec=args.width or "540p", quality=args.quality or "draft",
        gpu=args.gpu, no_cache=args.no_cache, stale=args.stale, jobs=args.jobs,
    )


def cmd_render(args: argparse.Namespace) -> int:
    """Full-render preview: iter-style render + full mix assemble at explicit
    (default 1080p/standard) width/quality."""
    v2_config = _load_v2_config(_find_workspace_root())
    dotted = _resolve_edit_arg(args.edit, v2_config)
    edit = _load_edit(dotted)

    from dlstudio import compile as dl_compile

    timeline = dl_compile.build_timeline(edit)
    return _iterate_render(
        edit, timeline,
        width_spec=args.width or "1080p", quality=args.quality or "standard",
        gpu=args.gpu, no_cache=args.no_cache, stale=args.stale, jobs=args.jobs,
    )


def cmd_final(args: argparse.Namespace) -> int:
    """Shipping render: same machinery as `render`, but defaults come from the
    workspace `[v2.final]` table (width/quality) when present, else 1080p/upload.
    Explicit --width/--quality still win."""
    workspace_root = _find_workspace_root()
    v2_config = _load_v2_config(workspace_root)
    final_cfg = _load_v2_final_config(workspace_root)
    dotted = _resolve_edit_arg(args.edit, v2_config)
    edit = _load_edit(dotted)

    from dlstudio import compile as dl_compile

    timeline = dl_compile.build_timeline(edit)
    width_spec = args.width or final_cfg.get("width") or "1080p"
    quality = args.quality or final_cfg.get("quality") or "upload"
    return _iterate_render(
        edit, timeline,
        width_spec=width_spec, quality=quality,
        gpu=args.gpu, no_cache=args.no_cache, stale=args.stale, jobs=args.jobs,
    )


def _format_beats_table(rows: list[tuple[str, float, int, bool]]) -> str:
    header = f"{'beat':<28} {'dur(s)':>8} {'chunks':>7} {'cached':>7}"
    lines = [header, "-" * len(header)]
    for bid, dur, n_chunks, cached in rows:
        lines.append(f"{bid:<28} {dur:>8.2f} {n_chunks:>7} {'yes' if cached else 'no':>7}")
    return "\n".join(lines)


def cmd_beats(args: argparse.Namespace) -> int:
    v2_config = _load_v2_config(_find_workspace_root())
    dotted = _resolve_edit_arg(args.edit, v2_config)
    edit = _load_edit(dotted)

    from dlstudio import cache as dl_cache
    from dlstudio import compile as dl_compile

    timeline = dl_compile.build_timeline(edit)
    # Mirror cmd_iter's own defaults (draft/540p): `dl2 beats` exists to show
    # whether the iterate loop's beats are cached, so its cache-key inputs
    # must default to exactly what cmd_iter defaults to, or every beat shows
    # cached=no right after a plain `dl2 iter` even though iter just cached
    # every one of them under its own (draft/540p) key.
    width_spec = args.width or "540p"
    quality = args.quality or "draft"
    design = _resize_design(timeline.design, width_spec)
    # width is redundant with design.resolution (see cmd_compose) -- always
    # resolved, never None, so the key lines up regardless of whether
    # --width was passed explicitly.
    width_px = design.resolution[0]

    rows = []
    for b in timeline.beats:
        chunk_count = len(edit.beats[b.id].chunks) if b.id in edit.beats else 0
        key = dl_cache.beat_key(b, design, quality=quality, width=width_px, gpu=args.gpu)
        rows.append((b.id, b.duration, chunk_count, dl_cache.has(key)))
    print(_format_beats_table(rows))
    return 0


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _tool_version(exe: str, path: str) -> str:
    try:
        result = subprocess.run(
            [exe, "-version"], capture_output=True, text=True, timeout=5,
            encoding="utf-8", errors="replace",
        )
        text = (result.stdout or result.stderr or "").strip()
        return text.splitlines()[0] if text else "(version unknown)"
    except Exception as e:  # pragma: no cover - defensive, environment-dependent
        return f"found at {path} but failed to run: {e}"


def run_doctor() -> list[DoctorCheck]:
    """ffmpeg/ffprobe presence + version, python version, and the core
    pydantic/PIL/numpy imports. All are `required` — a missing ffmpeg (or
    any core dependency) is a hard doctor failure."""
    checks: list[DoctorCheck] = []

    for exe in ("ffmpeg", "ffprobe"):
        path = shutil.which(exe)
        if path:
            checks.append(DoctorCheck(exe, True, f"{path} — {_tool_version(exe, path)}"))
        else:
            checks.append(DoctorCheck(exe, False, "not found on PATH"))

    checks.append(DoctorCheck("python", True, sys.version.split()[0]))

    for mod_name in ("pydantic", "PIL", "numpy"):
        try:
            mod = importlib.import_module(mod_name)
            version = getattr(mod, "__version__", "unknown")
            checks.append(DoctorCheck(mod_name, True, f"version {version}"))
        except ImportError as e:
            checks.append(DoctorCheck(mod_name, False, str(e)))

    return checks


def _format_doctor(checks: list[DoctorCheck]) -> str:
    lines = []
    for c in checks:
        status = "OK" if c.ok else "MISSING"
        lines.append(f"[{status}] {c.name}: {c.detail}")
    return "\n".join(lines)


def cmd_doctor(args: argparse.Namespace) -> int:
    checks = run_doctor()
    print(_format_doctor(checks))
    failed = [c for c in checks if c.required and not c.ok]
    return 1 if failed else 0


# ─── services / studio commands (Phase 3) ───────────────────────────────

def cmd_audio(args: argparse.Namespace) -> int:
    """Process a raw take into the beat's normalized VO wav + words.json
    (v1 `dl audio` parity). process_take -> beat.audio, transcribe ->
    beat.words, so a subsequent `dl2 compose` picks the new take up."""
    v2_config = _load_v2_config(_find_workspace_root())
    dotted = _resolve_edit_arg(args.edit, v2_config)
    edit = _load_edit(dotted)
    if args.beat_id not in edit.beats:
        raise CliError(
            f"beat {args.beat_id!r} not in edit {edit.name!r}; "
            f"available: {list(edit.beats)}"
        )
    beat = edit.beats[args.beat_id]
    recording = Path(args.recording)
    if not recording.exists():
        raise CliError(f"recording not found: {recording}")

    from dlstudio import services

    audio_out = Path(beat.audio)
    words_out = Path(beat.words)
    result = services.process_take(recording, audio_out)
    services.transcribe(audio_out, words_out, language=args.language, model=args.model)
    print(f"[dl2] audio: {recording} -> {audio_out}")
    print(f"[dl2]   measured input loudness: {result.input_i:.2f} LUFS")
    print(f"[dl2]   duration: {result.duration:.2f}s")
    print(f"[dl2]   words -> {words_out}")
    return 0


def cmd_transcribe(args: argparse.Namespace) -> int:
    """Standalone word-level transcription (no beat/edit context)."""
    wav = Path(args.wav)
    if not wav.exists():
        raise CliError(f"wav not found: {wav}")

    from dlstudio import services

    out = services.transcribe(
        wav, Path(args.out),
        language=args.language, model=args.model, backend=args.backend,
    )
    print(f"[dl2] transcribed {wav} -> {out}")
    return 0


def cmd_scratch_tts(args: argparse.Namespace) -> int:
    """Synthesize a throwaway scratch VO from a beat's `vo` text (or --text
    override) to data/scratch/<beat>_scratch_tts.wav."""
    v2_config = _load_v2_config(_find_workspace_root())
    dotted, beat_id = _resolve_compose_args(args, v2_config)
    edit = _load_edit(dotted)
    if beat_id not in edit.beats:
        raise CliError(
            f"beat {beat_id!r} not in edit {edit.name!r}; available: {list(edit.beats)}"
        )
    beat = edit.beats[beat_id]
    text = args.text if args.text is not None else beat.vo
    if not text or not text.strip():
        raise CliError(
            f"beat {beat_id!r} has no vo text to synthesize (pass --text)"
        )

    from dlstudio import services

    out = Path(f"data/scratch/{beat_id}_scratch_tts.wav")
    services.scratch_tts(text, out)
    print(f"[dl2] scratch tts -> {out}")
    return 0


def cmd_studio(args: argparse.Namespace) -> int:
    """Serve the Studio v2 web backend (127.0.0.1 only)."""
    v2_config = _load_v2_config(_find_workspace_root())
    dotted = _resolve_edit_arg(args.edit, v2_config)

    if args.dev:
        print(
            "[dl2] --dev: run the Vite dev server separately for hot-reload UI:\n"
            "        cd common/dlstudio/webui && npm run dev\n"
            "      then open its URL; it proxies /api/* to this backend."
        )

    try:
        import uvicorn

        from dlstudio.api import create_app
    except ImportError as e:
        raise CliError(
            "the 'studio' extra is not installed. Install it with:\n"
            "        pip install -e 'common/dlstudio[studio]'\n"
            f"      (missing dependency: {e.name})"
        ) from e

    app = create_app(dotted)
    print(f"[dl2] studio: http://127.0.0.1:{args.port}  (edit: {dotted})")
    uvicorn.run(app, host="127.0.0.1", port=args.port)
    return 0


# ─── publish / stock commands (Phase 4 services) ─────────────────────────

def cmd_publish(args: argparse.Namespace) -> int:
    """Generate a youtube_package.md for `edit` (title/description/tags
    placeholders + chapters derived from the compiled Timeline's beat
    placements + beat titles). See services.publish.generate_youtube_package
    for the section shape; this handler only wires CLI args through to it."""
    v2_config = _load_v2_config(_find_workspace_root())
    dotted = _resolve_edit_arg(args.edit, v2_config)
    edit = _load_edit(dotted)

    from dlstudio import compile as dl_compile
    from dlstudio import services

    timeline = dl_compile.build_timeline(edit)
    out_path = Path(args.out) if args.out else Path("data/publish/youtube_package.md")
    result = services.generate_youtube_package(
        edit, out_path=out_path, chapters_from_timeline=timeline,
    )
    print(f"[dl2] youtube package -> {result}")
    return 0


def cmd_stock_search(args: argparse.Namespace) -> int:
    """`dl2 stock search "<query>"` -- thin Pexels/Pixabay wrapper, no edit
    context needed. Writes JSON results to --out, or prints to stdout."""
    from dlstudio import services

    results = services.search(
        args.query, source=args.source, aspect=args.aspect, per_page=args.per_page,
    )
    import json as _json

    payload = _json.dumps([r.to_dict() for r in results], ensure_ascii=False, indent=2)
    if args.out:
        out_path = Path(args.out)
        out_path.parent.mkdir(parents=True, exist_ok=True)
        out_path.write_text(payload, encoding="utf-8")
        print(f"[dl2] stock search: {len(results)} result(s) -> {out_path}")
    else:
        print(payload)
    return 0


def cmd_stock_download(args: argparse.Namespace) -> int:
    """`dl2 stock download <manifest> --out <dir>` -- downloads every result
    in the manifest JSON (produced by `stock search --out`) to --out, and
    writes --out/manifest.json with provenance."""
    from dlstudio import services

    downloaded = services.download(args.manifest, args.out)
    print(f"[dl2] stock download: {len(downloaded)} file(s) -> {args.out}")
    return 0


# ─── argparse wiring ───────────────────────────────────────────────────

def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="dl2", description="Studio v2 CLI")
    parser.add_argument(
        "--debug", action="store_true",
        help="re-raise exceptions with a full traceback instead of a one-line message",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_check = sub.add_parser("check", help="compile the edit and run all checks")
    p_check.add_argument("edit", nargs="?", help="dotted edit module path")
    p_check.set_defaults(func=cmd_check)

    p_ir = sub.add_parser("ir", help="dump the compiled Timeline IR as JSON")
    p_ir.add_argument("edit", nargs="?")
    p_ir.add_argument("--out", help="write JSON to this path instead of stdout")
    p_ir.set_defaults(func=cmd_ir)

    p_compose = sub.add_parser("compose", help="render one beat (cache-aware)")
    p_compose.add_argument("edit_or_beat", help="beat id, or edit module path when beat_id is also given")
    p_compose.add_argument("beat_id", nargs="?")
    _add_render_flags(p_compose)
    p_compose.set_defaults(func=cmd_compose)

    p_iter = sub.add_parser("iter", help="draft-render all/stale beats and assemble")
    p_iter.add_argument("edit", nargs="?")
    p_iter.add_argument("--stale", action="store_true", help="only render cache-miss beats")
    p_iter.add_argument("-j", "--jobs", type=int, default=1, help="parallel worker processes")
    _add_render_flags(p_iter)
    p_iter.set_defaults(func=cmd_iter)

    p_render = sub.add_parser(
        "render", help="full render + mix assemble (default 1080p/standard)")
    p_render.add_argument("edit", nargs="?")
    p_render.add_argument("--stale", action="store_true", help="only render cache-miss beats")
    p_render.add_argument("-j", "--jobs", type=int, default=1, help="parallel worker processes")
    _add_render_flags(p_render)
    p_render.set_defaults(func=cmd_render)

    p_final = sub.add_parser(
        "final", help="shipping render + mix assemble ([v2.final] defaults, else 1080p/upload)")
    p_final.add_argument("edit", nargs="?")
    p_final.add_argument("--stale", action="store_true", help="only render cache-miss beats")
    p_final.add_argument("-j", "--jobs", type=int, default=1, help="parallel worker processes")
    _add_render_flags(p_final)
    p_final.set_defaults(func=cmd_final)

    p_beats = sub.add_parser("beats", help="beat durations / chunk counts / cache status")
    p_beats.add_argument("edit", nargs="?")
    _add_render_flags(p_beats)
    p_beats.set_defaults(func=cmd_beats)

    p_doctor = sub.add_parser("doctor", help="check local dependencies (ffmpeg, python, pydantic, ...)")
    p_doctor.set_defaults(func=cmd_doctor)

    p_audio = sub.add_parser(
        "audio", help="process a raw take -> beat VO wav + words.json (v1 `dl audio` parity)")
    p_audio.add_argument("edit", help="dotted edit module path")
    p_audio.add_argument("beat_id", help="beat whose audio/words to (re)write")
    p_audio.add_argument("recording", help="raw take recording file")
    p_audio.add_argument("--language", default="ru", help="transcription language (default: ru)")
    p_audio.add_argument("--model", default="medium", help="whisper model size (default: medium)")
    p_audio.set_defaults(func=cmd_audio)

    p_transcribe = sub.add_parser(
        "transcribe", help="standalone word-level transcription of a wav")
    p_transcribe.add_argument("wav", help="input wav")
    p_transcribe.add_argument("out", help="output words.json path")
    p_transcribe.add_argument("--language", default="ru", help="language (default: ru)")
    p_transcribe.add_argument("--model", default="medium", help="whisper model size (default: medium)")
    p_transcribe.add_argument(
        "--backend", default="auto", choices=("auto", "whisper", "whisperx"),
        help="transcription backend (default: auto)")
    p_transcribe.set_defaults(func=cmd_transcribe)

    p_scratch = sub.add_parser(
        "scratch-tts", help="synthesize a scratch VO from a beat's vo text")
    p_scratch.add_argument(
        "edit_or_beat", help="beat id, or edit module path when beat_id is also given")
    p_scratch.add_argument("beat_id", nargs="?")
    p_scratch.add_argument("--text", help="override text instead of the beat's vo")
    p_scratch.set_defaults(func=cmd_scratch_tts)

    p_studio = sub.add_parser("studio", help="serve the Studio v2 web backend (127.0.0.1)")
    p_studio.add_argument("edit", nargs="?", help="dotted edit module path")
    p_studio.add_argument("--port", type=int, default=8788, help="port (default: 8788)")
    p_studio.add_argument(
        "--dev", action="store_true", help="print the Vite dev-server hint before serving")
    p_studio.set_defaults(func=cmd_studio)

    p_publish = sub.add_parser(
        "publish", help="generate a YouTube upload package (title/desc/tags/chapters)")
    p_publish.add_argument("edit", nargs="?", help="dotted edit module path")
    p_publish.add_argument(
        "--out", help="output path (default: data/publish/youtube_package.md)")
    p_publish.set_defaults(func=cmd_publish)

    p_stock = sub.add_parser("stock", help="stock b-roll search/download (thin Pexels/Pixabay wrapper)")
    stock_sub = p_stock.add_subparsers(dest="stock_command", required=True)

    p_stock_search = stock_sub.add_parser("search", help="search a stock provider for b-roll")
    p_stock_search.add_argument("query", help="search query")
    p_stock_search.add_argument(
        "--source", default="pexels", choices=("pexels", "pixabay"), help="stock provider (default: pexels)")
    p_stock_search.add_argument("--aspect", default="16:9", help="target aspect ratio (default: 16:9)")
    p_stock_search.add_argument(
        "--per-page", type=int, default=10, dest="per_page", help="max results (default: 10)")
    p_stock_search.add_argument("--out", help="write JSON results to this path instead of stdout")
    p_stock_search.set_defaults(func=cmd_stock_search)

    p_stock_download = stock_sub.add_parser(
        "download", help="download stock assets from a search-results manifest")
    p_stock_download.add_argument("manifest", help="path to a JSON file of search results")
    p_stock_download.add_argument(
        "--out", required=True, help="output directory for downloaded files + manifest.json")
    p_stock_download.set_defaults(func=cmd_stock_download)

    dl_genhtml.add_subparser(sub)
    dl_newvideo.add_subparser(sub)
    dl_verify.add_subparser(sub)

    return parser


def main(argv: list[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)
    try:
        return int(args.func(args) or 0)
    except CliError as e:
        print(f"[dl2] error: {e}", file=sys.stderr)
        if args.debug:
            raise
        return 1
    except Exception as e:
        print(f"[dl2] error: {type(e).__name__}: {e}", file=sys.stderr)
        if args.debug:
            raise
        return 1


if __name__ == "__main__":
    sys.exit(main())
