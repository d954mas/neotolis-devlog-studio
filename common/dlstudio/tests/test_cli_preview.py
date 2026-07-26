"""`dl2 preview` — the one-command draft path (cli/preview.py wiring)."""
from __future__ import annotations

import json
from pathlib import Path

def test_parse_preview_defaults():
    from dlstudio import cli

    args = cli._build_parser().parse_args(["preview", "some.edit"])
    assert args.func is not None
    assert args.width is None and args.quality is None
    assert args.jobs == 1 and args.keyframes == 8


def test_cmd_preview_runs_stale_draft_then_review_artifacts(tmp_path, monkeypatch):
    """preview = check+iter --stale draft (via _iterate_render) then contact
    sheet + keyframes over the assembled output."""
    import dlstudio.services as services_mod
    from dlstudio import cli
    from dlstudio.cli import preview as preview_mod

    calls: dict = {}

    def fake_iterate_render(edit, timeline, *, width_spec, quality, gpu,
                            no_cache, stale, jobs):
        calls["iterate"] = {"width": width_spec, "quality": quality,
                            "stale": stale, "no_cache": no_cache, "jobs": jobs}
        out = Path(timeline.output)
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_bytes(b"assembled")
        return 0

    def fake_sheet(video, out_jpg, **kw):
        calls["sheet"] = (Path(video), Path(out_jpg))
        Path(out_jpg).parent.mkdir(parents=True, exist_ok=True)
        Path(out_jpg).write_bytes(b"jpg")
        return Path(out_jpg)

    def fake_frames(video, out_dir, *, count, **kw):
        calls["frames"] = (Path(video), Path(out_dir), count)
        Path(out_dir).mkdir(parents=True, exist_ok=True)
        p = Path(out_dir) / "kf_01.jpg"
        p.write_bytes(b"jpg")
        return [p]

    import textwrap
    import uuid

    pkg = f"proj_preview_{uuid.uuid4().hex[:8]}"
    proj = tmp_path / pkg
    (proj / "edits" / "main").mkdir(parents=True)
    (proj / "__init__.py").write_text("", encoding="utf-8")
    (proj / "edits" / "__init__.py").write_text("", encoding="utf-8")
    (proj / "edits" / "main" / "__init__.py").write_text(textwrap.dedent(
        """
        from dlstudio.model import Design, Edit, Fonts, Palette

        EDIT = Edit(
            name="preview-fake",
            design=Design(
                resolution=(1920, 1080),
                palette=Palette(tokens={"bg": "#000000", "text": "#ffffff"}),
                fonts=Fonts(main="main.ttf"),
            ),
            beats={}, order=[], output="data/finalize/output.mp4",
        )
        """), encoding="utf-8")
    (tmp_path / "devlog.toml").write_text("", encoding="utf-8")
    monkeypatch.syspath_prepend(str(tmp_path))
    monkeypatch.chdir(tmp_path)

    from conftest import make_ir_beat, make_timeline
    timeline = make_timeline([make_ir_beat("b01")])
    import dlstudio.compile as dl_compile_mod
    monkeypatch.setattr(dl_compile_mod, "build_timeline", lambda edit: timeline)
    monkeypatch.setattr(cli, "_iterate_render", fake_iterate_render)
    monkeypatch.setattr(services_mod, "make_contact_sheet", fake_sheet)
    monkeypatch.setattr(services_mod, "extract_keyframes", fake_frames)

    args = cli._build_parser().parse_args(["preview", f"{pkg}.edits.main"])
    code = preview_mod.cmd_preview(args)

    assert code == 0
    assert calls["iterate"] == {"width": "540p", "quality": "draft",
                                "stale": True, "no_cache": False, "jobs": 1}
    assert calls["sheet"][0] == Path(timeline.output)
    assert calls["sheet"][1] == Path("data/review/contact_sheet.jpg")
    assert calls["frames"][1] == Path("data/review/keyframes")
    assert calls["frames"][2] == 8
    assert Path("data/review/geometry_report.json").exists()
    assert Path("data/review/boundary_report.json").exists()
    geometry = json.loads(
        Path("data/review/geometry_report.json").read_text(encoding="utf-8")
    )
    assert geometry["output_resolution"] == [960, 540]
