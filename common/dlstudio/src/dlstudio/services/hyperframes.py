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

import hashlib
import json
import os
import re
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

from dlstudio.production import ProductionError, load_production_manifest

from .visual_blocks import ORIENTATIONS, VISUAL_BLOCK_TEMPLATES, render_visual_block_html
from .visual_block_evidence import validate_visual_evidence

# Ported from the legacy bridge (common/devlog/hyperframes.py), kept thin on
# purpose: scaffold + render only; every other knob (fps, resolution,
# variables, workers, ...) belongs to the hyperframes tool itself.

ENTRY_FILE = "index.html"

_PACKAGE = "hyperframes"

# v2 quality tier -> the hyperframes tool's own --quality value (the tool
# knows draft/standard/high; "final" buys its best encode).
_QUALITY_MAP: dict[str, str] = {"draft": "draft", "final": "high"}

_IMAGE_VARIABLES = {"before_image", "after_image", "image", "background_image"}


def _npx() -> str:
    exe = shutil.which("npx.cmd") or shutil.which("npx")
    if not exe:
        raise RuntimeError(
            "npx is not available on PATH. Install Node.js 22+ and npm to "
            "render HyperFrames assets."
        )
    return exe


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _json_object(path: Path, *, label: str) -> dict[str, object]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise RuntimeError(f"{label} is not valid UTF-8 JSON: {path}: {exc}") from exc
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} must contain one JSON object: {path}")
    return value


def _validate_visual_block_values(
    project: Path,
    variables_path: Path | None,
    *,
    production_root: Path | None = None,
) -> dict[str, object] | None:
    """Fail closed for built-in production blocks before invoking npx."""
    meta_path = project / "meta.json"
    if not meta_path.is_file():
        return None
    meta = _json_object(meta_path, label="HyperFrames project metadata")
    template = meta.get("template")
    if template in (None, "starter"):
        return None
    if not isinstance(template, str) or template not in VISUAL_BLOCK_TEMPLATES:
        raise RuntimeError(f"unknown visual-block template in {meta_path}: {template!r}")
    if variables_path is None:
        raise RuntimeError(
            f"visual-block template {template!r} requires --variables-file for render; "
            "declared defaults are preview placeholders, not release copy."
        )
    values = _json_object(variables_path, label="HyperFrames variables file")
    required = VISUAL_BLOCK_TEMPLATES[template].required_variables
    missing = [
        key for key in required
        if key not in values or (
            isinstance(values.get(key), str) and not str(values[key]).strip()
        )
    ]
    if missing:
        raise RuntimeError(
            f"visual-block template {template!r} is missing required variables: "
            + ", ".join(missing)
        )
    from .editorial_preflight import public_copy_issues

    public_issues = public_copy_issues(
        production_root or project,
        [
            (f"{variables_path.name}:{key}", value)
            for key, value in values.items()
            if isinstance(value, str) and key not in _IMAGE_VARIABLES
        ],
    )
    if public_issues:
        raise RuntimeError(public_issues[0].message)

    for key in _IMAGE_VARIABLES.intersection(values):
        raw = values[key]
        if not isinstance(raw, str):
            continue  # HyperFrames --strict-variables reports the type.
        asset = (project / raw).resolve()
        try:
            asset.relative_to(project)
        except ValueError as exc:
            raise RuntimeError(
                f"visual-block asset must stay inside its project: {key}={raw!r}"
            ) from exc
        if not asset.is_file():
            raise RuntimeError(f"visual-block asset not found: {key}={asset}")

    if template == "before-after":
        before = (project / str(values["before_image"])).resolve()
        after = (project / str(values["after_image"])).resolve()
        if before.is_file() and after.is_file() and _sha256(before) == _sha256(after):
            raise RuntimeError(
                "before-after proof uses identical inputs; provide two registered states."
            )
    if template == "cta-endcard":
        title = str(values["game_title"]).strip()
        public_copy = " ".join(
            str(values[key]) for key in ("game_title", "eyebrow", "cta", "episode")
        ).casefold()
        cta = str(values["cta"]).casefold()
        url = str(values["steam_url"]).strip()
        if title.casefold() == "your game":
            raise RuntimeError("CTA game_title is still the preview placeholder.")
        if "следующая остановка" in public_copy or "next stop" in public_copy:
            raise RuntimeError(
                "CTA must not claim Steam is a future stop when the page already exists."
            )
        if not any(token in cta for token in ("вишлист", "желаем", "wishlist")):
            raise RuntimeError("CTA must explicitly ask viewers to wishlist the game.")
        parsed = urlparse(url)
        canonical_path = re.fullmatch(r"/app/\d+(?:/[^/?#]+)?/?", parsed.path)
        if (
            parsed.scheme != "https"
            or parsed.hostname != "store.steampowered.com"
            or parsed.port is not None
            or canonical_path is None
            or parsed.query
            or parsed.fragment
        ):
            raise RuntimeError("CTA steam_url must be a canonical Steam app URL.")
        if production_root is not None:
            try:
                production = load_production_manifest(production_root)
            except ProductionError as exc:
                raise RuntimeError(f"CTA cannot load canonical product metadata: {exc}") from exc
            canonical_steam = production.product.sources.get("steam")
            if canonical_steam is None:
                raise RuntimeError(
                    "CTA requires canonical [sources].steam in product.toml."
                )
            if title != production.product.title:
                raise RuntimeError(
                    "CTA game_title does not match canonical product.toml title."
                )
            if url.rstrip("/") != canonical_steam.rstrip("/"):
                raise RuntimeError(
                    "CTA steam_url does not match canonical product.toml [sources].steam."
                )
    return values


