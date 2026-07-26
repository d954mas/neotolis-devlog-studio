"""Tests for dlstudio.cli -- argparse wiring, the edit loader, the error
boundary, and doctor diagnostics.

compile/ and render/ are NotImplementedError stub bodies during Phase 1
(owned by parallel agents). Tests that must prove the CLI's lazy-import
boundary call into the real compile.build_timeline / render.render_beat
stubs and assert NotImplementedError surfaces correctly through main()'s
error boundary -- they never assume compile/render actually produce
output. Tests that need an IRBeat/Timeline build them directly via the
conftest helpers instead of compiling an Edit.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import textwrap
import uuid
from pathlib import Path

import pytest

from dlstudio import cache as dl_cache
from dlstudio import cli
from dlstudio.model import Edit

from conftest import make_design, make_ir_beat, make_timeline


def _unique_pkg(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


def _make_fake_project(
    tmp_path: Path,
    pkg_name: str,
    *,
    edit_name: str = "myedit",
    default_edit_in_config: bool = False,
    edit_body: str | None = None,
) -> str:
    """Build tmp_path/<pkg_name>/edits/<edit_name>/__init__.py exposing
    EDIT, plus a devlog.toml workspace marker at tmp_path. Returns the
    dotted module path."""
    proj = tmp_path / pkg_name
    proj.mkdir(parents=True)
    (proj / "__init__.py").write_text("", encoding="utf-8")
    edits_dir = proj / "edits"
    edits_dir.mkdir()
    (edits_dir / "__init__.py").write_text("", encoding="utf-8")
    edit_dir = edits_dir / edit_name
    edit_dir.mkdir()

    dotted = f"{pkg_name}.edits.{edit_name}"

    if edit_body is None:
        edit_body = textwrap.dedent(
            """
            from dlstudio.model import Design, Edit, Fonts, Palette

            EDIT = Edit(
                name="fake-edit",
                design=Design(
                    resolution=(1920, 1080),
                    palette=Palette(tokens={"bg": "#000000", "text": "#ffffff"}),
                    fonts=Fonts(main="main.ttf"),
                ),
                beats={},
                order=[],
                output="data/finalize/output.mp4",
            )
            """
        )
    (edit_dir / "__init__.py").write_text(edit_body, encoding="utf-8")

    toml_lines = []
    if default_edit_in_config:
        toml_lines = ["[v2]", f'default_edit = "{dotted}"']
    (tmp_path / "devlog.toml").write_text("\n".join(toml_lines) + "\n", encoding="utf-8")

    return dotted


# ─── project root / workspace root resolution ─────────────────────────

def test_project_root_direct_child(tmp_path):
    module_file = tmp_path / "proj" / "edits" / "myedit" / "__init__.py"
    assert cli._project_root_for_module(module_file, tmp_path) == (tmp_path / "proj").resolve()


def test_project_root_deeper_nesting(tmp_path):
    module_file = tmp_path / "proj" / "edits" / "group" / "myedit" / "__init__.py"
    assert cli._project_root_for_module(module_file, tmp_path) == (tmp_path / "proj").resolve()


def test_project_root_fallback_without_workspace_root(tmp_path):
    module_file = tmp_path / "somewhere" / "proj" / "edits" / "myedit" / "__init__.py"
    expected = (tmp_path / "somewhere" / "proj").resolve()
    assert cli._project_root_for_module(module_file, None) == expected


def test_find_workspace_root_via_devlog_toml(tmp_path):
    (tmp_path / "devlog.toml").write_text("", encoding="utf-8")
    nested = tmp_path / "a" / "b"
    nested.mkdir(parents=True)
    assert cli._find_workspace_root(nested) == tmp_path.resolve()


# ─── config ─────────────────────────────────────────────────────────

def test_load_v2_config_reads_default_edit(tmp_path):
    (tmp_path / "devlog.toml").write_text(
        '[v2]\ndefault_edit = "proj.edits.myedit"\n', encoding="utf-8"
    )
    cfg = cli._load_v2_config(tmp_path)
    assert cfg["default_edit"] == "proj.edits.myedit"


def test_load_v2_config_missing_file_or_table(tmp_path):
    assert cli._load_v2_config(None) == {}
    assert cli._load_v2_config(tmp_path) == {}  # no devlog.toml at all
    (tmp_path / "devlog.toml").write_text('[defaults]\nwidth = "540p"\n', encoding="utf-8")
    assert cli._load_v2_config(tmp_path) == {}  # devlog.toml exists but no [v2] table


def test_resolve_edit_arg_prefers_explicit_over_config():
    assert cli._resolve_edit_arg("explicit.edit", {"default_edit": "config.edit"}) == "explicit.edit"
    assert cli._resolve_edit_arg(None, {"default_edit": "config.edit"}) == "config.edit"


def test_resolve_edit_arg_raises_without_either():
    with pytest.raises(cli.CliError):
        cli._resolve_edit_arg(None, {})


# ─── edit loader ────────────────────────────────────────────────────

def test_load_edit_success_chdirs_to_project_root(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_ok")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    edit = cli._load_edit(dotted)
    assert isinstance(edit, Edit)
    assert Path.cwd() == (tmp_path / pkg).resolve()


def test_load_edit_missing_EDIT_attr(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_noedit")
    dotted = _make_fake_project(tmp_path, pkg, edit_body="X = 1\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(cli.CliError, match="no EDIT object"):
        cli._load_edit(dotted)


def test_load_edit_wrong_EDIT_type(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_wrongtype")
    dotted = _make_fake_project(tmp_path, pkg, edit_body="EDIT = object()\n")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    with pytest.raises(cli.CliError, match="not dlstudio.model.Edit"):
        cli._load_edit(dotted)


def test_load_edit_bad_module_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    with pytest.raises(cli.CliError, match="cannot import"):
        cli._load_edit("nonexistent_pkg_xyz.edits.myedit")


def test_load_edit_uses_default_edit_from_config(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_default")
    dotted = _make_fake_project(tmp_path, pkg, default_edit_in_config=True)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    v2_config = cli._load_v2_config(cli._find_workspace_root())
    resolved = cli._resolve_edit_arg(None, v2_config)
    assert resolved == dotted


# ─── _resize_design ─────────────────────────────────────────────────

def test_resize_design_preset():
    design = make_design(1920, 1080)
    resized = cli._resize_design(design, "540p")
    assert resized.resolution == (960, 540)


# 0.6: the ONE explicit profile table from PLAN_STUDIO_V2 — presets resolve
# orientation-aware; a vertical "4k" is the transposed standard (2160x3840),
# never "width 3840" (which produced the 3840x6826 x264 OOM class).
@pytest.mark.parametrize("orig, preset, expected", [
    ((1920, 1080), "540p", (960, 540)),      # landscape draft
    ((1920, 1080), "1080p", (1920, 1080)),   # landscape final
    ((1920, 1080), "4k", (3840, 2160)),      # landscape 4k
    ((1080, 1920), "540p", (304, 540)),      # vertical draft
    ((1080, 1920), "1080p", (1080, 1920)),   # vertical final
    ((1080, 1920), "4k", (2160, 3840)),      # vertical 4k
])
def test_resize_design_profile_table(orig, preset, expected):
    design = make_design(*orig)
    assert cli._resize_design(design, preset).resolution == expected


def test_resize_design_vertical_4k_stays_encoder_safe():
    """Regression pin for the exact defect: vertical 4k used to compute
    3840x6826 (width-anchored), which exceeds the 4096px VQ-RES ceiling."""
    design = make_design(1080, 1920)
    w, h = cli._resize_design(design, "4k").resolution
    assert (w, h) == (2160, 3840)
    assert max(w, h) <= 4096


def test_resize_design_literal_int_rounds_even():
    design = make_design(1920, 1080)
    resized = cli._resize_design(design, 641)
    assert resized.resolution[0] % 2 == 0
    assert resized.resolution[1] % 2 == 0


def test_resize_design_none_is_noop():
    design = make_design(1920, 1080)
    assert cli._resize_design(design, None) is design


def test_resize_design_bad_value_raises():
    design = make_design(1920, 1080)
    with pytest.raises(cli.CliError):
        cli._resize_design(design, "not-a-width")


# ─── argparse wiring ────────────────────────────────────────────────

def test_parse_check():
    args = cli._build_parser().parse_args(["check", "some.edit"])
    assert args.command == "check"
    assert args.edit == "some.edit"
    assert args.func is cli.cmd_check


def test_parse_check_no_edit_defaults_none():
    args = cli._build_parser().parse_args(["check"])
    assert args.edit is None


def test_parse_ir_with_out():
    args = cli._build_parser().parse_args(["ir", "some.edit", "--out", "ir.json"])
    assert args.out == "ir.json"


def test_parse_compose_two_positionals():
    args = cli._build_parser().parse_args(
        ["compose", "some.edit", "b01", "--width", "540p", "--quality", "draft", "--gpu"]
    )
    assert args.edit_or_beat == "some.edit"
    assert args.beat_id == "b01"
    assert args.width == "540p"
    assert args.quality == "draft"
    assert args.gpu is True


def test_parse_compose_single_positional_is_beat_id():
    args = cli._build_parser().parse_args(["compose", "b01"])
    assert args.edit_or_beat == "b01"
    assert args.beat_id is None


def test_resolve_compose_args_disambiguation():
    ns = argparse.Namespace(edit_or_beat="b01", beat_id=None)
    assert cli._resolve_compose_args(ns, {"default_edit": "cfg.edit"}) == ("cfg.edit", "b01")

    ns2 = argparse.Namespace(edit_or_beat="explicit.edit", beat_id="b02")
    assert cli._resolve_compose_args(ns2, {}) == ("explicit.edit", "b02")


def test_parse_iter_stale_and_jobs():
    args = cli._build_parser().parse_args(["iter", "some.edit", "--stale", "-j", "4"])
    assert args.stale is True
    assert args.jobs == 4


def test_parse_iter_defaults():
    args = cli._build_parser().parse_args(["iter"])
    assert args.stale is False
    assert args.jobs == 1


def test_parse_beats():
    args = cli._build_parser().parse_args(["beats", "some.edit"])
    assert args.func is cli.cmd_beats


def test_parse_doctor():
    args = cli._build_parser().parse_args(["doctor"])
    assert args.func is cli.cmd_doctor


def test_parse_requires_a_command():
    with pytest.raises(SystemExit):
        cli._build_parser().parse_args([])


def test_parse_top_level_debug_flag():
    args = cli._build_parser().parse_args(["--debug", "doctor"])
    assert args.debug is True


def test_parse_no_debug_by_default():
    args = cli._build_parser().parse_args(["doctor"])
    assert args.debug is False


# ─── doctor ─────────────────────────────────────────────────────────

def test_doctor_all_present(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(
        cli.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout="fake version 1.0\n", stderr=""),
    )
    checks = cli.run_doctor()
    by_name = {c.name: c for c in checks}
    assert by_name["ffmpeg"].ok
    assert by_name["ffprobe"].ok
    assert by_name["python"].ok
    assert by_name["pydantic"].ok
    assert cli.main(["doctor"]) == 0


def test_doctor_missing_ffmpeg_fails_hard(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda exe: None)
    checks = cli.run_doctor()
    assert not next(c for c in checks if c.name == "ffmpeg").ok
    assert cli.main(["doctor"]) == 1


def test_doctor_missing_pydantic_import_fails(monkeypatch):
    monkeypatch.setattr(cli.shutil, "which", lambda exe: f"/usr/bin/{exe}")
    monkeypatch.setattr(
        cli.subprocess, "run",
        lambda *a, **k: subprocess.CompletedProcess(a[0], 0, stdout="v1\n", stderr=""),
    )
    real_import_module = cli.importlib.import_module

    def fake_import(name, *a, **k):
        if name == "pydantic":
            raise ImportError("simulated missing pydantic")
        return real_import_module(name, *a, **k)

    monkeypatch.setattr(cli.importlib, "import_module", fake_import)
    assert cli.main(["doctor"]) == 1


# ─── error boundary ─────────────────────────────────────────────────

def test_main_missing_edit_returns_1_with_pretty_message(tmp_path, monkeypatch, capsys):
    monkeypatch.chdir(tmp_path)  # isolated dir, no devlog.toml -> no default_edit
    monkeypatch.setattr(cli, "_find_workspace_root", lambda *args, **kwargs: None)
    code = cli.main(["check"])
    assert code == 1
    err = capsys.readouterr().err
    assert "edit module is required" in err
    assert "Traceback" not in err


def test_main_debug_reraises_cli_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(cli, "_find_workspace_root", lambda *args, **kwargs: None)
    with pytest.raises(cli.CliError):
        cli.main(["--debug", "check"])


# ─── lazy-import boundary: compile/render errors surface cleanly ─────
#
# compile/ and render/ are implemented by parallel agents and may finish
# at any point during this build -- these tests must not depend on their
# real behavior either way. Instead they monkeypatch the real, live
# dlstudio.compile.build_timeline (looked up the same way the CLI handlers
# do it: `from dlstudio import compile as dl_compile`) to simulate the
# "still a stub" condition on demand, proving cmd_* handlers (a) actually
# call through the lazy import at call time (not a cached reference) and
# (b) let NotImplementedError bubble up to main()'s error boundary as a
# pretty one-liner (or a real traceback under --debug).

import dlstudio.compile as dl_compile_mod  # noqa: E402
import dlstudio.render as dl_render_mod  # noqa: E402


def _raise_not_implemented(*_a, **_k):
    raise NotImplementedError("stub")


@pytest.mark.parametrize("subcmd", ["check", "ir", "beats", "iter"])
def test_single_edit_commands_surface_lazy_import_error(tmp_path, monkeypatch, subcmd):
    pkg = _unique_pkg(f"proj_{subcmd}")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dl_compile_mod, "build_timeline", _raise_not_implemented)

    code = cli.main([subcmd, dotted])
    assert code == 1  # NotImplementedError caught by the top-level error boundary


@pytest.mark.parametrize("subcmd", ["check", "ir", "beats", "iter"])
def test_single_edit_commands_debug_reraises_lazy_import_error(tmp_path, monkeypatch, subcmd):
    pkg = _unique_pkg(f"proj_dbg_{subcmd}")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dl_compile_mod, "build_timeline", _raise_not_implemented)

    with pytest.raises(NotImplementedError):
        cli.main(["--debug", subcmd, dotted])


def test_compose_surfaces_lazy_import_error(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_compose")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    monkeypatch.setattr(dl_compile_mod, "build_timeline", _raise_not_implemented)

    with pytest.raises(NotImplementedError):
        cli.main(["--debug", "compose", dotted, "b01"])


# ─── compose worker: cache <-> render.render_beat boundary ───────────
# Built directly from hand-crafted IRBeat/Design/Timeline objects -- these
# never touch dlstudio.compile. render.render_beat is monkeypatched to
# control exactly what "cache miss" and "cache hit" behavior get exercised,
# independent of the real render implementation's state/availability.

def test_compose_worker_cache_miss_falls_through_to_render(tmp_path, monkeypatch):
    monkeypatch.setattr(dl_render_mod, "render_beat", _raise_not_implemented)
    beat = make_ir_beat(
        audio=str(tmp_path / "nope.wav"), words_path=str(tmp_path / "nope.json")
    )
    design = make_design()
    out_path = tmp_path / "out" / "b01.mp4"

    with pytest.raises(NotImplementedError):
        cli._compose_worker(
            beat, design, "draft", False, None,
            str(out_path), str(tmp_path / "cache"),
        )


def _prime_cache_pair(key: str, base: Path, content: bytes = b"cached-beat-bytes") -> None:
    """Publish a complete (MP4 + VO stem) pair under `key` — entry format 2
    requires the pair, so priming tests must stage both halves the way a
    real render_beat leaves them on disk."""
    base.parent.mkdir(parents=True, exist_ok=True)
    base.write_bytes(content)
    dl_cache.vo_stem_sibling(base).write_bytes(b"stem:" + content)
    dl_cache.put(key, base)


def test_compose_worker_cache_miss_renders_and_populates_cache(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"

    def fake_render_beat(beat, design, timeline, opts):
        # Real contract: MP4 in workdir + `<beat>_vo_stem.wav` sibling.
        p = Path(opts.workdir) / f"{beat.id}.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"freshly-rendered")
        dl_cache.vo_stem_sibling(p).write_bytes(b"freshly-rendered-stem")
        return p

    monkeypatch.setattr(dl_render_mod, "render_beat", fake_render_beat)

    beat = make_ir_beat()
    design = make_design()
    out_path = tmp_path / "out" / "b01.mp4"

    msg = cli._compose_worker(
        beat, design, "draft", False, None, str(out_path), str(cache_dir)
    )
    assert "rendered" in msg
    assert out_path.read_bytes() == b"freshly-rendered"
    # 0.2: the cache published the PAIR and the hit materialized the stem too.
    assert dl_cache.vo_stem_sibling(out_path).read_bytes() == b"freshly-rendered-stem"
    assert any(cache_dir.glob("*.mp4")) and any(cache_dir.glob("*.wav"))


def test_compose_worker_cache_hit_short_circuits_render(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(dl_cache, "CACHE_DIR", cache_dir)
    # If render_beat were called on a cache hit, this would blow up loudly
    # instead of silently succeeding -- proving the hit path truly skips it.
    monkeypatch.setattr(dl_render_mod, "render_beat", _raise_not_implemented)

    beat = make_ir_beat()
    design = make_design()

    # width normalized to the resolved design resolution (L3): _compose_worker
    # always hashes width=design.resolution[0], never None, so the key here
    # must match that, not the raw (possibly-None) width_px a caller passes.
    key = dl_cache.beat_key(beat, design, quality="draft", width=design.resolution[0], gpu=False)
    _prime_cache_pair(key, tmp_path / "prerendered.mp4", b"already-rendered")

    out_path = tmp_path / "out" / "b01.mp4"
    msg = cli._compose_worker(beat, design, "draft", False, None, str(out_path), None)
    assert "cache hit" in msg
    assert out_path.read_bytes() == b"already-rendered"


def _realistic_fake_render_beat(beat, design, timeline, opts):
    """Mirrors the REAL render_beat path contract (render/beat.py): writes
    `workdir/<beat.id>.mp4` and returns that path. no-cache regression tests
    MUST use this shape — the 0.3 defect (shutil.SameFileError) only fires
    when the returned path collides with the CLI's own out_path, which a
    made-up `<beat>_rendered.mp4` name can never reproduce."""
    p = Path(opts.workdir) / f"{beat.id}.mp4"
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_bytes(b"fresh-no-cache-bytes")
    return p


def test_compose_worker_no_cache_skips_cache_get_and_put(tmp_path, monkeypatch):
    """M2: `no_cache=True` must bypass BOTH the cache read and the cache
    write entirely -- dl2 iter --no-cache was a silent no-op before this
    flag was threaded through _compose_worker."""
    cache_calls = {"get": 0, "put": 0}

    def spy_get(key, out):
        cache_calls["get"] += 1
        return False

    def spy_put(key, path):
        cache_calls["put"] += 1

    monkeypatch.setattr(dl_cache, "get", spy_get)
    monkeypatch.setattr(dl_cache, "put", spy_put)
    monkeypatch.setattr(dl_render_mod, "render_beat", _realistic_fake_render_beat)

    beat = make_ir_beat()
    design = make_design()
    out_path = tmp_path / "out" / "b01.mp4"

    msg = cli._compose_worker(
        beat, design, "draft", False, None, str(out_path), None, None, True,
    )

    assert cache_calls == {"get": 0, "put": 0}
    assert "no-cache" in msg
    assert out_path.read_bytes() == b"fresh-no-cache-bytes"


def test_compose_worker_no_cache_out_path_equals_rendered_path(tmp_path, monkeypatch):
    """0.3 regression (PLAN_STUDIO_V2): render_beat writes `workdir/<beat>.mp4`
    and returns it; the CLI's no-cache paths pass workdir = out.parent, so the
    rendered path IS the destination. Copying a file onto itself raised
    shutil.SameFileError — the worker must succeed and leave the fresh bytes."""
    monkeypatch.setattr(dl_render_mod, "render_beat", _realistic_fake_render_beat)

    beat = make_ir_beat()
    design = make_design()
    # exactly what cmd_iter/_iterate_render passes: out lives in the workdir
    out_path = tmp_path / "data" / "finalize" / "b01.mp4"

    msg = cli._compose_worker(
        beat, design, "draft", False, None, str(out_path),
        str(tmp_path / "cache"), None, True,
    )

    assert "no-cache" in msg
    assert out_path.read_bytes() == b"fresh-no-cache-bytes"
    assert not any((tmp_path / "cache").glob("*")) if (tmp_path / "cache").exists() else True


def test_cmd_compose_no_cache_renders_without_samefile_error(tmp_path, monkeypatch):
    """0.3 regression for the `dl2 compose --no-cache` handler itself: its
    workdir is data/finalize and its out_path is data/finalize/<beat>.mp4 —
    identical paths; the handler must not die in shutil.copyfile."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(dl_cache, "CACHE_DIR", cache_dir)

    pkg = _unique_pkg("proj_compose_no_cache")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    project_root = (tmp_path / pkg).resolve()

    beat = make_ir_beat("b01")
    timeline = make_timeline([beat], design=make_design())
    monkeypatch.setattr(dl_compile_mod, "build_timeline", lambda edit: timeline)
    monkeypatch.setattr(dl_render_mod, "render_beat", _realistic_fake_render_beat)

    args = cli._build_parser().parse_args(["compose", dotted, "b01", "--no-cache"])
    code = cli.cmd_compose(args)

    assert code == 0
    out_file = project_root / "data" / "finalize" / "b01.mp4"
    assert out_file.read_bytes() == b"fresh-no-cache-bytes"
    assert not cache_dir.exists() or not any(cache_dir.iterdir())


