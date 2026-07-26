"""cli/preview.py — `dl2 preview <edit>`: the one-command draft path.

Deterministic sequence (PLAN_STUDIO_V2 1.3):

    check (the 0.4 pre-render gate, inside the iterate machinery)
    -> iter --stale draft (render only cache-miss beats at 540p draft)
    -> assemble (full mix)
    -> contact sheet  data/review/contact_sheet.jpg
    -> keyframes      data/review/keyframes/kf_NN.jpg

No judgment calls here — reviewer agents look at the artifacts; this
command only produces them.
"""
from __future__ import annotations

import argparse
from pathlib import Path


def cmd_preview(args: argparse.Namespace) -> int:
    from dlstudio import compile as dl_compile
    from dlstudio import services
    from dlstudio.cli import (
        _find_workspace_root,
        _iterate_render,
        _load_edit,
        _load_v2_config,
        _resize_design,
        _resolve_edit_arg,
    )

    v2_config = _load_v2_config(_find_workspace_root())
    dotted = _resolve_edit_arg(args.edit, v2_config)
    edit = _load_edit(dotted)

    timeline = dl_compile.build_timeline(edit)
    width_spec = args.width or "540p"
    effective_design = _resize_design(timeline.design, width_spec)
    effective_timeline = services.timeline_for_design(timeline, effective_design)
    geometry_report = services.write_geometry_report(effective_timeline)
    boundary_report = services.write_boundary_report(effective_timeline)
    rc = _iterate_render(
        edit, timeline,
        width_spec=width_spec, quality=args.quality or "draft",
        gpu=False, no_cache=False, stale=True, jobs=args.jobs,
    )
    if rc:
        return rc

    output = Path(timeline.output)
    sheet = services.make_contact_sheet(
        output, Path("data/review/contact_sheet.jpg"))
    frames = services.extract_keyframes(
        output, Path("data/review/keyframes"), count=args.keyframes)

    print(f"[dl2] preview: draft   -> {output}")
    print(f"[dl2] preview: geometry-> {geometry_report}")
    print(f"[dl2] preview: boundary-> {boundary_report}")
    print(f"[dl2] preview: sheet   -> {sheet}")
    print(f"[dl2] preview: frames  -> {frames[0].parent} ({len(frames)} files)")
    return 0


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "preview",
        help="draft path in one command: check + stale draft render + "
             "assemble + contact sheet + keyframes",
    )
    p.add_argument("edit", nargs="?", help="dotted edit module path")
    p.add_argument("--width", help="resolution profile (default: 540p)")
    p.add_argument("--quality", help="quality tier (default: draft)")
    p.add_argument("-j", "--jobs", type=int, default=1,
                   help="parallel worker processes")
    p.add_argument("--keyframes", type=int, default=8,
                   help="number of keyframe stills (default: 8)")
    p.set_defaults(func=cmd_preview)