def _find_production_root(project: Path, explicit: Path | None) -> Path | None:
    if explicit is not None:
        return explicit.resolve()
    for candidate in (project, *project.parents):
        if (candidate / "production.toml").is_file():
            try:
                return load_production_manifest(candidate).root
            except ProductionError as exc:
                raise RuntimeError(f"invalid production root: {exc}") from exc
        try:
            relative = project.relative_to(candidate)
        except ValueError:
            continue
        # Legacy projects have no production.toml. Infer their root only
        # from the canonical data/hyperframes layout; merely encountering a
        # devlog.toml farther up (for example the workspace root in tests)
        # must not capture an unrelated project.
        if relative.parts[:2] == ("data", "hyperframes"):
            return candidate.resolve()
    return None


def _relative_bound(root: Path, path: Path, *, label: str) -> str:
    resolved = path.resolve()
    try:
        return resolved.relative_to(root.resolve()).as_posix()
    except ValueError as exc:
        raise RuntimeError(f"{label} must stay inside the production root: {resolved}") from exc


def _write_render_manifest(
    *,
    project: Path,
    out: Path,
    quality: str,
    variables: Path | None,
    evidence: Path | None,
    production_root: Path | None,
) -> Path | None:
    if not out.is_file():
        return None
    meta_path = project / "meta.json"
    meta = (
        _json_object(meta_path, label="HyperFrames project metadata")
        if meta_path.is_file()
        else {}
    )
    root = production_root or Path(
        os.path.commonpath(
            [str(path.resolve()) for path in (project, out.parent)]
        )
    )
    payload: dict[str, object] = {
        "schema": "devlog.hyperframes_render/v2",
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "artifact": {
            "path": _relative_bound(root, out, label="HyperFrames artifact"),
            "sha256": _sha256(out),
        },
        "project": {
            "path": _relative_bound(root, project, label="HyperFrames project"),
            "entry_sha256": _sha256(project / ENTRY_FILE),
            "meta_sha256": _sha256(meta_path) if meta_path.is_file() else None,
        },
        "quality": quality,
        "template": meta.get("template"),
        "orientation": meta.get("orientation"),
    }
    if variables is not None:
        payload["variables"] = {
            "path": _relative_bound(root, variables, label="HyperFrames variables"),
            "sha256": _sha256(variables),
        }
    if evidence is not None:
        payload["evidence"] = {
            "path": _relative_bound(root, evidence, label="HyperFrames evidence"),
            "sha256": _sha256(evidence),
        }
    manifest = out.with_suffix(out.suffix + ".render.json")
    manifest.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    return manifest


