"""cli/newvideo.py -- `dl2 new-video <project>`: scaffold a fresh v2 project
by copying the packaged template (dlstudio.template).

The command ONLY copies the template and creates the correct structure
(PLAN_STUDIO_V2 1.2) -- no wizard, no project database, no configuration:

    <workspace>/<project>/
      __init__.py
      edits/__init__.py
      edits/<edit-name>/{__init__.py, beats.py, design.py}   # from the template
      data/{audio,footage,images,music,sfx,fonts,hyperframes,infographics,
            finalize,scratch}/

Orientation is Design.resolution, NOT a model field (locked plan decision):
`--format vertical` rewrites the template's `RESOLUTION = (1920, 1080)` line
in the copied design.py to (1080, 1920); landscape keeps (1920, 1080).

The edit package shape (__init__.py exposing EDIT + beats.py + design.py) is
the loader + Studio hot-reload convention -- see dlstudio.template's
docstring; a standalone edit.py file is NOT supported.
"""
from __future__ import annotations

import argparse
import importlib
import re
from pathlib import Path

TEMPLATE_FILES: tuple[str, ...] = ("__init__.py", "beats.py", "design.py")

DATA_SUBDIRS: tuple[str, ...] = (
    "audio", "footage", "images", "music", "sfx", "fonts",
    "hyperframes", "infographics", "finalize", "scratch",
)

FORMAT_RESOLUTIONS: dict[str, tuple[int, int]] = {
    "landscape": (1920, 1080),
    "vertical": (1080, 1920),
}

_RESOLUTION_RE = re.compile(r"(?m)^RESOLUTION = \(\s*\d+\s*,\s*\d+\s*\)\s*$")


def rewrite_resolution(design_src: str, resolution: tuple[int, int]) -> str:
    """Replace the template's module-level `RESOLUTION = (w, h)` line with
    `resolution`. Raises ValueError when the line is missing or ambiguous
    (a template edit broke the contract) -- never returns the source
    silently unchanged."""
    new_line = f"RESOLUTION = ({resolution[0]}, {resolution[1]})"
    rewritten, n = _RESOLUTION_RE.subn(new_line, design_src)
    if n != 1:
        raise ValueError(
            "template design.py must contain exactly one "
            f"'RESOLUTION = (w, h)' line, found {n}"
        )
    return rewritten


def _ensure_package(dir_path: Path) -> None:
    """mkdir -p + empty __init__.py (an existing __init__.py is kept -- a
    second edit scaffolded into an existing project must not clobber it)."""
    dir_path.mkdir(parents=True, exist_ok=True)
    init = dir_path / "__init__.py"
    if not init.exists():
        init.write_text("", encoding="utf-8")


def cmd_new_video(args: argparse.Namespace) -> int:
    # Lazy import: cli/__init__ imports this module during its own import
    # (before CliError exists), so a module-level `from dlstudio.cli
    # import ...` would be circular.
    from dlstudio.cli import CliError, _find_workspace_root

    workspace_root = _find_workspace_root()
    if workspace_root is None:
        raise CliError(
            "no workspace root found (no devlog.toml or .git upward from cwd) "
            "-- run inside the devlogs workspace"
        )

    project: str = args.project
    edit_name: str = args.edit_name
    for value, label in ((project, "project"), (edit_name, "--edit-name")):
        if not value.isidentifier():
            raise CliError(
                f"{label} {value!r} must be a valid Python identifier "
                "(it becomes an importable package name)"
            )

    resolution = FORMAT_RESOLUTIONS[args.format]
    project_dir = workspace_root / project
    edit_dir = project_dir / "edits" / edit_name
    dotted = f"{project}.edits.{edit_name}"
    if edit_dir.exists():
        raise CliError(
            f"edit dir already exists: {edit_dir} -- "
            "pick another <project> or --edit-name"
        )

    template_dir = Path(importlib.import_module("dlstudio.template").__file__).parent

    _ensure_package(project_dir)
    _ensure_package(project_dir / "edits")
    edit_dir.mkdir()
    for name in TEMPLATE_FILES:
        text = (template_dir / name).read_text(encoding="utf-8")
        if name == "design.py":
            try:
                text = rewrite_resolution(text, resolution)
            except ValueError as e:
                raise CliError(str(e)) from e
        (edit_dir / name).write_text(text, encoding="utf-8")

    for sub in DATA_SUBDIRS:
        (project_dir / "data" / sub).mkdir(parents=True, exist_ok=True)

    print(f"[dl2] created {project_dir} ({args.format}, {resolution[0]}x{resolution[1]})")
    print(f"[dl2]   edit module: {dotted}")
    print("[dl2] next steps:")
    print(f"[dl2]   1. dl2 check {dotted}")
    print("[dl2]      missing-asset errors are the asset TODO list for this edit")
    print(f"[dl2]   2. drop a TTF at {project}/data/fonts/main.ttf; put footage/images/")
    print(f"[dl2]      music/sfx under {project}/data/<kind>/ (beats.py paths point there)")
    print(f"[dl2]   3. edit {project}/edits/{edit_name}/beats.py, then: dl2 iter {dotted}")
    return 0


def add_subparser(sub: argparse._SubParsersAction) -> None:
    p = sub.add_parser(
        "new-video",
        help="scaffold a new v2 project from the packaged template",
    )
    p.add_argument("project", help="project package name, created under the workspace root")
    p.add_argument(
        "--format", default="landscape", choices=sorted(FORMAT_RESOLUTIONS),
        help="orientation -- sets Design.resolution in the copied design.py "
             "(default: landscape)",
    )
    p.add_argument(
        "--edit-name", dest="edit_name", default="main",
        help="edit package name under <project>/edits/ (default: main)",
    )
    p.set_defaults(func=cmd_new_video)