def test_render_targets_serial_calls_worker_per_beat(tmp_path, monkeypatch):
    calls = []

    def fake_worker(beat, design, quality, gpu, width_px, out_path,
                    cache_dir_override, beat_chunks=None, no_cache=False):
        calls.append(beat.id)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"rendered")
        return "ok"

    monkeypatch.setattr(cli, "_compose_worker", fake_worker)

    beats = [make_ir_beat("b01"), make_ir_beat("b02")]
    design = make_design()
    beat_files = {b.id: tmp_path / f"{b.id}.mp4" for b in beats}

    cli._render_targets(
        beats, design,
        quality="draft", gpu=False, width_px=None,
        beat_files=beat_files, jobs=1,
    )

    assert calls == ["b01", "b02"]
    assert all(p.exists() for p in beat_files.values())


def test_render_targets_propagates_no_cache_to_worker(tmp_path, monkeypatch):
    """M2: cmd_iter --no-cache must actually reach the worker call, not
    silently stop at _render_targets."""
    seen_no_cache = []

    def fake_worker(beat, design, quality, gpu, width_px, out_path,
                    cache_dir_override, beat_chunks=None, no_cache=False):
        seen_no_cache.append(no_cache)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"rendered")
        return "ok"

    monkeypatch.setattr(cli, "_compose_worker", fake_worker)

    beats = [make_ir_beat("b01"), make_ir_beat("b02")]
    design = make_design()
    beat_files = {b.id: tmp_path / f"{b.id}.mp4" for b in beats}

    cli._render_targets(
        beats, design,
        quality="draft", gpu=False, width_px=None,
        beat_files=beat_files, jobs=1, no_cache=True,
    )

    assert seen_no_cache == [True, True]


