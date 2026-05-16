"""Devlog CLI — single entry point for the production pipeline.

Usage (from C:\\projects\\devlogs\\):
    python -m devlog.cli <command> [args]

Commands:
    compose <edit> <beat_id>      Render one beat from given edit
    render  <edit> [--beat <id>]  Render all beats in edit.order; --no-concat to skip concat
    concat  <edit>                Concat existing per-beat videos into edit.output
    audio   <edit> <beat_id> <recording_filename>
                                  Process raw recording -> normalized wav + words.json
    transcribe <audio_path> <output_json> [--model medium]
                                  Standalone whisper transcription
    serve <edit>                  Run local web server (recorder + preview)
    cut <video> <start-end> [--reframe MODE] [--out PATH]
                                  Clip range from video, optional 16:9 -> 9:16 reframe

Where <edit> is a Python import path like 'trolley.edits.youtube'.
The CLI auto-detects the project root from the edit module location and runs
each command with cwd set to that root, so paths in beats.py stay relative.
"""
from __future__ import annotations
import sys
import os
import argparse
import importlib
import re
import shutil
import subprocess
from pathlib import Path

from devlog.config import DevlogConfig, load_config


if sys.platform == "win32":
    try:
        sys.stdout.reconfigure(encoding="utf-8")
        sys.stderr.reconfigure(encoding="utf-8")
    except Exception:
        pass


# ─── Edit loading ────────────────────────────────────────────────

def _load_edit(edit_path: str):
    """Import an edit module and return (Edit, project_root).

    `edit_path` is a dotted module path like 'trolley.edits.youtube'.
    Project root is two directories above the edit (edits/<name>/__init__.py
    -> project_root/edits/<name>/ -> project_root).
    """
    mod = importlib.import_module(edit_path)
    if not hasattr(mod, "EDIT"):
        raise SystemExit(f"Module {edit_path} has no EDIT object — "
                         f"expected `EDIT = Edit(...)` in __init__.py")
    edit_file = Path(mod.__file__).resolve()
    project_root = edit_file.parent.parent.parent
    return mod.EDIT, project_root


def _project_chdir(project_root: Path):
    """Switch cwd to the project root so beats.py paths resolve."""
    os.chdir(project_root)
    print(f"[devlog] cwd -> {project_root}")


_WIDTH_PRESETS = {
    "360p":  640,
    "540p":  960,
    "720p":  1280,
    "1080p": 1920,
    "1440p": 2560,
    "4k":    3840,
}

_QUALITY_PRESETS = ("draft", "preview", "upload", "master")


def _resolve_edit(edit_arg: str | None, config: DevlogConfig) -> str:
    edit = edit_arg or config.default_edit
    if not edit:
        raise SystemExit("Edit module is required. Pass it explicitly or set default_edit in devlog.toml.")
    return edit


def _apply_render_defaults(args, config: DevlogConfig, *, for_watch: bool = False) -> None:
    """Fill omitted width/quality/parallel/audio defaults from devlog.toml."""
    defaults = config.watch if for_watch and config.watch else config.defaults
    if getattr(args, "final", False):
        final = config.final
        if getattr(args, "width", None) is None:
            args.width = final.get("width", "4k")
        if getattr(args, "quality", None) is None and not getattr(args, "draft", False):
            args.quality = final.get("quality", "upload")
        if getattr(args, "parallel", None) is None:
            args.parallel = int(final.get("parallel", defaults.get("parallel", 1)))
        if final.get("gpu") and not getattr(args, "gpu", False):
            args.gpu = True
        return

    if getattr(args, "width", None) is None:
        args.width = defaults.get("width")
    if getattr(args, "quality", None) is None and not getattr(args, "draft", False):
        args.quality = defaults.get("quality")
    if hasattr(args, "parallel") and getattr(args, "parallel", None) is None:
        args.parallel = int(defaults.get("parallel", 1))


def _apply_audio_defaults(args, config: DevlogConfig) -> None:
    if getattr(args, "language", None) is None:
        args.language = config.defaults.get("language", "ru")
    if getattr(args, "model", None) is None:
        args.model = config.defaults.get("model", "medium")


