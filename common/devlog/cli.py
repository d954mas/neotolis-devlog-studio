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
import subprocess
from pathlib import Path


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
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    if args.beat_id not in edit.beats:
        raise SystemExit(f"Beat {args.beat_id!r} not in edit {edit.name!r}. "
                         f"Available: {list(edit.beats)}")
    design = _resize_design(edit.design, args.width)
    beat = edit.beats[args.beat_id]
    suffix = _render_suffix(args)
    out_path = f"data/finalize/{args.beat_id}{suffix}.mp4"
    engine = getattr(args, "engine", "ffmpeg")
    print(f"[devlog] resolution {design.resolution}  fps {design.fps}"
          f"{' DRAFT' if args.draft else ''}{' GPU' if args.gpu else ''}  engine={engine}")
    if engine == "moviepy":
        from devlog.render import compose
        compose(beat, design, out_path, draft=args.draft, gpu=args.gpu, no_cache=args.no_cache)
    else:
        from devlog.render.compose_ffmpeg import compose_ffmpeg
        compose_ffmpeg(beat, design, out_path, draft=args.draft, gpu=args.gpu, no_cache=args.no_cache)


def cmd_render(args):
    """Render all beats in edit.order, then concat (unless --no-concat).

    --parallel N renders N beats concurrently via multiprocessing.
    --draft uses ultrafast x264 preset (4-6x faster, slightly larger files).
    --engine selects ffmpeg (default, fast) or moviepy (legacy fallback).
    """
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    design = _resize_design(edit.design, args.width)
    suffix = _render_suffix(args)
    engine = getattr(args, "engine", "ffmpeg")
    print(f"[devlog] resolution {design.resolution}  fps {design.fps}"
          f"{' DRAFT' if args.draft else ''}"
          f"{' parallel=' + str(args.parallel) if args.parallel > 1 else ''}"
          f"  engine={engine}")
    targets = [args.beat] if args.beat else edit.order

    if args.parallel > 1 and len(targets) > 1:
        _render_parallel(edit, design, targets, suffix, args.draft, args.gpu,
                         args.no_cache, args.parallel, engine)
    else:
        for bid in targets:
            out_path = f"data/finalize/{bid}{suffix}.mp4"
            print(f"\n[devlog] rendering {bid} -> {out_path}")
            _render_one(edit.beats[bid], design, out_path, args.draft, args.gpu,
                        args.no_cache, engine)

    if not args.no_concat and not args.beat:
        _concat(edit, root, suffix=suffix)


def _render_suffix(args) -> str:
    """Derive output filename suffix from width / draft flags."""
    parts = []
    if args.width:
        parts.append(f"_{_WIDTH_PRESETS.get(args.width, args.width)}w")
    if args.draft:
        parts.append("_draft")
    if not parts:
        return "_video_1080p"
    return "".join(parts)


def _render_one(beat, design, out_path: str, draft: bool, gpu: bool,
                no_cache: bool, engine: str = "ffmpeg"):
    """Single beat render — engine-aware. Top-level (picklable for Windows spawn)."""
    if engine == "moviepy":
        from devlog.render import compose
        compose(beat, design, out_path, draft=draft, gpu=gpu, no_cache=no_cache)
    else:
        from devlog.render.compose_ffmpeg import compose_ffmpeg
        compose_ffmpeg(beat, design, out_path, draft=draft, gpu=gpu, no_cache=no_cache)
    return out_path


def _render_parallel(edit, design, targets: list[str], suffix: str,
                     draft: bool, gpu: bool, no_cache: bool, n_workers: int,
                     engine: str = "ffmpeg"):
    """Run beat renders concurrently. Each worker is its own Python process."""
    from concurrent.futures import ProcessPoolExecutor, as_completed
    print(f"[devlog] launching {n_workers} workers for {len(targets)} beats (engine={engine})")
    with ProcessPoolExecutor(max_workers=n_workers) as pool:
        futures = {}
        for bid in targets:
            out_path = f"data/finalize/{bid}{suffix}.mp4"
            fut = pool.submit(_render_one, edit.beats[bid], design, out_path,
                              draft, gpu, no_cache, engine)
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
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    suffix = f"_{_WIDTH_PRESETS.get(args.width, args.width)}w" if args.width else "_video_1080p"
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
    print(f"[devlog] concat manifest: {manifest} ({len(lines)} beats)")
    print(f"[devlog] writing {out}...")
    subprocess.run([
        "ffmpeg", "-y", "-f", "concat", "-safe", "0",
        "-i", str(manifest), "-c", "copy", out,
    ], check=True)
    print(f"[devlog] done -> {out}")


def cmd_audio(args):
    """Process a raw recording -> normalized wav + words.json for a beat."""
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.audio.process import process_beat_audio
    process_beat_audio(args.beat_id, args.recording_filename)


def cmd_transcribe(args):
    """Standalone whisper transcription (no beat context required)."""
    from devlog.audio.transcribe import transcribe
    transcribe(args.audio_path, args.output_json, model_size=args.model)


def cmd_serve(args):
    """Start local web server for recorder + preview."""
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.web.serve import serve
    serve(edit, port=args.port)


def cmd_cut(args):
    """Clip a time range from a video, optionally reframing 16:9 -> 9:16."""
    from devlog.cut import cut_range
    cut_range(args.video, args.range, out_path=args.out, reframe=args.reframe)