@pytest.mark.slow
def test_render_targets_parallel_real_subprocess_boundary(tmp_path):
    """-j 2 really spawns worker processes -- a monkeypatch in this
    process can't reach across that boundary, so this exercises whatever
    dlstudio.render.render_beat actually is right now (stub or real).
    Either way, these beats reference nonexistent audio/asset paths, so
    the real worker call is guaranteed to fail with ffmpeg unable to read
    the missing source. The point of this test is that ProcessPoolExecutor
    + the lazy import correctly propagate THAT SPECIFIC failure back to the
    parent via fut.result() instead of silently losing it, hanging, or
    surfacing some unrelated error (e.g. a pickling/import failure) -- so
    the assertion is pinned to the real render failure's own message
    (render_beat's "ffmpeg failed" RuntimeError), not just "some Exception"."""
    beat_a, beat_b = make_ir_beat("b01"), make_ir_beat("b02")
    design = make_design()
    beat_files = {"b01": tmp_path / "b01.mp4", "b02": tmp_path / "b02.mp4"}

    old = os.environ.get("DLSTUDIO_CACHE_DIR")
    os.environ["DLSTUDIO_CACHE_DIR"] = str(tmp_path / "cache")
    try:
        with pytest.raises(RuntimeError, match="ffmpeg failed"):
            cli._render_targets(
                [beat_a, beat_b], design,
                quality="draft", gpu=False, width_px=None,
                beat_files=beat_files, jobs=2,
            )
    finally:
        if old is None:
            os.environ.pop("DLSTUDIO_CACHE_DIR", None)
        else:
            os.environ["DLSTUDIO_CACHE_DIR"] = old


