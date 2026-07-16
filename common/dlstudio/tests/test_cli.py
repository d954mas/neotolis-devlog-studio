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
    code = cli.main(["check"])
    assert code == 1
    err = capsys.readouterr().err
    assert "edit module is required" in err
    assert "Traceback" not in err


def test_main_debug_reraises_cli_error(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
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
    timeline = make_timeline([beat], design=design)
    out_path = tmp_path / "out" / "b01.mp4"

    with pytest.raises(NotImplementedError):
        cli._compose_worker(
            beat, design, timeline, "draft", False, None,
            str(out_path), str(tmp_path / "cache"),
        )


def test_compose_worker_cache_miss_renders_and_populates_cache(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"

    def fake_render_beat(beat, design, timeline, opts):
        p = Path(opts.workdir) / f"{beat.id}_rendered.mp4"
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes(b"freshly-rendered")
        return p

    monkeypatch.setattr(dl_render_mod, "render_beat", fake_render_beat)

    beat = make_ir_beat()
    design = make_design()
    timeline = make_timeline([beat], design=design)
    out_path = tmp_path / "out" / "b01.mp4"

    msg = cli._compose_worker(
        beat, design, timeline, "draft", False, None, str(out_path), str(cache_dir)
    )
    assert "rendered" in msg
    assert out_path.read_bytes() == b"freshly-rendered"
    assert any(cache_dir.glob("*.mp4"))


def test_compose_worker_cache_hit_short_circuits_render(tmp_path, monkeypatch):
    cache_dir = tmp_path / "cache"
    monkeypatch.setattr(dl_cache, "CACHE_DIR", cache_dir)
    # If render_beat were called on a cache hit, this would blow up loudly
    # instead of silently succeeding -- proving the hit path truly skips it.
    monkeypatch.setattr(dl_render_mod, "render_beat", _raise_not_implemented)

    beat = make_ir_beat()
    design = make_design()
    timeline = make_timeline([beat], design=design)

    key = dl_cache.beat_key(beat, design, quality="draft", width=None, gpu=False)
    rendered = tmp_path / "prerendered.mp4"
    rendered.write_bytes(b"already-rendered")
    dl_cache.put(key, rendered)

    out_path = tmp_path / "out" / "b01.mp4"
    msg = cli._compose_worker(beat, design, timeline, "draft", False, None, str(out_path), None)
    assert "cache hit" in msg
    assert out_path.read_bytes() == b"already-rendered"


def test_render_targets_serial_calls_worker_per_beat(tmp_path, monkeypatch):
    calls = []

    def fake_worker(beat, design, timeline, quality, gpu, width_px, out_path,
                    cache_dir_override, beat_chunks=None):
        calls.append(beat.id)
        Path(out_path).parent.mkdir(parents=True, exist_ok=True)
        Path(out_path).write_bytes(b"rendered")
        return "ok"

    monkeypatch.setattr(cli, "_compose_worker", fake_worker)

    beats = [make_ir_beat("b01"), make_ir_beat("b02")]
    design = make_design()
    timeline = make_timeline(beats, design=design)
    beat_files = {b.id: tmp_path / f"{b.id}.mp4" for b in beats}

    cli._render_targets(
        beats, design, timeline,
        quality="draft", gpu=False, width_px=None,
        beat_files=beat_files, jobs=1,
    )

    assert calls == ["b01", "b02"]
    assert all(p.exists() for p in beat_files.values())


@pytest.mark.slow
def test_render_targets_parallel_real_subprocess_boundary(tmp_path):
    """-j 2 really spawns worker processes -- a monkeypatch in this
    process can't reach across that boundary, so this exercises whatever
    dlstudio.render.render_beat actually is right now (stub or real).
    Either way, these beats reference nonexistent audio/asset paths, so
    the real worker call is guaranteed to fail; the point of this test is
    that ProcessPoolExecutor + the lazy import correctly propagate that
    failure back to the parent via fut.result() instead of silently
    losing it or hanging."""
    beat_a, beat_b = make_ir_beat("b01"), make_ir_beat("b02")
    design = make_design()
    timeline = make_timeline([beat_a, beat_b], design=design)
    beat_files = {"b01": tmp_path / "b01.mp4", "b02": tmp_path / "b02.mp4"}

    old = os.environ.get("DLSTUDIO_CACHE_DIR")
    os.environ["DLSTUDIO_CACHE_DIR"] = str(tmp_path / "cache")
    try:
        with pytest.raises(Exception):
            cli._render_targets(
                [beat_a, beat_b], design, timeline,
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
    prerendered = tmp_path / "prerendered.mp4"
    prerendered.write_bytes(b"cached-beat-bytes")
    dl_cache.put(key, prerendered)
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


def test_cmd_iter_stale_skips_restore_when_file_already_present(tmp_path, monkeypatch):
    """If the beat file is already on disk, --stale must not needlessly
    re-copy from cache (dl_cache.get is only a fallback for the missing
    case)."""
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
    prerendered = tmp_path / "prerendered.mp4"
    prerendered.write_bytes(b"cached-beat-bytes")
    dl_cache.put(key, prerendered)

    out_dir = project_root / "data" / "finalize"
    out_dir.mkdir(parents=True, exist_ok=True)
    existing = out_dir / "b01.mp4"
    existing.write_bytes(b"already-on-disk")

    get_calls = []
    real_get = dl_cache.get

    def spy_get(k, p):
        get_calls.append((k, p))
        return real_get(k, p)

    monkeypatch.setattr(dl_cache, "get", spy_get)
    monkeypatch.setattr(dl_render_mod, "render_beat",
                        lambda *a, **k: (_ for _ in ()).throw(
                            AssertionError("render_beat must not run for a cache-hit beat")))
    monkeypatch.setattr(dl_render_mod, "assemble",
                        lambda _tl, _bf, _o: out_dir / "final.mp4")

    args = cli._build_parser().parse_args(["iter", dotted, "--stale"])
    code = cli.cmd_iter(args)

    assert code == 0
    assert get_calls == []                       # no restore needed
    assert existing.read_bytes() == b"already-on-disk"