def _manifest_file(
    root: Path,
    value: object,
    *,
    label: str,
    required: bool = True,
) -> Path | None:
    if value is None and not required:
        return None
    if not isinstance(value, dict):
        raise RuntimeError(f"{label} record is missing from render manifest.")
    raw_path = value.get("path")
    expected_hash = value.get("sha256")
    if not isinstance(raw_path, str) or not raw_path or not isinstance(expected_hash, str):
        raise RuntimeError(f"{label} record requires path and sha256.")
    path = (root / raw_path).resolve()
    try:
        path.relative_to(root)
    except ValueError as exc:
        raise RuntimeError(f"{label} path escapes the production root.") from exc
    if not path.is_file() or _sha256(path) != expected_hash.casefold():
        raise RuntimeError(f"{label} file is missing or stale: {raw_path}")
    return path


def validate_hyperframes_render_manifest(
    artifact: str | Path,
    manifest_path: str | Path,
    production_root: str | Path,
    *,
    require_final: bool = False,
) -> None:
    """Revalidate a generated video and every release input at final-check time."""
    root = Path(production_root).resolve()
    manifest_file = Path(manifest_path)
    if not manifest_file.is_absolute():
        manifest_file = root / manifest_file
    manifest_file = manifest_file.resolve()
    try:
        manifest_file.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("HyperFrames render manifest escapes the production root.") from exc
    manifest = _json_object(manifest_file, label="HyperFrames render manifest")
    if manifest.get("schema") != "devlog.hyperframes_render/v2":
        raise RuntimeError("HyperFrames render manifest has an unsupported schema.")
    if require_final and manifest.get("quality") != "final":
        raise RuntimeError(
            "shipping requires a HyperFrames manifest rendered at quality=final."
        )

    artifact_path = _manifest_file(root, manifest.get("artifact"), label="artifact")
    expected_artifact = Path(artifact)
    if not expected_artifact.is_absolute():
        expected_artifact = root / expected_artifact
    if artifact_path != expected_artifact.resolve():
        raise RuntimeError("HyperFrames render manifest points to a different artifact.")

    project_record = manifest.get("project")
    if not isinstance(project_record, dict) or not isinstance(project_record.get("path"), str):
        raise RuntimeError("HyperFrames render manifest requires a project record.")
    project = (root / str(project_record["path"])).resolve()
    try:
        project.relative_to(root)
    except ValueError as exc:
        raise RuntimeError("HyperFrames project escapes the production root.") from exc
    entry = project / ENTRY_FILE
    meta_path = project / "meta.json"
    if (
        not entry.is_file()
        or _sha256(entry) != str(project_record.get("entry_sha256", "")).casefold()
        or not meta_path.is_file()
        or _sha256(meta_path) != str(project_record.get("meta_sha256", "")).casefold()
    ):
        raise RuntimeError("HyperFrames project source changed after render.")

    variables = _manifest_file(
        root,
        manifest.get("variables"),
        label="variables",
        required=False,
    )
    evidence = _manifest_file(
        root,
        manifest.get("evidence"),
        label="evidence",
        required=False,
    )
    values = _validate_visual_block_values(
        project,
        variables,
        production_root=root,
    )
    meta = _json_object(meta_path, label="HyperFrames project metadata")
    template = meta.get("template")
    orientation = meta.get("orientation")
    if manifest.get("template") != template or manifest.get("orientation") != orientation:
        raise RuntimeError("HyperFrames project metadata no longer matches render manifest.")
    validate_visual_evidence(
        project,
        production_root=root,
        template=template if isinstance(template, str) else None,
        values=values,
        evidence_path=evidence,
    )