# ─── cmd_iter --stale: restore-on-skip when the cache entry outlives the
# on-disk beat file (docs/issues/dlstudio-phase1-followups.md #5) ─────────
#
# --stale skips beats whose cache key already exists (nothing to render),
# but the beat's MP4 under data/finalize/ may since have been deleted (e.g.
# the workdir got cleaned). Before the fix, cmd_iter left that file missing
# and the trailing "missing rendered beats" check failed the whole `iter`
# even though the render was still sitting in cache. cmd_iter must restore
# it via dl_cache.get(key, path) when it notices the skip.

def test_cmd_iter_stale_restores_missing_cached_beat_file(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(dl_cache, "CACHE_DIR", cache_dir)

    pkg = _unique_pkg("proj_iter_stale")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    project_root = (tmp_path / pkg).resolve()

    beat = make_ir_beat("b01")
    raw_design = make_design()  # 1920x1080
    timeline = make_timeline([beat], design=raw_design)
    monkeypatch.setattr(dl_compile_mod, "build_timeline", lambda edit: timeline)

    # cmd_iter's own defaults: width_spec="540p" (no --width given), quality
    # "draft" (no --quality given), gpu=False -- must match exactly for the
    # cache key to line up with what cmd_iter itself computes.
    resized_design = cli._resize_design(raw_design, "540p")
    key = dl_cache.beat_key(
        beat, resized_design, quality="draft",
        width=resized_design.resolution[0], gpu=False,
    )

    # Prime the cache as if a prior `dl2 iter` run rendered b01 successfully.
    _prime_cache_pair(key, tmp_path / "prerendered.mp4")
    # ...but data/finalize/b01.mp4 was since deleted (e.g. workdir cleanup) --
    # cmd_iter must not have anything on disk for b01 at this point.
    assert not (project_root / "data" / "finalize" / "b01.mp4").exists()

    def fail_render_beat(*_a, **_k):
        raise AssertionError("render_beat must not run for a cache-hit beat")

    def fake_assemble(_timeline, beat_files, _opts):
        assert beat_files["b01"].exists(), "beat file must be restored before assemble"
        return project_root / "data" / "finalize" / "final.mp4"

    monkeypatch.setattr(dl_render_mod, "render_beat", fail_render_beat)
    monkeypatch.setattr(dl_render_mod, "assemble", fake_assemble)

    args = cli._build_parser().parse_args(["iter", dotted, "--stale"])
    code = cli.cmd_iter(args)

    assert code == 0
    restored = project_root / "data" / "finalize" / "b01.mp4"
    assert restored.exists()
    assert restored.read_bytes() == b"cached-beat-bytes"


def test_cmd_iter_stale_replaces_existing_file_with_cache_artifact(tmp_path, monkeypatch):
    """0.1 regression (PLAN_STUDIO_V2): on a cache hit, --stale must ALWAYS
    materialize the exact cache artifact. An existing data/finalize/<beat>.mp4
    may be a leftover from another resolution/quality/edit — its presence
    proves nothing, and before the fix it silently reached assemble.

    (Replaces test_cmd_iter_stale_skips_restore_when_file_already_present,
    which pinned the defective skip-if-present behaviour.)"""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(dl_cache, "CACHE_DIR", cache_dir)

    pkg = _unique_pkg("proj_iter_stale_present")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    project_root = (tmp_path / pkg).resolve()

    beat = make_ir_beat("b01")
    raw_design = make_design()
    timeline = make_timeline([beat], design=raw_design)
    monkeypatch.setattr(dl_compile_mod, "build_timeline", lambda edit: timeline)

    resized_design = cli._resize_design(raw_design, "540p")
    key = dl_cache.beat_key(
        beat, resized_design, quality="draft",
        width=resized_design.resolution[0], gpu=False,
    )
    # The cache holds this key's true artifact (e.g. the 540p draft render)...
    _prime_cache_pair(key, tmp_path / "prerendered.mp4", b"cached-540p-draft-bytes")

    # ...but data/finalize/b01.mp4 currently holds SOMETHING ELSE (say, a
    # leftover 1080p render from another invocation).
    out_dir = project_root / "data" / "finalize"
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = out_dir / "b01.mp4"
    existing.write_bytes(b"leftover-from-another-resolution")

    monkeypatch.setattr(dl_render_mod, "render_beat",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("render_beat must not run for a cache-hit beat")))
    monkeypatch.setattr(dl_render_mod, "assemble",
                        lambda _tl, _bf, _o: out_dir / "final.mp4")

    args = cli._build_parser().parse_args(["iter", dotted, "--stale"])
    code = cli.cmd_iter(args)

    assert code == 0
    # The on-disk file must now BE the cache artifact, not the leftover.
    assert existing.read_bytes() == b"cached-540p-draft-bytes"
    # ...and its VO stem pair came with it (0.2).
    assert dl_cache.vo_stem_sibling(existing).read_bytes() == b"stem:cached-540p-draft-bytes"


# ─── M2: `dl2 iter --no-cache` must actually bypass the cache ─────────────
#
# --no-cache was wired onto the argparser but cmd_iter never read
# args.no_cache -- it was a silent no-op. Prime the cache under exactly the
# key cmd_iter's own (draft/540p) defaults would compute, then run
# `iter --no-cache` and prove render_beat runs anyway (the pre-existing
# cache hit is bypassed) and the output is the freshly rendered bytes, not
# the stale cached ones.

def test_cmd_iter_no_cache_bypasses_existing_cache_entry(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(dl_cache, "CACHE_DIR", cache_dir)

    pkg = _unique_pkg("proj_iter_no_cache")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    project_root = (tmp_path / pkg).resolve()

    beat = make_ir_beat("b01")
    raw_design = make_design()
    timeline = make_timeline([beat], design=raw_design)
    monkeypatch.setattr(dl_compile_mod, "build_timeline", lambda edit: timeline)

    resized_design = cli._resize_design(raw_design, "540p")
    key = dl_cache.beat_key(
        beat, resized_design, quality="draft",
        width=resized_design.resolution[0], gpu=False,
    )
    _prime_cache_pair(key, tmp_path / "prerendered.mp4", b"stale-cached-bytes")

    render_calls = []

    def fake_render_beat(beat, design, timeline, opts):
        # Real path contract: render_beat writes workdir/<beat>.mp4 and
        # returns it — under `iter --no-cache` that IS the destination file
        # (the 0.3 SameFileError class), so the fake must mirror it.
        render_calls.append(beat.id)
        p = Path(opts.workdir) / f"{beat.id}.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"freshly-rendered-bytes")
        return p

    put_calls = []
    real_put = dl_cache.put

    def spy_put(k, p):
        put_calls.append(k)
        real_put(k, p)

    monkeypatch.setattr(dl_render_mod, "render_beat", fake_render_beat)
    monkeypatch.setattr(dl_cache, "put", spy_put)
    monkeypatch.setattr(dl_render_mod, "assemble",
                        lambda _tl, beat_files, _o: beat_files["b01"])

    args = cli._build_parser().parse_args(["iter", dotted, "--no-cache"])
    code = cli.cmd_iter(args)

    assert code == 0
    assert render_calls == ["b01"]       # the existing cache hit was bypassed
    assert put_calls == []               # and nothing was (re-)published to it
    out_file = project_root / "data" / "finalize" / "b01.mp4"
    assert out_file.read_bytes() == b"freshly-rendered-bytes"


# ─── 0.4: checks are a mandatory pre-render gate on every render path ─────
#
# resolve profile -> compile -> RUN CHECKS -> render -> verify output.
# Errors always block (draft included); warnings never block.

def _timeline_with_missing_asset(beat):
    from dlstudio.ir import AssetProbe

    tl = make_timeline([beat], design=make_design())
    return tl.model_copy(update={"assets": {
        "data/gone.png": AssetProbe(path="data/gone.png", kind="image", exists=False),
    }})


def _timeline_with_warning_only(beat):
    from dlstudio.ir import CheckIssue

    tl = make_timeline([beat], design=make_design())
    return tl.model_copy(update={"diagnostics": [
        CheckIssue(severity="warn", code="VQ-OFFSET",
                   message="scene offset clamped", where="b01"),
    ]})


def test_cmd_iter_blocks_on_check_errors(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_iter_gate")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    beat = make_ir_beat("b01")
    monkeypatch.setattr(dl_compile_mod, "build_timeline",
                        lambda edit: _timeline_with_missing_asset(beat))
    monkeypatch.setattr(dl_render_mod, "render_beat",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("render must not start when checks error")))

    args = cli._build_parser().parse_args(["iter", dotted])
    with pytest.raises(cli.CliError, match="pre-render checks failed"):
        cli.cmd_iter(args)


def test_cmd_compose_blocks_on_check_errors(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_compose_gate")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    beat = make_ir_beat("b01")
    monkeypatch.setattr(dl_compile_mod, "build_timeline",
                        lambda edit: _timeline_with_missing_asset(beat))
    monkeypatch.setattr(dl_render_mod, "render_beat",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("render must not start when checks error")))

    args = cli._build_parser().parse_args(["compose", dotted, "b01", "--no-cache"])
    with pytest.raises(cli.CliError, match="pre-render checks failed"):
        cli.cmd_compose(args)


@pytest.mark.parametrize("command", ["render", "final"])
def test_cmd_render_and_final_block_on_check_errors(tmp_path, monkeypatch, command):
    pkg = _unique_pkg(f"proj_{command}_gate")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    beat = make_ir_beat("b01")
    monkeypatch.setattr(dl_compile_mod, "build_timeline",
                        lambda edit: _timeline_with_missing_asset(beat))
    monkeypatch.setattr(dl_render_mod, "render_beat",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("render must not start when checks error")))

    args = cli._build_parser().parse_args([command, dotted])
    with pytest.raises(cli.CliError, match="pre-render checks failed"):
        args.func(args)


