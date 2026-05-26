"""Optional Hyperframes bridge for rich HTML/GSAP motion assets.

This module intentionally keeps Hyperframes outside the core renderer. It
creates or renders standalone Hyperframes projects, then the resulting MP4 can
be used by the existing pipeline as a normal Scene video.
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
from pathlib import Path


def _npx() -> str:
    exe = shutil.which("npx.cmd") or shutil.which("npx")
    if not exe:
        raise RuntimeError("npx is not available. Install Node.js 22+ and npm to use Hyperframes.")
    return exe


def create_sample_project(project_dir: str | Path, *, force: bool = False,
                          title: str = "273 COMMITS") -> Path:
    """Create a tiny Hyperframes project that demonstrates GSAP timelines."""
    root = Path(project_dir)
    if root.exists() and any(root.iterdir()) and not force:
        raise FileExistsError(f"{root} already exists and is not empty. Use --force to overwrite sample files.")
    root.mkdir(parents=True, exist_ok=True)
    (root / "compositions").mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    (root / "meta.json").write_text(json.dumps({
        "name": root.name,
        "id": root.name,
        "createdBy": "devlog dl gen-html --init",
    }, indent=2), encoding="utf-8")
    (root / "index.html").write_text(_sample_index_html(title), encoding="utf-8")
    return root


def render_hyperframes(project_dir: str | Path, out_path: str | Path, *,
                       composition: str | None = None,
                       fps: str | int | None = None,
                       quality: str | None = None,
                       fmt: str | None = None,
                       workers: str | int | None = None,
                       docker: bool = False,
                       gpu: bool = False,
                       resolution: str | None = None,
                       variables: str | None = None,
                       variables_file: str | None = None,
                       package: str = "hyperframes") -> Path:
    """Run `npx hyperframes render` for a project directory."""
    project = Path(project_dir).resolve()
    if not project.exists():
        raise FileNotFoundError(f"Hyperframes project directory does not exist: {project}")
    out = Path(out_path).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    cmd: list[str] = [_npx(), "-y", package, "render", str(project), "--output", str(out)]
    if composition:
        cmd += ["--composition", composition]
    if fps:
        cmd += ["--fps", str(fps)]
    if quality:
        cmd += ["--quality", quality]
    if fmt:
        cmd += ["--format", fmt]
    if workers:
        cmd += ["--workers", str(workers)]
    if docker:
        cmd.append("--docker")
    if gpu:
        cmd.append("--gpu")
    if resolution:
        cmd += ["--resolution", resolution]
    if variables:
        cmd += ["--variables", variables]
    if variables_file:
        cmd += ["--variables-file", variables_file]

    env = os.environ.copy()
    env.setdefault("NO_COLOR", "1")
    node_options = env.get("NODE_OPTIONS", "")
    if "--use-system-ca" not in node_options:
        env["NODE_OPTIONS"] = (node_options + " --use-system-ca").strip()
    proc = subprocess.run(cmd, cwd=project, env=env, text=True, capture_output=True)
    if proc.returncode != 0:
        debug = out.with_suffix(out.suffix + ".hyperframes_error.txt")
        debug.write_text(
            "CMD:\n" + " ".join(cmd) + "\n\nSTDOUT:\n" + proc.stdout + "\n\nSTDERR:\n" + proc.stderr,
            encoding="utf-8",
        )
        raise RuntimeError(f"Hyperframes render failed (rc={proc.returncode}). Debug: {debug}")
    return out


def _sample_index_html(title: str) -> str:
    escaped = title.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    return f"""<!doctype html>
<html>
<head>
  <meta charset="utf-8">
  <title>Devlog Hyperframes Sample</title>
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