def init_project(
    project_dir: Path,
    *,
    force: bool = False,
    title: str = "273 COMMITS",
    template: str | None = None,
    orientation: str = "landscape",
) -> Path:
    """Scaffold a starter HyperFrames project into `project_dir`.

    Writes `index.html` (a small bar-chart composition demonstrating the
    paused-timeline `window.__timelines` contract), `meta.json`, and empty
    `compositions/` + `assets/` directories. Refuses a non-empty existing
    directory unless `force=True`. When `template` names a built-in visual
    block, writes that parametrized production scaffold instead of the
    legacy bar-chart starter.
    """
    root = Path(project_dir)
    if template is not None and template not in VISUAL_BLOCK_TEMPLATES:
        raise ValueError(
            f"unknown visual-block template: {template!r}. "
            f"Use one of {sorted(VISUAL_BLOCK_TEMPLATES)}."
        )
    if orientation not in ORIENTATIONS:
        raise ValueError(
            f"unknown orientation: {orientation!r}. Use one of {sorted(ORIENTATIONS)}."
        )
    if template is None and orientation != "landscape":
        raise ValueError(
            "orientation applies to a visual-block template. Pass --template "
            "or use the legacy starter's landscape orientation."
        )
    if root.exists() and any(root.iterdir()) and not force:
        raise FileExistsError(
            f"{root} already exists and is not empty. Pass force=True to "
            "overwrite the starter files."
        )
    root.mkdir(parents=True, exist_ok=True)
    (root / "compositions").mkdir(parents=True, exist_ok=True)
    (root / "assets").mkdir(parents=True, exist_ok=True)
    meta = {
        "name": root.name,
        "id": root.name,
        "createdBy": "dl2 gen-html --init",
        "template": template or "starter",
        "orientation": orientation,
    }
    if template is not None:
        definition = VISUAL_BLOCK_TEMPLATES[template]
        meta["label"] = definition.label
        meta["purpose"] = definition.purpose
        meta["requiredVariables"] = list(definition.required_variables)
    (root / "meta.json").write_text(json.dumps(meta, indent=2), encoding="utf-8")
    source = (
        render_visual_block_html(template, orientation=orientation)
        if template is not None
        else _starter_index_html(title)
    )
    (root / ENTRY_FILE).write_text(source, encoding="utf-8")
    return root


def render_html(
    project_dir: Path,
    out_mp4: Path,
    *,
    quality: str = "draft",
    variables_file: Path | None = None,
    evidence_file: Path | None = None,
    production_root: Path | None = None,
) -> Path:
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
    out = Path(out_mp4).resolve()
    out.parent.mkdir(parents=True, exist_ok=True)

    variables: Path | None = None
    if variables_file is not None:
        variables = Path(variables_file).resolve()
        if not variables.is_file():
            raise RuntimeError(f"HyperFrames variables file not found: {variables}")
    resolved_production_root = _find_production_root(
        project,
        Path(production_root) if production_root is not None else None,
    )
    values = _validate_visual_block_values(
        project,
        variables,
        production_root=resolved_production_root,
    )
    meta_path = project / "meta.json"
    meta = (
        _json_object(meta_path, label="HyperFrames project metadata")
        if meta_path.is_file()
        else {}
    )
    evidence: Path | None = None
    if evidence_file is not None:
        evidence = Path(evidence_file).resolve()
        if not evidence.is_file():
            raise RuntimeError(f"visual-block evidence file not found: {evidence}")
    validate_visual_evidence(
        project,
        production_root=resolved_production_root,
        template=meta.get("template") if isinstance(meta.get("template"), str) else None,
        values=values,
        evidence_path=evidence,
    )

    npx = _npx()
    cmd = [npx, "-y", _PACKAGE, "render", str(project),
           "--output", str(out), "--quality", _QUALITY_MAP[quality]]
    if variables is not None:
        cmd.extend(["--variables-file", str(variables), "--strict-variables"])

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
    _write_render_manifest(
        project=project,
        out=out,
        quality=quality,
        variables=variables,
        evidence=evidence,
        production_root=resolved_production_root,
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