def test_cmd_iter_proceeds_when_only_warnings(tmp_path, monkeypatch, capsys):
    """Draft may proceed on warnings — only mechanical ERRORS block."""
    pkg = _unique_pkg("proj_iter_warnok")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    project_root = (tmp_path / pkg).resolve()

    beat = make_ir_beat("b01")
    monkeypatch.setattr(dl_compile_mod, "build_timeline",
                        lambda edit: _timeline_with_warning_only(beat))
    monkeypatch.setattr(dl_render_mod, "render_beat", _realistic_fake_render_beat)
    monkeypatch.setattr(dl_render_mod, "assemble",
                        lambda _tl, beat_files, _o: beat_files["b01"])

    args = cli._build_parser().parse_args(["iter", dotted, "--no-cache"])
    code = cli.cmd_iter(args)

    assert code == 0
    assert (project_root / "data" / "finalize" / "b01.mp4").exists()
    assert "[WARN] VQ-OFFSET" in capsys.readouterr().out


# ─── M4: `dl2 beats` defaults must match `dl2 iter`'s (draft/540p) ────────
#
# cmd_beats used to default to quality="standard" / native width while
# cmd_iter renders (and caches) at draft/540p, so beat_key never lined up
# between the two commands and `dl2 beats` always reported cached=no right
# after a plain `dl2 iter`. Both commands must now compute the identical
# key for the identical (no-flags) invocation.

def test_cmd_beats_default_key_matches_cmd_iter_default_key():
    beat = make_ir_beat("b01")
    raw_design = make_design()  # 1920x1080 native

    beats_args = cli._build_parser().parse_args(["beats", "some.edit"])
    iter_args = cli._build_parser().parse_args(["iter", "some.edit"])

    beats_width_spec = beats_args.width or "540p"
    beats_quality = beats_args.quality or "draft"
    beats_design = cli._resize_design(raw_design, beats_width_spec)
    beats_width_px = beats_design.resolution[0]

    iter_width_spec = iter_args.width or "540p"
    iter_quality = iter_args.quality or "draft"
    iter_design = cli._resize_design(raw_design, iter_width_spec)
    iter_width_px = iter_design.resolution[0]

    beats_key = dl_cache.beat_key(
        beat, beats_design, quality=beats_quality, width=beats_width_px, gpu=False,
    )
    iter_key = dl_cache.beat_key(
        beat, iter_design, quality=iter_quality, width=iter_width_px, gpu=False,
    )
    assert beats_key == iter_key


def test_cmd_beats_reports_cached_after_plain_iter(tmp_path, monkeypatch, capsys):
    """End-to-end: cache a beat exactly as a plain `dl2 iter` (no flags)
    would, then run `dl2 beats` with no flags and confirm it reports
    cached=yes for that beat."""
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(dl_cache, "CACHE_DIR", cache_dir)

    pkg = _unique_pkg("proj_beats_match_iter")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    beat = make_ir_beat("b01")
    raw_design = make_design()
    timeline = make_timeline([beat], design=raw_design)
    monkeypatch.setattr(dl_compile_mod, "build_timeline", lambda edit: timeline)

    # Prime the cache exactly as cmd_iter's own (draft/540p) defaults would.
    resized_design = cli._resize_design(raw_design, "540p")
    key = dl_cache.beat_key(
        beat, resized_design, quality="draft",
        width=resized_design.resolution[0], gpu=False,
    )
    _prime_cache_pair(key, tmp_path / "prerendered.mp4", b"cached-bytes")

    args = cli._build_parser().parse_args(["beats", dotted])
    code = cli.cmd_beats(args)

    assert code == 0
    out = capsys.readouterr().out
    lines = [ln for ln in out.splitlines() if ln.startswith("b01")]
    assert len(lines) == 1
    assert lines[0].split()[-1] == "yes"   # cached column


# ─── Phase 2: `dl2 render` / `dl2 final` (full mix assemble) ──────────────
#
# render/final reuse cmd_iter's machinery (_iterate_render) and differ ONLY in
# their default width/quality; both must run the full mix assemble. These tests
# stub the render + assemble seams (no ffmpeg) and assert the resolved
# width/quality that flows into RenderOpts / assemble.

