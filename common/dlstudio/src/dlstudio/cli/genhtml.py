"""cli/genhtml.py -- `dl2 gen-html <dir> [--init] [--out] [--quality]`, the
HyperFrames HTML/GSAP asset subcommand (services/hyperframes.py does the
actual work):

    dl2 gen-html <dir> --init                                  scaffold
    dl2 gen-html <dir> --out data/infographics/<asset>.mp4 --quality draft|final

`<dir>` may be a bare asset name -- resolved to `data/hyperframes/<name>/`
-- or a real directory path (anything with a path separator, or an existing
directory, is taken as-is). `--out` defaults to
`data/infographics/<asset>.mp4`, `<asset>` being the project directory's
name. Passing `--init` together with `--out` scaffolds and then renders in
one call; `--init` alone stops after scaffolding.

Module-level imports stay stdlib-only, same structure as cli/verify.py:
dlstudio.services and CliError are imported INSIDE the handler (a module-
level `from dlstudio.cli import CliError` would be a circular import --
cli/__init__ imports this module to wire the subparser).
"""
from __future__ import annotations

import argparse
from pathlib import Path

HYPERFRAMES_ROOT = Path("data/hyperframes")
INFOGRAPHICS_ROOT = Path("data/infographics")


def _resolve_project_dir(raw: str) -> Path:
    """Bare asset name -> `data/hyperframes/<name>/`; anything that already
    looks like a path (has a separator, or names an existing directory) is
    taken as-is."""
    path = Path(raw)
    if len(path.parts) > 1 or path.is_dir():
        return path
    return HYPERFRAMES_ROOT / raw


def cmd_gen_html(args: argparse.Namespace) -> int:
    from dlstudio import services
    from dlstudio.cli import CliError  # lazy: circular at module import time

    project_dir = _resolve_project_dir(args.dir)
    if args.template and not args.init:
        raise CliError("--template requires --init.")
    if args.orientation != "landscape" and not args.init:
        raise CliError("--orientation is only used with --init.")
    if args.variables_file and not args.out:
        raise CliError("--variables-file requires an explicit --out path.")
    if args.evidence_file and not args.variables_file:
        raise CliError("--evidence-file requires --variables-file.")

    if args.init:
        try:
            services.init_project(
                project_dir,
                template=args.template,
                orientation=args.orientation,
            )
        except (FileExistsError, ValueError) as e:
            raise CliError(str(e)) from e
        print(f"[dl2] gen-html: scaffolded {project_dir}")
        if not args.out:
            return 0

    out = Path(args.out) if args.out else INFOGRAPHICS_ROOT / f"{project_dir.name}.mp4"
    try:
        render_options = {
            "quality": args.quality,
            "variables_file": Path(args.variables_file) if args.variables_file else None,
            "evidence_file": Path(args.evidence_file) if args.evidence_file else None,
        }
        if args.production_root:
            render_options["production_root"] = Path(args.production_root)
        rendered = services.render_html(
            project_dir,
            out,
            **render_options,
        )
    except (RuntimeError, ValueError) as e:
        raise CliError(str(e)) from e
    print(f"[dl2] gen-html: rendered {rendered}")
    return 0


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "gen-html",
        help="scaffold or render a HyperFrames HTML/GSAP asset (npx hyperframes)",
    )
    p.add_argument(
        "dir",
        help="asset name (resolved to data/hyperframes/<name>/) or a project directory path",
    )
    p.add_argument(
        "--init", action="store_true",
        help="scaffold a starter project instead of rendering",
    )
    p.add_argument(
        "--template",
        choices=("day-card", "before-after", "focus-callout", "cta-endcard", "explain-steps"),
        help="production visual-block scaffold to create with --init",
    )
    p.add_argument(
        "--orientation", choices=("landscape", "vertical"), default="landscape",
        help="visual-block scaffold orientation (default: landscape)",
    )
    p.add_argument(
        "--out",
        help="output .mp4 path (default: data/infographics/<asset>.mp4)",
    )
    p.add_argument(
        "--quality", choices=("draft", "final"), default="draft",
        help="render quality tier (default: draft)",
    )
    p.add_argument(
        "--variables-file",
        help="JSON values passed to HyperFrames at render time",
    )
    p.add_argument(
        "--evidence-file",
        help="approved-source and reproducible-derivation evidence for proof blocks",
    )
    p.add_argument(
        "--production-root",
        help="video project root containing data/assets/registry.json",
    )
    p.set_defaults(func=cmd_gen_html)