def cmd_watch(args):
    """Auto-rerender on beats.py change. Polls mtime; on change spawns a
    fresh `render` subprocess (clean module reimport). Cache makes
    unchanged beats nearly instant.
    """
    import time
    import subprocess
    import importlib
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    mod = importlib.import_module(args.edit + ".beats")
    beats_file = Path(mod.__file__).resolve()
    print(f"[watch] watching {beats_file}")

    def run_render():
        cmd = [sys.executable, "-m", "devlog", "render", args.edit,
               "--width", args.width or "540p"]
        if args.draft: cmd.append("--draft")
        if args.gpu: cmd.append("--gpu")
        if args.parallel > 1: cmd += ["-j", str(args.parallel)]
        cmd.append("--no-concat")
        subprocess.run(cmd, check=False)

    print("[watch] initial render...")
    run_render()
    last_mtime = beats_file.stat().st_mtime
    print(f"[watch] ready — edit {beats_file.name} to trigger rebuild. Ctrl+C to stop.")
    try:
        while True:
            time.sleep(1)
            try:
                m = beats_file.stat().st_mtime
            except OSError:
                continue
            if m != last_mtime:
                print(f"\n[watch] {beats_file.name} changed — rebuilding")
                run_render()
                last_mtime = m
    except KeyboardInterrupt:
        print("\n[watch] stopped")


def cmd_cache_clear(args):
    """Wipe the render cache (data/finalize/.cache/)."""
    edit, root = _load_edit(args.edit)
    _project_chdir(root)
    from devlog.cache import clear_cache
    n = clear_cache()
    print(f"[devlog] cleared {n} cache entries")


# ─── Argparse setup ──────────────────────────────────────────────

def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="devlog", description="Reusable video production pipeline.")
    sub = parser.add_subparsers(dest="cmd", required=True)

    width_help = ("Override render width (preset 540p/720p/1080p/4k or raw int). "
                  "Use 540p for fast iteration, 4k for final.")
    draft_help = "Use libx264 ultrafast preset + CRF 28 (4-6x faster encode, slightly larger file)"
    gpu_help = "Use h264_nvenc (NVIDIA GPU) instead of libx264 — 5-10x faster encode on RTX/etc"
    nocache_help = "Force re-render even if content hash matches a cached file"
    parallel_help = ("Render N beats concurrently via multiprocessing. "
                     "Recommended 4-6 on 8-core CPU.")

    p_compose = sub.add_parser("compose", help="Render one beat")
    p_compose.add_argument("edit", help="Edit module path (e.g. trolley.edits.youtube)")
    p_compose.add_argument("beat_id")
    p_compose.add_argument("--width", help=width_help)
    p_compose.add_argument("--draft", action="store_true", help=draft_help)
    p_compose.add_argument("--gpu", action="store_true", help=gpu_help)
    p_compose.add_argument("--no-cache", action="store_true", help=nocache_help)
    p_compose.add_argument("--engine", choices=["ffmpeg", "moviepy"], default="ffmpeg",
                            help="Render engine: ffmpeg (default, fast) or moviepy (legacy)")
    p_compose.set_defaults(func=cmd_compose)

    p_render = sub.add_parser("render", help="Render all beats and concat")
    p_render.add_argument("edit")
    p_render.add_argument("--beat", help="Render only this single beat (skips concat)")
    p_render.add_argument("--no-concat", action="store_true", help="Skip final concat step")
    p_render.add_argument("--width", help=width_help)
    p_render.add_argument("--draft", action="store_true", help=draft_help)
    p_render.add_argument("--gpu", action="store_true", help=gpu_help)
    p_render.add_argument("--no-cache", action="store_true", help=nocache_help)
    p_render.add_argument("--parallel", "-j", type=int, default=1, help=parallel_help)
    p_render.add_argument("--engine", choices=["ffmpeg", "moviepy"], default="ffmpeg",
                           help="Render engine: ffmpeg (default, fast) or moviepy (legacy)")
    p_render.set_defaults(func=cmd_render)

    p_concat = sub.add_parser("concat", help="Concat existing rendered beats into edit.output")
    p_concat.add_argument("edit")
    p_concat.add_argument("--width", help="Match suffix of beat videos to concat (e.g. 540p)")
    p_concat.set_defaults(func=cmd_concat)

    p_audio = sub.add_parser("audio", help="Process a recording -> wav + words.json")
    p_audio.add_argument("edit")
    p_audio.add_argument("beat_id")
    p_audio.add_argument("recording_filename", help="Filename inside data/recordings/")
    p_audio.set_defaults(func=cmd_audio)

    p_transcribe = sub.add_parser("transcribe", help="Standalone whisper transcription")
    p_transcribe.add_argument("audio_path")
    p_transcribe.add_argument("output_json")
    p_transcribe.add_argument("--model", default="medium", help="Whisper model size")
    p_transcribe.set_defaults(func=cmd_transcribe)

    p_serve = sub.add_parser("serve", help="Run local web server (recorder + preview)")
    p_serve.add_argument("edit")
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
    p_watch.add_argument("edit")
    p_watch.add_argument("--width", default="540p", help=width_help)
    p_watch.add_argument("--draft", action="store_true", help=draft_help)
    p_watch.add_argument("--gpu", action="store_true", help=gpu_help)
    p_watch.add_argument("--parallel", "-j", type=int, default=4, help=parallel_help)
    p_watch.set_defaults(func=cmd_watch)

    p_cc = sub.add_parser("cache-clear", help="Wipe the render cache")
    p_cc.add_argument("edit")
    p_cc.set_defaults(func=cmd_cache_clear)

    return parser


def main(argv: list[str] | None = None):
    parser = build_parser()
    args = parser.parse_args(argv)
    args.func(args)


if __name__ == "__main__":
    main()