def _resize_design(design, width_spec: str | None):
    """Override design.resolution to match `width_spec`, preserving aspect.

    width_spec may be a preset name ('540p', '4k') or raw int.
    Use for fast-iteration renders at 540p / 720p, or final at 4k.
    """
    if not width_spec:
        return design
    import dataclasses
    if width_spec in _WIDTH_PRESETS:
        new_w = _WIDTH_PRESETS[width_spec]
    else:
        try:
            new_w = int(width_spec)
        except ValueError:
            raise SystemExit(f"--width must be int or one of {list(_WIDTH_PRESETS)}, got {width_spec!r}")
    orig_w, orig_h = design.resolution
    new_h = int(round(new_w * orig_h / orig_w))
    # Round to even pixels for libx264
    new_w = (new_w // 2) * 2
    new_h = (new_h // 2) * 2
    return dataclasses.replace(design, resolution=(new_w, new_h))


# ─── Commands ────────────────────────────────────────────────────

def cmd_compose(args):
    """Render a single beat from the edit."""
    config = load_config()
    if args.beat_id is None:
        edit_path = _resolve_edit(None, config)
        beat_id = args.edit_or_beat
    else:
        edit_path = _resolve_edit(args.edit_or_beat, config)
        beat_id = args.beat_id
    _apply_render_defaults(args, config)
    edit, root = _load_edit(edit_path)
    _project_chdir(root)
    if beat_id not in edit.beats:
        raise SystemExit(f"Beat {beat_id!r} not in edit {edit.name!r}. "
                         f"Available: {list(edit.beats)}")
    design = _resize_design(edit.design, args.width)
    beat = edit.beats[beat_id]
    suffix = _render_suffix(args)
    out_path = f"data/finalize/{beat_id}{suffix}.mp4"
    engine = getattr(args, "engine", "ffmpeg")
    quality = _effective_quality(args)
    draft = _effective_draft(args)
    print(f"[devlog] resolution {design.resolution}  fps {design.fps}"
          f"{' DRAFT' if draft else ''}{' GPU' if args.gpu else ''}"
          f"{' quality=' + quality if quality else ''}  engine={engine}")
    if engine == "moviepy":
        from devlog.render import compose
        compose(beat, design, out_path, draft=draft, gpu=args.gpu, no_cache=args.no_cache)
    else:
        from devlog.render.compose_ffmpeg import compose_ffmpeg
        compose_ffmpeg(beat, design, out_path, draft=draft, gpu=args.gpu,
                       no_cache=args.no_cache, quality=quality)


def cmd_render(args):
    """Render all beats in edit.order, then concat (unless --no-concat).

    --parallel N renders N beats concurrently via multiprocessing.
    --draft uses ultrafast x264 preset (4-6x faster, slightly larger files).
    --engine selects ffmpeg (default, fast) or moviepy (legacy fallback).
    """
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    _apply_render_defaults(args, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    design = _resize_design(edit.design, args.width)
    if args.final and not args.skip_final_preflight:
        _run_final_preflight(edit, root, design.W)
    suffix = _render_suffix(args)
    engine = getattr(args, "engine", "ffmpeg")
    quality = _effective_quality(args)
    draft = _effective_draft(args)
    print(f"[devlog] resolution {design.resolution}  fps {design.fps}"
          f"{' DRAFT' if draft else ''}"
          f"{' parallel=' + str(args.parallel) if args.parallel > 1 else ''}"
          f"{' quality=' + quality if quality else ''}"
          f"  engine={engine}")
    targets = [args.beat] if args.beat else edit.order

    if args.parallel > 1 and len(targets) > 1:
        _render_parallel(edit, design, targets, suffix, draft, args.gpu,
                         args.no_cache, args.parallel, engine, quality)
    else:
        for bid in targets:
            out_path = f"data/finalize/{bid}{suffix}.mp4"
            print(f"\n[devlog] rendering {bid} -> {out_path}")
            _render_one(edit.beats[bid], design, out_path, draft, args.gpu,
                        args.no_cache, engine, quality)

    if not args.no_concat and not args.beat:
        _concat(edit, root, suffix=suffix)
        # Auto-review the final concatenated output — catches silent overlay
        # drops that the renderer happily produces but a human would spot.
        # Skip on --no-review; promote warnings to exit code on --strict-review.
        if not args.no_review and suffix == "_video_1080p":
            out = Path(edit.output)
            if out.exists():
                print(f"\n[devlog] reviewing {out}...")
                from devlog.review import review_video
                verdicts = review_video(edit, str(out),
                                        threshold=args.review_threshold,
                                        verbose=False)
                fails = [v for v in verdicts if not v.passed]
                if fails:
                    print(f"\n  ⚠ {len(fails)}/{len(verdicts)} chunks failed visual review:")
                    for v in fails:
                        text = v.spec.text.replace("\n", " / ")[:50]
                        print(f"    [FAIL] {v.spec.beat_id} c{v.spec.chunk_idx} "
                              f"t={v.spec.t_video_mid:.2f}  diff={v.diff:.1f}  {text}")
                    print(f"\n  Run `dl review {args.edit} {out}` for full report.")
                    if args.strict_review:
                        raise SystemExit(1)
                else:
                    print(f"  ✓ {len(verdicts)}/{len(verdicts)} chunks render correctly")


def _run_final_preflight(edit, root: Path, target_width: int) -> None:
    """Block final renders on structural errors or missing assets."""
    from devlog.assets import asset_report
    from devlog.check import check_edit

    issues = check_edit(edit, root, deep=True)
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    report = asset_report(edit, root, target_width=target_width)
    print(f"[final] preflight: {len(errors)} errors, {len(warnings)} warnings, "
          f"{len(report.missing)} missing assets, {len(report.low_res)} low-res images")
    if report.low_res:
        print("[final] low-res images are quality warnings; render may still continue.")
    if errors:
        for issue in errors[:10]:
            print(f"[final] ERROR {issue.code}: {issue.message}")
    if report.missing:
        for path in report.missing[:10]:
            print(f"[final] MISSING {path}")
    if errors or report.missing:
        raise SystemExit("Final preflight failed. Fix errors/missing assets or pass --skip-final-preflight.")


def _effective_quality(args) -> str | None:
    if getattr(args, "draft", False) and getattr(args, "quality", None) not in (None, "draft"):
        raise SystemExit("--draft conflicts with --quality; use --quality draft instead")
    q = getattr(args, "quality", None)
    if q:
        return q
    if getattr(args, "draft", False):
        return "draft"
    return None


def _effective_draft(args) -> bool:
    return bool(getattr(args, "draft", False) or getattr(args, "quality", None) == "draft")


def _render_suffix(args) -> str:
    """Derive output filename suffix from width / draft flags."""
    quality = _effective_quality(args)
    parts = []
    if args.width:
        parts.append(f"_{_WIDTH_PRESETS.get(args.width, args.width)}w")
    if _effective_draft(args):
        parts.append("_draft")
    elif quality:
        parts.append(f"_{quality}")
    if not parts:
        return "_video_1080p"
    return "".join(parts)


def _render_one(beat, design, out_path: str, draft: bool, gpu: bool,
                no_cache: bool, engine: str = "ffmpeg", quality: str | None = None):
    """Single beat render — engine-aware. Top-level (picklable for Windows spawn)."""
    if engine == "moviepy":
        from devlog.render import compose
        compose(beat, design, out_path, draft=draft, gpu=gpu, no_cache=no_cache)
    else:
        from devlog.render.compose_ffmpeg import compose_ffmpeg
        compose_ffmpeg(beat, design, out_path, draft=draft, gpu=gpu,
                       no_cache=no_cache, quality=quality)
    return out_path


def _render_parallel(edit, design, targets: list[str], suffix: str,
                     draft: bool, gpu: bool, no_cache: bool, n_workers: int,
                     engine: str = "ffmpeg", quality: str | None = None):
    """Run beat renders concurrently. Each worker is its own Python process."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    print(f"[devlog] launching {n_workers} workers for {len(targets)} beats (engine={engine})")
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futures = {}
        for bid in targets:
            out_path = f"data/finalize/{bid}{suffix}.mp4"
            fut = pool.submit(_render_one, edit.beats[bid], design, out_path,
                              draft, gpu, no_cache, engine, quality)
            futures[fut] = bid
        for fut in as_completed(futures):
            bid = futures[fut]
            try:
                fut.result()
                print(f"[devlog] [OK] {bid}")
            except Exception as e:
                print(f"[devlog] [FAIL] {bid}: {e}")
                raise


def cmd_concat(args):
    """Concatenate per-beat videos into edit.output."""
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    _apply_render_defaults(args, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    suffix = _render_suffix(args)
    _concat(edit, root, suffix=suffix)


def _concat(edit, root: Path, suffix: str = "_video_1080p"):
    """Internal: build concat manifest and run ffmpeg."""
    manifest = Path("data/finalize/_concat.txt")
    manifest.parent.mkdir(parents=True, exist_ok=True)
    lines = []
    missing = []
    for bid in edit.order:
        path = (root / f"data/finalize/{bid}{suffix}.mp4").resolve()
        if not path.exists():
            missing.append(str(path))
            continue
        lines.append(f"file '{path.as_posix()}'")
    if missing:
        raise SystemExit(f"Missing rendered beats: {missing}. "
                         f"Run `devlog render {edit.name}` first.")
    manifest.write_text("\n".join(lines) + "\n", encoding="utf-8")
    # If using a non-default suffix, append it to the output filename so
    # different-resolution renders don't overwrite each other.
    out = edit.output
    if suffix != "_video_1080p":
        out_path = Path(out)
        out = str(out_path.with_stem(out_path.stem + suffix))
    # Two-step concat: demuxer with stream-copy video + audio re-encode.
    # Why: demuxer concat + `-c copy` audio produces a duplicated audio
    # stream (363s on 247s video) due to non-monotonic DTS in our
    # ffmpeg-engine beats. Forcing `-c:a aac` re-encodes audio (fixing
    # timestamps via re-decode) while keeping video as a stream copy
    # — saves the ~30s video re-encode that the previous filter-graph
    # approach incurred.
    n = len(lines)
    print(f"[devlog] concat manifest: {manifest} ({n} beats, stream-copy concat)")
    print(f"[devlog] writing {out}...")
    # Stream-copy both streams. Works because compose_ffmpeg now forces
    # 48kHz audio output for all beats — previously, mixed sample rates
    # (e.g. outro at 96kHz) broke demuxer concat by causing audio packets
    # to be timestamped inconsistently. Result: ~5s concat instead of
    # ~30s filter-graph re-encode.
    subprocess.run([
        "ffmpeg", "-y",
        "-f", "concat", "-safe", "0",
        "-i", str(manifest),
        "-c", "copy",
        out,
    ], check=True)
    print(f"[devlog] done -> {out}")


def cmd_audio(args):
    """Process a raw recording -> normalized wav + words.json for a beat."""
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    _apply_audio_defaults(args, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.audio.process import process_beat_audio
    process_beat_audio(
        args.beat_id,
        args.recording_filename,
        whisper_model=args.model,
        language=args.language,
        insecure_ssl=args.insecure_ssl,
    )


def cmd_transcribe(args):
    """Standalone whisper transcription (no beat context required)."""
    config = load_config()
    _apply_audio_defaults(args, config)
    from devlog.audio.transcribe import transcribe
    transcribe(args.audio_path, args.output_json,
               model_size=args.model,
               language=args.language,
               insecure_ssl=args.insecure_ssl)


def cmd_serve(args):
    """Start local web server for recorder + preview."""
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.web.serve import serve
    serve(edit, port=args.port, edit_path=args.edit)


def cmd_cut(args):
    """Clip a time range from a video, optionally reframing 16:9 -> 9:16."""
    from devlog.cut import cut_range
    cut_range(args.video, args.range, out_path=args.out, reframe=args.reframe)


def cmd_watch(args):
    """Auto-rerender on source changes. Polls mtimes; on change spawns a
    fresh `check` + `render` subprocess (clean module reimport). Cache makes
    unchanged beats nearly instant.
    """
    import time
    import subprocess
    import importlib
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    _apply_render_defaults(args, config, for_watch=True)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    beats_mod = importlib.import_module(args.edit + ".beats")
    design_mod = importlib.import_module(args.edit + ".design")
    common_root = Path(__file__).parent
    watched = [
        Path(beats_mod.__file__).resolve(),
        Path(design_mod.__file__).resolve(),
        common_root / "types.py",
        common_root / "render" / "compose_ffmpeg.py",
        common_root / "render" / "plate.py",
        common_root / "render" / "overlay.py",
        common_root / "render" / "image.py",
        common_root / "render" / "text.py",
        common_root / "render" / "effects.py",
    ]
    watched = [p for p in watched if p.exists()]
    print("[watch] watching:")
    for p in watched:
        print(f"  {p}")

    def run_render():
        if not args.no_check:
            check_cmd = [sys.executable, "-m", "devlog", "check", args.edit]
            if args.deep_check:
                check_cmd.append("--deep")
            check_result = subprocess.run(check_cmd, check=False)
            if check_result.returncode != 0:
                print("[watch] check failed; skipping render")
                return

        cmd = [sys.executable, "-m", "devlog", "render", args.edit,
               "--width", args.width]
        if args.beat:
            cmd += ["--beat", args.beat]
        if args.draft: cmd.append("--draft")
        if args.quality: cmd += ["--quality", args.quality]
        if args.gpu: cmd.append("--gpu")
        if args.parallel > 1: cmd += ["-j", str(args.parallel)]
        cmd.append("--no-concat")
        subprocess.run(cmd, check=False)

    print("[watch] initial render...")
    run_render()
    last_mtimes = {p: p.stat().st_mtime for p in watched}
    print("[watch] ready — edit watched files to trigger rebuild. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
            changed = []
            for p in watched:
                try:
                    m = p.stat().st_mtime
                except OSError:
                    continue
                if m != last_mtimes[p]:
                    changed.append(p)
                    last_mtimes[p] = m
            if changed:
                names = ", ".join(p.name for p in changed)
                print(f"\n[watch] changed: {names} — rebuilding")
                run_render()
    except KeyboardInterrupt:
        print("\n[watch] stopped")


def cmd_cache_clear(args):
    """Wipe the render cache (data/finalize/.cache/)."""
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.cache import clear_cache
    n = clear_cache()
    print(f"[devlog] cleared {n} cache entries")


def _format_bytes(n: int) -> str:
    units = ["B", "KB", "MB", "GB"]
    value = float(n)
    for unit in units:
        if value < 1024 or unit == units[-1]:
            return f"{value:.1f} {unit}" if unit != "B" else f"{int(value)} B"
        value /= 1024
    return f"{n} B"


def cmd_cache_info(args):
    """Show render cache size and entry count."""
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.cache import cache_info
    info = cache_info()
    print(f"cache entries: {info.entries}")
    print(f"cache size: {_format_bytes(info.total_bytes)}")


def cmd_cache_prune(args):
    """Remove old render cache entries."""
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.cache import prune_cache
    removed = prune_cache(args.older_than_days)
    print(f"[devlog] pruned {removed} cache entries older than {args.older_than_days:g} days")


def cmd_review(args):
    """Chunk-aware visual review of a rendered video."""
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.review import review_video
    print(f"[devlog] reviewing {args.video} against {args.edit}")
    verdicts = review_video(edit, args.video, threshold=args.threshold)
    fails = sum(1 for v in verdicts if not v.passed)
    if args.strict and fails:
        raise SystemExit(1)


def cmd_check(args):
    """Validate an edit before rendering."""
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.check import check_edit, format_issues
    issues = check_edit(edit, root, deep=args.deep)
    print(format_issues(issues))
    errors = [i for i in issues if i.severity == "error"]
    warnings = [i for i in issues if i.severity == "warning"]
    print(f"[devlog] check: {len(errors)} errors, {len(warnings)} warnings")
    if errors or (warnings and args.warnings_as_errors):
        raise SystemExit(1)


def cmd_doctor(args):
    """Check local dependencies needed by the pipeline."""
    from devlog.doctor import format_doctor, run_doctor
    checks = run_doctor(with_whisper=args.with_whisper)
    print(format_doctor(checks))
    failed = [c for c in checks if c.required and not c.ok]
    if failed:
        raise SystemExit(1)


def cmd_beats(args):
    """Print beat durations and render status for an edit."""
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    _apply_render_defaults(args, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.timeline import format_summaries, summarize_edit
    suffix = _render_suffix(args)
    summaries = summarize_edit(edit, root, suffix=suffix)
    print(format_summaries(summaries))
    if args.missing_only:
        missing = [s.output for s in summaries if not s.rendered]
        if missing:
            print("\nmissing renders:")
            for path in missing:
                print(f"  {path}")


def cmd_smoke(args):
    """Run a fast workspace self-test."""
    from devlog.smoke import format_smoke, run_smoke
    config = load_config()
    steps = run_smoke(config, skip_tests=args.skip_tests, deep_check=args.deep_check)
    print(format_smoke(steps))
    if any(step.returncode != 0 for step in steps):
        raise SystemExit(1)


def cmd_assets(args):
    """Show used/missing/unused assets for an edit."""
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.assets import asset_report, format_asset_report
    design = _resize_design(edit.design, args.width)
    report = asset_report(edit, root, target_width=design.W)
    print(format_asset_report(report, show_used=args.show_used, show_unused=args.show_unused))
    if report.missing and args.strict:
        raise SystemExit(1)


def _write_or_print(text: str, out_path: str | None) -> None:
    if out_path:
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text(text, encoding="utf-8")
        print(f"[devlog] wrote {out_path}")
    else:
        try:
            sys.stdout.write(text)
        except BrokenPipeError:
            pass


def cmd_script(args):
    """Export voiceover script as Markdown."""
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.export import script_markdown
    _write_or_print(script_markdown(edit), args.out)


def cmd_shotlist(args):
    """Export chunk/scene shotlist as Markdown."""
    config = load_config()
    args.edit = _resolve_edit(args.edit, config)
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.export import shotlist_markdown
    _write_or_print(shotlist_markdown(edit), args.out)


def _py_ident(value: str, what: str) -> str:
    if not re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", value):
        raise SystemExit(f"{what} must be a valid Python identifier, got {value!r}")
    return value


def _write_file(path: Path, content: str, force: bool) -> None:
    if path.exists() and not force:
        raise SystemExit(f"Refusing to overwrite existing file: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def cmd_new(args):
    """Create a minimal new devlog project scaffold."""
    project = _py_ident(args.project, "project")
    edit_name = _py_ident(args.edit, "edit")
    root = Path.cwd() / project
    if root.exists() and any(root.iterdir()) and not args.force:
        raise SystemExit(f"{root} already exists. Use --force to overwrite template files.")

    const_prefix = re.sub(r"[^A-Za-z0-9_]", "_", project).upper()
    for d in [
        root / "data" / "finalize",
        root / "data" / "recordings",
        root / "data" / "review",
        root / "shared",
        root / "edits" / edit_name,
    ]:
        d.mkdir(parents=True, exist_ok=True)

    _write_file(root / "__init__.py", '"""Devlog project package."""\n', args.force)
    _write_file(root / "shared" / "__init__.py", "", args.force)
    _write_file(root / "edits" / "__init__.py", "", args.force)
    _write_file(root / "shared" / "palette.py", f'''"""Brand palette and fonts for {project}."""
from devlog.types import Palette, Fonts


{const_prefix}_PALETTE = Palette(
    bg=(26, 22, 18),
    gold=(232, 182, 71),
    gold_dim=(224, 174, 69),
    red=(192, 57, 43),
    fg_dim=(180, 170, 150),
)

{const_prefix}_FONTS = Fonts(
    display="C:/Windows/Fonts/bahnschrift.ttf",
    text="C:/Windows/Fonts/tahomabd.ttf",
    mono="C:/Windows/Fonts/consolab.ttf",
    emoji="C:/Windows/Fonts/seguiemj.ttf",
)
''', args.force)
    _write_file(root / "edits" / edit_name / "design.py", f'''"""Design for the {edit_name} edit."""
from devlog.types import Design
from {project}.shared.palette import {const_prefix}_PALETTE, {const_prefix}_FONTS


DESIGN = Design(
    resolution=(1920, 1080),
    fps=30,
    palette={const_prefix}_PALETTE,
    fonts={const_prefix}_FONTS,
)
''', args.force)
    _write_file(root / "edits" / edit_name / "beats.py", '''"""Beat plan for this edit."""
from devlog.types import Beat, Chunk


BEATS: dict[str, Beat] = {
    "intro": Beat(
        title="Intro",
        vo="Replace this with your recorded voiceover text.",
        stage="Record this take in the studio, then run dl audio.",
        audio="data/finalize/intro_audio_final.wav",
        words="data/finalize/intro_words.json",
        chunks=[
            Chunk(words=(0, 4), kind="plate", text="INTRO", size=260, red_underline=True),
        ],
        face="none",
    ),
}

CONCAT_ORDER: list[str] = ["intro"]
OUTPUT = "data/finalize/iter01.mp4"
''', args.force)
    _write_file(root / "edits" / edit_name / "__init__.py", f'''from devlog.types import Edit
from .design import DESIGN
from .beats import BEATS, CONCAT_ORDER, OUTPUT


EDIT = Edit(name="{edit_name}", design=DESIGN, beats=BEATS, order=CONCAT_ORDER, output=OUTPUT)
''', args.force)
    _write_file(root / "README.md", f'''# {project}

New devlog project scaffold.

Next steps:

1. Record voiceover with `dl serve {project}.edits.{edit_name}`.
2. Process a take with `dl audio {project}.edits.{edit_name} intro <take>.webm`.
3. Replace chunks in `{project}/edits/{edit_name}/beats.py`.
4. Run `dl check {project}.edits.{edit_name}` before rendering.
5. Render drafts with `dl render {project}.edits.{edit_name} --width 540p --quality draft -j 6`.
''', args.force)
    source_agents = Path.cwd() / "trolley" / ".claude" / "agents"
    target_agents = root / ".claude" / "agents"
    if source_agents.exists():
        target_agents.mkdir(parents=True, exist_ok=True)
        for agent_name in ("vo-reviewer.md", "video-reviewer.md"):
            src = source_agents / agent_name
            dst = target_agents / agent_name
            if src.exists() and (args.force or not dst.exists()):
                shutil.copyfile(src, dst)
    print(f"[devlog] created {root}")
    print(f"[devlog] edit module: {project}.edits.{edit_name}")


# ─── Argparse setup ──────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devlog", description="Reusable video production pipeline.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    width_help = ("Override render width (preset 540p/720p/1080p/4k or raw int). "
                  "Use 540p for fast iteration, 4k for final.")
    draft_help = "Use libx264 ultrafast preset + CRF 28 (4-6x faster encode, slightly larger file)"
    quality_help = "Render quality preset: draft, preview, upload, or master"
    gpu_help = "Use h264_nvenc (NVIDIA GPU) instead of libx264 — 5-10x faster encode on RTX/etc"
    nocache_help = "Force re-render even if content hash matches a cached file"
    parallel_help = ("Render N beats concurrently via multiprocessing. "
                     "Recommended 4-6 on 8-core CPU.")

    p_compose = sub.add_parser("compose", help="Render one beat")
    p_compose.add_argument("edit_or_beat", help="Beat id, or edit module path when beat_id is also provided")
    p_compose.add_argument("beat_id", nargs="?")
    p_compose.add_argument("--width", help=width_help)
    p_compose.add_argument("--draft", action="store_true", help=draft_help)
    p_compose.add_argument("--quality", choices=_QUALITY_PRESETS, help=quality_help)
    p_compose.add_argument("--gpu", action="store_true", help=gpu_help)
    p_compose.add_argument("--no-cache", action="store_true", help=nocache_help)
    p_compose.add_argument("--engine", choices=["ffmpeg", "moviepy"], default="ffmpeg",
                            help="Render engine: ffmpeg (default, fast) or moviepy (legacy)")
    p_compose.set_defaults(func=cmd_compose)

    p_render = sub.add_parser("render", help="Render all beats and concat")
    p_render.add_argument("edit", nargs="?")
    p_render.add_argument("--beat", help="Render only this single beat (skips concat)")
    p_render.add_argument("--no-concat", action="store_true", help="Skip final concat step")
    p_render.add_argument("--width", help=width_help)
    p_render.add_argument("--draft", action="store_true", help=draft_help)
    p_render.add_argument("--quality", choices=_QUALITY_PRESETS, help=quality_help)
    p_render.add_argument("--final", action="store_true",
                          help="Use final render defaults from devlog.toml")
    p_render.add_argument("--skip-final-preflight", action="store_true",
                          help="Skip check --deep and asset preflight for --final")
    p_render.add_argument("--gpu", action="store_true", help=gpu_help)
    p_render.add_argument("--no-cache", action="store_true", help=nocache_help)
    p_render.add_argument("--parallel", "-j", type=int, default=None, help=parallel_help)
    p_render.add_argument("--engine", choices=["ffmpeg", "moviepy"], default="ffmpeg",
                           help="Render engine: ffmpeg (default, fast) or moviepy (legacy)")
    p_render.add_argument("--no-review", action="store_true",
                          help="Skip chunk-aware visual review of the concatenated output")
    p_render.add_argument("--strict-review", action="store_true",
                          help="Exit 1 if any chunk fails visual review (for CI gates)")
    p_render.add_argument("--review-threshold", type=float, default=35.0,
                          help="Max diff for chunk to count as rendered correctly (default 35)")
    p_render.set_defaults(func=cmd_render)

    p_concat = sub.add_parser("concat", help="Concat existing rendered beats into edit.output")
    p_concat.add_argument("edit", nargs="?")
    p_concat.add_argument("--width", help="Match suffix of beat videos to concat (e.g. 540p)")
    p_concat.add_argument("--quality", choices=_QUALITY_PRESETS, help="Match quality suffix of beat videos")
    p_concat.add_argument("--draft", action="store_true", help="Match draft suffix")
    p_concat.set_defaults(func=cmd_concat)

    p_audio = sub.add_parser("audio", help="Process a recording -> wav + words.json")
    p_audio.add_argument("edit")
    p_audio.add_argument("beat_id")
    p_audio.add_argument("recording_filename", help="Filename inside data/recordings/")
    p_audio.add_argument("--model", help="Whisper model size")
    p_audio.add_argument("--language", help="Whisper language code")
    p_audio.add_argument("--insecure-ssl", action="store_true",
                         help="Disable SSL verification for first-time Whisper model download")
    p_audio.set_defaults(func=cmd_audio)

    p_transcribe = sub.add_parser("transcribe", help="Standalone whisper transcription")
    p_transcribe.add_argument("audio_path")
    p_transcribe.add_argument("output_json")
    p_transcribe.add_argument("--model", help="Whisper model size")
    p_transcribe.add_argument("--language", help="Whisper language code")
    p_transcribe.add_argument("--insecure-ssl", action="store_true",
                              help="Disable SSL verification for first-time Whisper model download")
    p_transcribe.set_defaults(func=cmd_transcribe)

    p_serve = sub.add_parser("serve", help="Run local web server (recorder + preview)")
    p_serve.add_argument("edit", nargs="?")
    p_serve.add_argument("--port", type=int, default=8080)
    p_serve.set_defaults(func=cmd_serve)

    p_cut = sub.add_parser("cut", help="Clip time range from a video, optional reframe")
    p_cut.add_argument("video")
    p_cut.add_argument("range", help="Time range like 2:55-3:18 or 175-198 (seconds)")
    p_cut.add_argument("--reframe", choices=["none", "crop_center", "blur_pad", "letterbox"],
                       default="none")
    p_cut.add_argument("--out", required=True)
    p_cut.set_defaults(func=cmd_cut)

    p_watch = sub.add_parser("watch", help="Auto-rebuild on beats.py change (uses cache for speed)")
    p_watch.add_argument("edit", nargs="?")
    p_watch.add_argument("--beat", help="Render only this beat on changes")
    p_watch.add_argument("--width", help=width_help)
    p_watch.add_argument("--draft", action="store_true", help=draft_help)
    p_watch.add_argument("--quality", choices=_QUALITY_PRESETS, help=quality_help)
    p_watch.add_argument("--gpu", action="store_true", help=gpu_help)
    p_watch.add_argument("--parallel", "-j", type=int, default=None, help=parallel_help)
    p_watch.add_argument("--no-check", action="store_true", help="Skip check before rendering")
    p_watch.add_argument("--deep-check", action="store_true", help="Run `check --deep` before rendering")
    p_watch.set_defaults(func=cmd_watch)

    p_cc = sub.add_parser("cache-clear", help="Wipe the render cache")
    p_cc.add_argument("edit", nargs="?")
    p_cc.set_defaults(func=cmd_cache_clear)

    p_ci = sub.add_parser("cache-info", help="Show render cache size")
    p_ci.add_argument("edit", nargs="?")
    p_ci.set_defaults(func=cmd_cache_info)

    p_cp = sub.add_parser("cache-prune", help="Remove old render cache entries")
    p_cp.add_argument("edit", nargs="?")
    p_cp.add_argument("--older-than-days", type=float, required=True)
    p_cp.set_defaults(func=cmd_cache_prune)

    p_review = sub.add_parser("review", help="Chunk-aware visual review of rendered video")
    p_review.add_argument("edit", help="Edit module path (e.g. trolley.edits.youtube)")
    p_review.add_argument("video", help="Path to rendered .mp4 (relative to project root)")
    p_review.add_argument("--threshold", type=float, default=35.0,
                          help="Max mean abs RGB diff in band region for PASS (default 35)")
    p_review.add_argument("--strict", action="store_true",
                          help="Exit 1 on any FAIL (for CI gates)")
    p_review.set_defaults(func=cmd_review)

    p_check = sub.add_parser("check", help="Validate an edit before rendering")
    p_check.add_argument("edit", nargs="?")
    p_check.add_argument("--deep", action="store_true",
                         help="Also ffprobe video durations to catch offsets past EOF")
    p_check.add_argument("--warnings-as-errors", action="store_true")
    p_check.set_defaults(func=cmd_check)

    p_doctor = sub.add_parser("doctor", help="Check local ffmpeg/python dependencies")
    p_doctor.add_argument("--with-whisper", action="store_true",
                          help="Also check that the Whisper package is importable")
    p_doctor.set_defaults(func=cmd_doctor)

    p_beats = sub.add_parser("beats", help="Show beat durations and render status")
    p_beats.add_argument("edit", nargs="?")
    p_beats.add_argument("--width", help="Match render suffix width (e.g. 540p)")
    p_beats.add_argument("--quality", choices=_QUALITY_PRESETS, help="Match render suffix quality")
    p_beats.add_argument("--draft", action="store_true", help="Match draft suffix")
    p_beats.add_argument("--missing-only", action="store_true", help="Also list missing rendered files")
    p_beats.set_defaults(func=cmd_beats)

    p_smoke = sub.add_parser("smoke", help="Run tests + check + beats for quick self-test")
    p_smoke.add_argument("--skip-tests", action="store_true", help="Only run check and beats")
    p_smoke.add_argument("--deep-check", action="store_true", help="Run check --deep")
    p_smoke.set_defaults(func=cmd_smoke)

    p_assets = sub.add_parser("assets", help="Show used/missing/unused assets")
    p_assets.add_argument("edit", nargs="?")
    p_assets.add_argument("--width", help="Target width for low-res image warnings")
    p_assets.add_argument("--show-used", action="store_true")
    p_assets.add_argument("--show-unused", action="store_true")
    p_assets.add_argument("--strict", action="store_true", help="Exit 1 when assets are missing")
    p_assets.set_defaults(func=cmd_assets)

    p_script = sub.add_parser("script", help="Export VO script markdown")
    p_script.add_argument("edit", nargs="?")
    p_script.add_argument("--out", help="Write markdown to this path instead of stdout")
    p_script.set_defaults(func=cmd_script)

    p_shotlist = sub.add_parser("shotlist", help="Export chunk/scene shotlist markdown")
    p_shotlist.add_argument("edit", nargs="?")
    p_shotlist.add_argument("--out", help="Write markdown to this path instead of stdout")
    p_shotlist.set_defaults(func=cmd_shotlist)

    p_new = sub.add_parser("new", help="Create a new devlog project scaffold")
    p_new.add_argument("project", help="Python package name for the project")
    p_new.add_argument("--edit", default="youtube", help="Initial edit folder/module name")
    p_new.add_argument("--force", action="store_true", help="Overwrite template files if they exist")
    p_new.set_defaults(func=cmd_new)

    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
