"""hyperframes: optional HTML/GSAP motion-asset bridge (`npx hyperframes`).

Thin wrapper over the external HyperFrames renderer: `init_project()`
scaffolds a starter project, `render_html()` shells out to
`npx hyperframes render` to turn the project into an MP4 the rest of the
pipeline consumes as a normal video asset. Nothing renders in-process — the
whole point is keeping HTML/GSAP motion work outside the core renderer.

Conventions (the `dl2 gen-html` subcommand resolves both):
  - project sources live in `data/hyperframes/<asset>/` (entry file
    `index.html`, plus `meta.json`, `compositions/`, `assets/`);
  - rendered output goes to `data/infographics/<asset>.mp4`.

Determinism: compositions build a PAUSED GSAP timeline synchronously at page
load and register it as `window.__timelines["<id>"]`, where `<id>` matches
the composition root's `data-composition-id`. The renderer seeks that
timeline frame by frame instead of letting it play on the wall clock, so a
given project always produces the same frames. Never build a timeline inside
async code (fetch/setTimeout/Promise) — the capture engine reads
`window.__timelines` synchronously after load.

Requirements: Node.js 22+ and npm on PATH (`npx` downloads the hyperframes
package on first use). The child env always carries
`NODE_OPTIONS=--use-system-ca` so those npx downloads trust the system /
corporate CA store, and `NO_COLOR=1` so logs stay ANSI-free.

Quality: the v2 tiers are "draft" | "final", mapped onto the tool's own
--quality values (draft -> draft, final -> high); see `_QUALITY_MAP`.

Per the services/ lazy-import contract this module is stdlib-only: node/npx
is probed at call time inside `render_html()`, never at import time.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path

# Ported from the legacy bridge (common/devlog/hyperframes.py), kept thin on
# purpose: scaffold + render only; every other knob (fps, resolution,
# variables, workers, ...) belongs to the hyperframes tool itself.

ENTRY_FILE = "index.html"

_PACKAGE = "hyperframes"

# v2 quality tier -> the hyperframes tool's own --quality value (the tool
# knows draft/standard/high; "final" buys its best encode).
_QUALITY_MAP: dict[str, str] = {"draft": "draft", "final": "high"}


def _npx() -> str:
    exe = shutil.which("npx.cmd") or shutil.which("npx")
    if not exe:
        raise RuntimeError(
            "npx is not available on PATH. Install Node.js 22+ and npm to "
            "render HyperFrames assets."
        )
    return exe


def init_project(project_dir: Path, *, force: bool = False,
                 title: str = "273 COMMITS") -> Path:
    """Scaffold a starter HyperFrames project into `project_dir`.

    Writes `index.html` (a small bar-chart composition demonstrating the
    paused-timeline `window.__timelines` contract), `meta.json`, and empty
    `compositions/` + `assets/` directories. Refuses a non-empty existing
    directory unless `force=True`; `title` is the headline text baked into
    the starter composition.
    """
    root = Path(project_dir)
    if root.exists() and any(root.iterdir()) and not force:
        raise FileExistsError(
            f"{root} already exists and is not empty. Pass force=True to "
            "overwrite the starter files."
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / "compositions").mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "meta.json").write_text(json.dumps({
        "name": root.name,
        "id": root.name,
        "createdBy": "dl2 gen-html --init",
    }, indent=2), encoding="utf-8")
    (root / ENTRY_FILE).write_text(_starter_index_html(title), encoding="utf-8")
    return root


def render_html(project_dir: Path, out_mp4: Path, *, quality: str = "draft") -> Path:
    """Render a HyperFrames project directory to `out_mp4` via
    `npx hyperframes render`.

    `quality` is a v2 tier ("draft" | "final"), mapped through
    `_QUALITY_MAP` onto the tool's own --quality flag. The output directory
    is created if needed. Raises `RuntimeError` when the project has no
    `index.html` entry file, when npx is missing from PATH, or when the
    render subprocess fails (message carries the stderr tail; the full
    stdout/stderr log is written next to the output file).
    """
    if quality not in _QUALITY_MAP:
        raise ValueError(
            f"unsupported quality: {quality!r}. Use one of {sorted(_QUALITY_MAP)}."
        )
    project = Path(project_dir).resolve()
    entry = project / ENTRY_FILE
    if not entry.exists():
        raise RuntimeError(
            f"HyperFrames project entry file not found: {entry}. "
            "Scaffold a starter project with `dl2 gen-html <dir> --init`."
        )
    npx = _npx()
    out = Path(out_mp4).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd = [npx, "-y", _PACKAGE, "render", str(project),
           "--output", str(out), "--quality", _QUALITY_MAP[quality]]

    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")
    node_options = env.get("NODE_OPTIONS", "")
    if "--use-system-ca" not in node_options:
        # System/corporate CA trust for npx's package downloads.
        env["NODE_OPTIONS"] = (node_options + " --use-system-ca").strip()

    proc = subprocess.run(
        cmd, cwd=project, env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    if proc.returncode != 0:
        debug = out.with_suffix(out.suffix + ".hyperframes_error.txt")
        debug.write_text(
            "CMD:\n" + " ".join(cmd)
            + "\n\nSTDOUT:\n" + proc.stdout
            + "\n\nSTDERR:\n" + proc.stderr,
            encoding="utf-8",
        )
        tail = "\n".join((proc.stderr or "").strip().splitlines()[-15:])
        raise RuntimeError(
            f"HyperFrames render failed (rc={proc.returncode}). "
            f"Full log: {debug}\nstderr tail:\n{tail}"
        )
    return out


def _starter_index_html(title: str) -> str:
    escaped = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>HyperFrames Starter</title>
  <style>
    html, body {{
      margin: 0;
      width: 100%;
      height: 100%;
      background: #1a1612;
      overflow: hidden;
      font-family: Bahnschrift, Tahoma, system-ui, sans-serif;
    }}
    [data-composition-id="root"] {{
      position: relative;
      overflow: hidden;
      background: radial-gradient(circle at 50% 42%, #2a2117 0%, #1a1612 62%, #0b0907 100%);
      color: #e8b647;
    }}
    .clip {{
      position: absolute;
      box-sizing: border-box;
    }}
    #title {{
      left: 0;
      right: 0;
      top: 72px;
      text-align: center;
      font-size: 104px;
      font-weight: 800;
      letter-spacing: 0;
      opacity: 0;
      text-shadow: 4px 4px 0 #000;
    }}
    #underline {{
      left: 720px;
      top: 194px;
      width: 480px;
      height: 9px;
      background: #c0392b;
      transform-origin: center;
      transform: scaleX(0);
    }}
    .bar {{
      bottom: 250px;
      width: 210px;
      height: var(--h);
      background: #e8b647;
      transform-origin: bottom;
      transform: scaleY(0);
      box-shadow: 8px 12px 0 #000;
    }}
    .bar.hot {{
      background: #c0392b;
    }}
    .label {{
      bottom: 202px;
      width: 210px;
      text-align: center;
      font-size: 34px;
      color: #e0ae45;
      opacity: 0;
    }}
    .value {{
      width: 210px;
      text-align: center;
      font-size: 42px;
      color: #e8b647;
      opacity: 0;
      text-shadow: 3px 3px 0 #000;
    }}
  </style>
</head>
<body>
  <div id="root" data-composition-id="root" data-start="0" data-width="1920" data-height="1080">
    <h1 id="title" class="clip" data-start="0" data-duration="3.2" data-track-index="1">{escaped}</h1>
    <div id="underline" class="clip" data-start="0" data-duration="3.2" data-track-index="1"></div>
    <div id="b1" class="clip bar" style="left: 276px; --h: 92px" data-start="0" data-duration="3.2" data-track-index="2"></div>
    <div id="b2" class="clip bar" style="left: 536px; --h: 190px" data-start="0" data-duration="3.2" data-track-index="2"></div>
    <div id="b3" class="clip bar hot" style="left: 796px; --h: 520px" data-start="0" data-duration="3.2" data-track-index="2"></div>
    <div id="b4" class="clip bar" style="left: 1056px; --h: 300px" data-start="0" data-duration="3.2" data-track-index="2"></div>
    <div id="b5" class="clip bar" style="left: 1316px; --h: 226px" data-start="0" data-duration="3.2" data-track-index="2"></div>
    <div class="clip label" style="left: 276px" data-start="0" data-duration="3.2" data-track-index="3">D1</div>
    <div class="clip label" style="left: 536px" data-start="0" data-duration="3.2" data-track-index="3">D2</div>
    <div class="clip label" style="left: 796px" data-start="0" data-duration="3.2" data-track-index="3">D3</div>
    <div class="clip label" style="left: 1056px" data-start="0" data-duration="3.2" data-track-index="3">D4</div>
    <div class="clip label" style="left: 1316px" data-start="0" data-duration="3.2" data-track-index="3">D5</div>
    <div class="clip value" style="left: 276px; bottom: 358px" data-start="0" data-duration="3.2" data-track-index="3">8</div>
    <div class="clip value" style="left: 536px; bottom: 456px" data-start="0" data-duration="3.2" data-track-index="3">23</div>
    <div class="clip value" style="left: 796px; bottom: 786px" data-start="0" data-duration="3.2" data-track-index="3">80</div>
    <div class="clip value" style="left: 1056px; bottom: 566px" data-start="0" data-duration="3.2" data-track-index="3">31</div>
    <div class="clip value" style="left: 1316px; bottom: 492px" data-start="0" data-duration="3.2" data-track-index="3">18</div>
  </div>
  <script src="https://cdn.jsdelivr.net/npm/gsap@3/dist/gsap.min.js"></script>
  <script>
    // Deterministic contract: a PAUSED timeline, built synchronously, keyed
    // by the composition root's data-composition-id. The renderer seeks it.
    const tl = gsap.timeline({{ paused: true }});
    tl.to("#title", {{ opacity: 1, y: 16, duration: 0.45, ease: "power2.out" }}, 0);
    tl.to("#underline", {{ scaleX: 1, duration: 0.35, ease: "power2.out" }}, 0.2);
    tl.to(".bar", {{ scaleY: 1, duration: 0.9, stagger: 0.08, ease: "back.out(1.4)" }}, 0.45);
    tl.to(".label", {{ opacity: 1, duration: 0.25, stagger: 0.05 }}, 0.7);
    tl.to(".value", {{ opacity: 1, y: -12, duration: 0.3, stagger: 0.07 }}, 1.0);
    window.__timelines = window.__timelines || {{}};
    window.__timelines["root"] = tl;
  </script>
</body>
</html>
"""