def _run_full_render(tmp_path, monkeypatch, argv, cmd, *, design,
                     toml_body=None):
    """Wire a fake project + timeline, stub _render_targets (writes the beat
    files) and assemble (captures the RenderOpts), then run `cmd`. Returns the
    captured RenderOpts."""
    pkg = _unique_pkg("proj_full_render")
    dotted = _make_fake_project(tmp_path, pkg)
    if toml_body is not None:
        (tmp_path / "devlog.toml").write_text(toml_body.format(dotted=dotted),
                                              encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    beat = make_ir_beat("b01")
    timeline = make_timeline([beat], design=design)
    monkeypatch.setattr(dl_compile_mod, "build_timeline", lambda edit: timeline)

    def fake_render_targets(targets, design_arg, *, quality, gpu, width_px,
                            beat_files, jobs, chunks_by_beat=None, no_cache=False):
        for _bid, p in beat_files.items():
            p.parent.mkdir(parents=True, exist_ok=True)
            p.write_bytes(b"beat")

    monkeypatch.setattr(cli, "_render_targets", fake_render_targets)

    captured = {}

    def fake_assemble(_tl, beat_files, opts):
        captured["opts"] = opts
        out = Path(_tl.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"final")
        return out

    monkeypatch.setattr(dl_render_mod, "assemble", fake_assemble)

    args = cli._build_parser().parse_args([argv[0], dotted, *argv[1:]])
    code = cmd(args)
    assert code == 0
    return captured["opts"]


def test_cmd_render_defaults_1080p_standard(tmp_path, monkeypatch):
    opts = _run_full_render(
        tmp_path, monkeypatch, ["render"], cli.cmd_render,
        design=make_design(3840, 2160))
    assert opts.quality == "standard"
    assert opts.width == 1920            # 1080p preset resolves a 3840-wide design to 1920


def test_cmd_render_explicit_flags_override(tmp_path, monkeypatch):
    opts = _run_full_render(
        tmp_path, monkeypatch, ["render", "--width", "720p", "--quality", "master"],
        cli.cmd_render, design=make_design(3840, 2160))
    assert opts.quality == "master"
    assert opts.width == 1280            # 720p preset


def test_cmd_final_defaults_1080p_upload_without_config(tmp_path, monkeypatch):
    opts = _run_full_render(
        tmp_path, monkeypatch, ["final"], cli.cmd_final,
        design=make_design(3840, 2160))
    assert opts.quality == "upload"
    assert opts.width == 1920


def test_cmd_final_reads_v2_final_config(tmp_path, monkeypatch):
    toml = ('[v2]\ndefault_edit = "{dotted}"\n'
            '[v2.final]\nwidth = "720p"\nquality = "master"\n')
    opts = _run_full_render(
        tmp_path, monkeypatch, ["final"], cli.cmd_final,
        design=make_design(3840, 2160), toml_body=toml)
    assert opts.quality == "master"
    assert opts.width == 1280


def test_cmd_final_explicit_flags_beat_config(tmp_path, monkeypatch):
    toml = ('[v2]\ndefault_edit = "{dotted}"\n'
            '[v2.final]\nwidth = "720p"\nquality = "master"\n')
    opts = _run_full_render(
        tmp_path, monkeypatch, ["final", "--width", "4k", "--quality", "upload"],
        cli.cmd_final, design=make_design(3840, 2160), toml_body=toml)
    assert opts.quality == "upload"
    assert opts.width == 3840            # 4k preset, explicit flag wins over config


def test_cmd_render_runs_full_assemble(tmp_path, monkeypatch):
    """render must actually call assemble (the full mix pass), not stop at
    per-beat rendering."""
    called = {}

    pkg = _unique_pkg("proj_render_assembles")
    dotted = _make_fake_project(tmp_path, pkg)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    timeline = make_timeline([make_ir_beat("b01")], design=make_design())
    monkeypatch.setattr(dl_compile_mod, "build_timeline", lambda edit: timeline)
    monkeypatch.setattr(cli, "_render_targets",
                        lambda targets, d, **kw: [
                            kw["beat_files"][b.id].parent.mkdir(parents=True, exist_ok=True)
                            or kw["beat_files"][b.id].write_bytes(b"x") for b in targets])

    def fake_assemble(_tl, beat_files, opts):
        called["assemble"] = True
        out = Path(_tl.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"final")
        return out

    monkeypatch.setattr(dl_render_mod, "assemble", fake_assemble)

    args = cli._build_parser().parse_args(["render", dotted])
    assert cli.cmd_render(args) == 0
    assert called.get("assemble") is True


# ─── Phase 3: services + studio commands ─────────────────────────────────
#
# cmd_audio/transcribe/scratch-tts call into dlstudio.services; the service
# funcs are heavy (ffmpeg/whisper/SAPI), so these tests monkeypatch the live
# service attributes and assert the CLI passes the right args. cmd_studio's
# server start is monkeypatched (create_app + uvicorn.run) so nothing binds.

import dlstudio.services as dl_services_mod  # noqa: E402

_BEAT_EDIT_BODY = textwrap.dedent(
    """
    from dlstudio.model import Beat, Chunk, Design, Edit, Fonts, Palette, Plate

    EDIT = Edit(
        name="fake-edit",
        design=Design(
            resolution=(1920, 1080),
            palette=Palette(tokens={"bg": "#000000", "text": "#ffffff"}),
            fonts=Fonts(main="main.ttf"),
        ),
        beats={
            "b01": Beat(
                audio="data/finalize/b01_vo.wav",
                words="data/finalize/b01_words.json",
                vo="scratch narration line",
                chunks=[Chunk(words=(0, 1), content=Plate(text="X"))],
            ),
        },
        order=["b01"],
        output="data/finalize/output.mp4",
    )
    """
)


class _FakeAudioResult:
    input_i = -16.0
    duration = 2.5


def test_cmd_audio_calls_services_with_right_args(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_audio")
    dotted = _make_fake_project(tmp_path, pkg, edit_body=_BEAT_EDIT_BODY)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / pkg / "rec.webm").write_bytes(b"raw-take")

    calls = {}

    def fake_pt(recording, out_wav, **kw):
        calls["pt"] = (Path(recording), Path(out_wav))
        Path(out_wav).write_bytes(b"processed")
        return _FakeAudioResult()

    def fake_tr(wav, out_json, **kw):
        calls["tr"] = (Path(wav), Path(out_json), kw)
        Path(out_json).write_text('{"words":[]}', encoding="utf-8")
        return Path(out_json)

    monkeypatch.setattr(dl_services_mod, "process_take", fake_pt)
    monkeypatch.setattr(dl_services_mod, "transcribe", fake_tr)

    assert cli.main(["audio", dotted, "b01", "rec.webm"]) == 0
    assert calls["pt"][0] == Path("rec.webm")
    assert calls["pt"][1].parent == Path("data/finalize")
    assert calls["pt"][1].name.startswith(".b01_vo.tmp-")
    assert calls["tr"][0] == calls["pt"][1]
    assert calls["tr"][1].parent == Path("data/finalize")
    assert calls["tr"][1].name.startswith(".b01_words.tmp-")
    assert calls["tr"][2] == {"language": "ru", "model": "medium"}
    assert Path("data/finalize/b01_vo.wav").read_bytes() == b"processed"
    assert json.loads(Path("data/finalize/b01_words.json").read_text(
        encoding="utf-8"
    )) == {"words": []}


def test_cmd_audio_transcribe_failure_preserves_previous_bundle(
    tmp_path,
    monkeypatch,
):
    pkg = _unique_pkg("proj_audio_atomic")
    dotted = _make_fake_project(tmp_path, pkg, edit_body=_BEAT_EDIT_BODY)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    project = tmp_path / pkg
    (project / "rec.webm").write_bytes(b"raw-take")
    audio = project / "data" / "finalize" / "b01_vo.wav"
    words = project / "data" / "finalize" / "b01_words.json"
    audio.parent.mkdir(parents=True)
    audio.write_bytes(b"old-audio")
    words.write_text('{"words":["old"]}', encoding="utf-8")

    def fake_pt(_recording, out_wav, **_kw):
        Path(out_wav).write_bytes(b"new-audio")
        return _FakeAudioResult()

    def failing_transcribe(_wav, out_json, **_kw):
        Path(out_json).write_text('{"words":["partial"]}', encoding="utf-8")
        raise RuntimeError("transcription failed")

    monkeypatch.setattr(dl_services_mod, "process_take", fake_pt)
    monkeypatch.setattr(dl_services_mod, "transcribe", failing_transcribe)

    assert cli.main(["audio", dotted, "b01", "rec.webm"]) == 1
    assert audio.read_bytes() == b"old-audio"
    assert json.loads(words.read_text(encoding="utf-8")) == {"words": ["old"]}
    assert not list(audio.parent.glob(".*.tmp-*"))


def test_cmd_audio_unknown_beat_errors(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_audio_bad")
    dotted = _make_fake_project(tmp_path, pkg, edit_body=_BEAT_EDIT_BODY)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    (tmp_path / pkg / "rec.webm").write_bytes(b"raw-take")
    assert cli.main(["audio", dotted, "nope", "rec.webm"]) == 1


def test_cmd_speech_edit_applies_agent_plan_and_promotes_bundle(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_speech_edit")
    dotted = _make_fake_project(tmp_path, pkg, edit_body=_BEAT_EDIT_BODY)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    project = tmp_path / pkg
    finalize = project / "data" / "finalize"
    finalize.mkdir(parents=True)
    (finalize / "b01_vo.wav").write_bytes(b"source-audio")
    (finalize / "b01_words.json").write_text("{}", encoding="utf-8")
    audio_hash = hashlib.sha256(b"source-audio").hexdigest()
    words_hash = hashlib.sha256(b"{}").hexdigest()
    (project / "agent_plan.json").write_text(json.dumps({
        "schema": "dlstudio.speech-edit/v1",
        "input": {
            "audio_sha256": audio_hash,
            "words_sha256": words_hash,
            "duration": 2.0,
        },
        "cuts": [{
            "t0": 0.4,
            "t1": 0.8,
            "reasons": ["false_start"],
            "sources": ["agent"],
            "confidence": 1.0,
        }],
    }), encoding="utf-8")
    calls = {}

    def fake_execute(source_audio, source_words, output_audio, output_words,
                     artifact_path, **kwargs):
        calls["paths"] = tuple(map(Path, (
            source_audio, source_words, output_audio, output_words, artifact_path,
        )))
        calls["plan"] = kwargs["plan"]
        Path(output_audio).write_bytes(b"edited-audio")
        Path(output_words).write_text('{"words": []}', encoding="utf-8")
        Path(artifact_path).write_text('{"schema": "dlstudio.speech-edit/v1"}', encoding="utf-8")
        return type("Result", (), {
            "source_duration": 2.0,
            "duration": 1.6,
            "removed_duration": 0.4,
            "cut_count": 1,
        })()

    monkeypatch.setattr(dl_services_mod, "execute_speech_edit", fake_execute)

    assert cli.main(["speech-edit", dotted, "b01", "agent_plan.json"]) == 0
    assert calls["paths"][0].name == f"b01_speech_edit.input-{audio_hash[:12]}.wav"
    assert calls["paths"][1].name == f"b01_speech_edit.input-{words_hash[:12]}.json"
    assert calls["paths"][0].read_bytes() == b"source-audio"
    assert calls["paths"][1].read_text(encoding="utf-8") == "{}"
    assert calls["paths"][0] != Path("data/finalize/b01_vo.wav")
    assert calls["paths"][1] != Path("data/finalize/b01_words.json")
    assert calls["paths"][0].exists()
    assert calls["paths"][1].exists()
    assert calls["paths"][0].parent == Path("data/finalize")
    assert calls["paths"][1].parent == Path("data/finalize")
    assert calls["paths"][2].name.startswith(".b01_vo.speech-edit-")
    assert calls["paths"][3].name.startswith(".b01_words.speech-edit-")
    assert calls["paths"][4].name.startswith(".b01_speech_edit.speech-edit-")
    assert calls["paths"][0].suffix == ".wav"
    assert calls["paths"][1].suffix == ".json"
    assert calls["paths"][0].is_file()
    assert calls["paths"][1].is_file()
    assert calls["paths"][0].read_bytes() != (finalize / "b01_vo.wav").read_bytes()
    assert calls["plan"].cuts[0].reasons == ("false_start",)
    assert (finalize / "b01_vo.wav").read_bytes() == b"edited-audio"
    assert json.loads((finalize / "b01_words.json").read_text(encoding="utf-8")) == {"words": []}
    assert (finalize / "b01_speech_edit.json").exists()


def test_cmd_speech_edit_rejects_stale_plan_before_creating_input_snapshots(
    tmp_path, monkeypatch
):
    pkg = _unique_pkg("proj_speech_edit_stale")
    dotted = _make_fake_project(tmp_path, pkg, edit_body=_BEAT_EDIT_BODY)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    project = tmp_path / pkg
    finalize = project / "data" / "finalize"
    finalize.mkdir(parents=True)
    (finalize / "b01_vo.wav").write_bytes(b"current-audio")
    (finalize / "b01_words.json").write_text("{}", encoding="utf-8")
    plan_path = project / "stale_plan.json"
    plan_path.write_text(json.dumps({
        "schema": "dlstudio.speech-edit/v1",
        "input": {
            "audio_sha256": hashlib.sha256(b"old-audio").hexdigest(),
            "words_sha256": hashlib.sha256(b"{}").hexdigest(),
            "duration": 2.0,
        },
        "cuts": [],
    }), encoding="utf-8")

    assert cli.main(["speech-edit", dotted, "b01", str(plan_path)]) == 1
    assert not list(finalize.glob("b01_speech_edit.input-*"))
    assert not list(finalize.glob(".*.snapshot"))
    assert (finalize / "b01_vo.wav").read_bytes() == b"current-audio"


def test_speech_edit_bundle_promotion_rolls_back_on_replace_failure(tmp_path, monkeypatch):
    from dlstudio.services import bundle as bundle_service

    data = tmp_path / "data"
    data.mkdir()
    staged_audio = data / "staged.wav"
    staged_words = data / "staged.json"
    audio = data / "audio.wav"
    words = data / "words.json"
    staged_audio.write_bytes(b"new-audio")
    staged_words.write_bytes(b"new-words")
    audio.write_bytes(b"old-audio")
    words.write_bytes(b"old-words")
    real_replace = bundle_service.os.replace

    def fail_second_promotion(src, dst):
        if Path(src) == staged_words and Path(dst) == words:
            raise OSError("simulated replace failure")
        return real_replace(src, dst)

    monkeypatch.setattr(bundle_service.os, "replace", fail_second_promotion)
    with pytest.raises(OSError, match="simulated"):
        cli._promote_bundle([(staged_audio, audio), (staged_words, words)])

    assert audio.read_bytes() == b"old-audio"
    assert words.read_bytes() == b"old-words"


def test_cmd_speech_edit_can_prepare_hash_bound_plan_for_agent(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_speech_plan")
    dotted = _make_fake_project(tmp_path, pkg, edit_body=_BEAT_EDIT_BODY)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)
    project = tmp_path / pkg
    finalize = project / "data" / "finalize"
    finalize.mkdir(parents=True)
    (finalize / "b01_vo.wav").write_bytes(b"source-audio")
    (finalize / "b01_words.json").write_text("{}", encoding="utf-8")
    plan = dl_services_mod.SpeechEditPlan(
        source_duration=2.0,
        cuts=(),
        input_audio_sha256="a" * 64,
        input_words_sha256="b" * 64,
    )
    monkeypatch.setattr(
        dl_services_mod, "build_automatic_plan_from_files", lambda *_args: plan,
    )

    assert cli.main([
        "speech-edit", dotted, "b01",
        "--prepare-plan", "data/review/b01_plan.json",
    ]) == 0
    prepared = json.loads(
        (project / "data/review/b01_plan.json").read_text(encoding="utf-8")
    )
    assert prepared["input"]["audio_sha256"] == "a" * 64
    assert prepared["cuts"] == []
    assert (finalize / "b01_vo.wav").read_bytes() == b"source-audio"


def test_cmd_transcribe_calls_service_with_right_args(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    (tmp_path / "in.wav").write_bytes(b"wav-bytes")

    calls = {}

    def fake_tr(wav, out_json, **kw):
        calls["tr"] = (Path(wav), Path(out_json), kw)
        return Path(out_json)

    monkeypatch.setattr(dl_services_mod, "transcribe", fake_tr)
    assert cli.main([
        "transcribe", "in.wav", "out.json",
        "--language", "en", "--model", "small", "--backend", "whisper",
    ]) == 0
    assert calls["tr"][0] == Path("in.wav")
    assert calls["tr"][1] == Path("out.json")
    assert calls["tr"][2] == {"language": "en", "model": "small", "backend": "whisper"}


def test_cmd_scratch_tts_uses_beat_vo_text(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_scratch")
    dotted = _make_fake_project(tmp_path, pkg, edit_body=_BEAT_EDIT_BODY)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    calls = {}

    def fake_tts(text, out_wav, **kw):
        calls["tts"] = (text, Path(out_wav))
        return Path(out_wav)

    monkeypatch.setattr(dl_services_mod, "scratch_tts", fake_tts)
    assert cli.main(["scratch-tts", dotted, "b01"]) == 0
    assert calls["tts"][0] == "scratch narration line"
    assert calls["tts"][1] == Path("data/scratch/b01_scratch_tts.wav")


def test_cmd_scratch_tts_text_override(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_scratch2")
    dotted = _make_fake_project(tmp_path, pkg, edit_body=_BEAT_EDIT_BODY)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    calls = {}
    monkeypatch.setattr(
        dl_services_mod, "scratch_tts",
        lambda text, out_wav, **kw: calls.setdefault("text", text) or Path(out_wav),
    )
    assert cli.main(["scratch-tts", dotted, "b01", "--text", "custom override words"]) == 0
    assert calls["text"] == "custom override words"


def test_cmd_studio_arg_wiring(tmp_path, monkeypatch):
    pytest.importorskip("fastapi")
    monkeypatch.chdir(tmp_path)
    import uvicorn as _uv
    import dlstudio.api as _api

    captured = {}

    def fake_create_app(edit_module):
        captured["edit"] = edit_module
        return "APP"

    monkeypatch.setattr(_api, "create_app", fake_create_app)
    monkeypatch.setattr(_uv, "run", lambda app, **kw: captured.update(run=(app, kw)))

    assert cli.main(["studio", "some.pkg.edit", "--port", "9999"]) == 0
    assert captured["edit"] == "some.pkg.edit"
    assert captured["run"][0] == "APP"
    assert captured["run"][1]["host"] == "127.0.0.1"
    assert captured["run"][1]["port"] == 9999


def test_cmd_studio_dev_prints_hint(tmp_path, monkeypatch, capsys):
    pytest.importorskip("fastapi")
    monkeypatch.chdir(tmp_path)
    import uvicorn as _uv
    import dlstudio.api as _api
    monkeypatch.setattr(_api, "create_app", lambda edit_module: "APP")
    monkeypatch.setattr(_uv, "run", lambda app, **kw: None)

    assert cli.main(["studio", "some.pkg.edit", "--dev"]) == 0
    out = capsys.readouterr().out
    assert "npm run dev" in out
    # the hint must point at the real webui dir, not the stale src/ path
    assert "common/dlstudio/webui" in out
    assert "src/dlstudio/webui" not in out


# ─── arg parsing for the new commands ────────────────────────────────────

def test_parse_audio_defaults():
    args = cli._build_parser().parse_args(["audio", "pkg.edit", "b01", "rec.webm"])
    assert (args.edit, args.beat_id, args.recording) == ("pkg.edit", "b01", "rec.webm")
    assert args.language == "ru" and args.model == "medium"
    assert args.func is cli.cmd_audio


def test_parse_transcribe_defaults():
    args = cli._build_parser().parse_args(["transcribe", "in.wav", "out.json"])
    assert (args.wav, args.out) == ("in.wav", "out.json")
    assert args.backend == "auto" and args.language == "ru" and args.model == "medium"
    assert args.func is cli.cmd_transcribe


def test_parse_scratch_tts_disambiguation():
    args = cli._build_parser().parse_args(["scratch-tts", "pkg.edit", "b01"])
    assert args.edit_or_beat == "pkg.edit" and args.beat_id == "b01"
    assert args.text is None and args.func is cli.cmd_scratch_tts


def test_parse_studio_defaults():
    args = cli._build_parser().parse_args(["studio"])
    assert args.edit is None and args.port == 8788 and args.dev is False
    assert args.func is cli.cmd_studio


# ─── Phase 4: `dl2 publish` / `dl2 stock` CLI wiring ─────────────────────
#
# cmd_publish/cmd_stock_search/cmd_stock_download call into
# dlstudio.services (generate_youtube_package / search / download); these
# tests monkeypatch the live service attributes (same pattern as
# cmd_audio/cmd_transcribe/cmd_scratch_tts above) and assert the CLI passes
# the right args -- no real HTTP, no real markdown generation.

def test_parse_publish_defaults():
    args = cli._build_parser().parse_args(["publish", "pkg.edit"])
    assert args.edit == "pkg.edit" and args.out is None
    assert args.func is cli.cmd_publish


def test_parse_publish_with_out():
    args = cli._build_parser().parse_args(["publish", "pkg.edit", "--out", "custom.md"])
    assert args.out == "custom.md"


def test_parse_stock_search_defaults():
    args = cli._build_parser().parse_args(["stock", "search", "cats"])
    assert args.query == "cats"
    assert args.source == "pexels"
    assert args.aspect == "16:9"
    assert args.per_page == 10
    assert args.out is None
    assert args.func is cli.cmd_stock_search


def test_parse_stock_search_explicit_flags():
    args = cli._build_parser().parse_args([
        "stock", "search", "dogs", "--source", "pixabay", "--aspect", "9:16",
        "--per-page", "3", "--out", "results.json",
    ])
    assert (args.source, args.aspect, args.per_page, args.out) == ("pixabay", "9:16", 3, "results.json")


def test_parse_stock_download_requires_out():
    with pytest.raises(SystemExit):
        cli._build_parser().parse_args(["stock", "download", "manifest.json"])


def test_parse_stock_download_defaults():
    args = cli._build_parser().parse_args(["stock", "download", "manifest.json", "--out", "outdir"])
    assert args.manifest == "manifest.json" and args.out == "outdir"
    assert args.func is cli.cmd_stock_download


def test_parse_stock_requires_subcommand():
    with pytest.raises(SystemExit):
        cli._build_parser().parse_args(["stock"])


def test_cmd_publish_uses_default_out_and_passes_timeline(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_publish")
    dotted = _make_fake_project(tmp_path, pkg, edit_body=_BEAT_EDIT_BODY)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    timeline = make_timeline([make_ir_beat("b01")], design=make_design())
    monkeypatch.setattr(dl_compile_mod, "build_timeline", lambda edit: timeline)

    calls = {}

    def fake_generate(edit, *, out_path, **kw):
        calls["edit"] = edit
        calls["out_path"] = Path(out_path)
        calls["kw"] = kw
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("stub package", encoding="utf-8")
        return Path(out_path)

    monkeypatch.setattr(dl_services_mod, "generate_youtube_package", fake_generate)

    assert cli.main(["publish", dotted]) == 0
    # cmd_publish's default out is relative to the project root cli._load_edit
    # already chdir'd into -- compare the relative form, not an absolute path.
    assert calls["out_path"] == Path("data") / "publish" / "youtube_package.md"
    assert calls["kw"]["chapters_from_timeline"] is timeline
    assert calls["out_path"].exists()


def test_cmd_publish_custom_out(tmp_path, monkeypatch):
    pkg = _unique_pkg("proj_publish_out")
    dotted = _make_fake_project(tmp_path, pkg, edit_body=_BEAT_EDIT_BODY)
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    timeline = make_timeline([make_ir_beat("b01")], design=make_design())
    monkeypatch.setattr(dl_compile_mod, "build_timeline", lambda edit: timeline)

    calls = {}

    def fake_generate(edit, *, out_path, **kw):
        calls["out_path"] = Path(out_path)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_text("stub", encoding="utf-8")
        return Path(out_path)

    monkeypatch.setattr(dl_services_mod, "generate_youtube_package", fake_generate)

    assert cli.main(["publish", dotted, "--out", "custom/pkg.md"]) == 0
    assert calls["out_path"] == Path("custom") / "pkg.md"


def test_cmd_stock_search_prints_json_to_stdout(monkeypatch, capsys):
    class _FakeResult:
        def to_dict(self):
            return {"source": "pexels", "id": "1", "url": "https://x/1.mp4"}

    calls = {}

    def fake_search(query, *, source, aspect, per_page):
        calls["args"] = (query, source, aspect, per_page)
        return [_FakeResult()]

    monkeypatch.setattr(dl_services_mod, "search", fake_search)
    assert cli.main(["stock", "search", "cats"]) == 0
    assert calls["args"] == ("cats", "pexels", "16:9", 10)
    out = capsys.readouterr().out
    assert '"id": "1"' in out


def test_cmd_stock_search_writes_out_file(tmp_path, monkeypatch):
    class _FakeResult:
        def to_dict(self):
            return {"source": "pixabay", "id": "9", "url": "https://y/9.mp4"}

    monkeypatch.setattr(
        dl_services_mod, "search",
        lambda query, *, source, aspect, per_page: [_FakeResult()],
    )
    monkeypatch.chdir(tmp_path)
    assert cli.main(["stock", "search", "dogs", "--out", "results.json"]) == 0
    written = (tmp_path / "results.json").read_text(encoding="utf-8")
    assert '"id": "9"' in written


def test_cmd_stock_download_calls_service_with_right_args(tmp_path, monkeypatch):
    calls = {}

    def fake_download(manifest, out_dir):
        calls["args"] = (manifest, out_dir)
        return [{"id": "1"}, {"id": "2"}]

    monkeypatch.setattr(dl_services_mod, "download", fake_download)
    monkeypatch.chdir(tmp_path)
    assert cli.main(["stock", "download", "manifest.json", "--out", "outdir"]) == 0
    assert calls["args"] == ("manifest.json", "outdir")


def test_cmd_stock_search_env_key_error_surfaces_cleanly(tmp_path, monkeypatch):
    """Missing API key raises services.stock.StockConfigError -- the CLI's
    generic error boundary must surface it as a clean one-liner naming the
    env var, not a raw traceback."""
    monkeypatch.chdir(tmp_path)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    code = cli.main(["stock", "search", "cats"])
    assert code == 1
