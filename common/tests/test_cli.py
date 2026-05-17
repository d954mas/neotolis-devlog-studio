import argparse
from pathlib import Path

import pytest

from devlog import cli
from devlog.types import Beat, Chunk, Design, Edit, Fonts, Palette


def test_render_suffix_supports_quality_presets():
    assert cli._render_suffix(argparse.Namespace(width=None, draft=False, quality=None)) == "_video_1080p"
    assert cli._render_suffix(argparse.Namespace(width="540p", draft=False, quality="preview")) == "_960w_preview"
    assert cli._render_suffix(argparse.Namespace(width=None, draft=False, quality="upload")) == "_upload"
    assert cli._render_suffix(argparse.Namespace(width=None, draft=False, quality="draft")) == "_draft"


def test_draft_flag_conflicts_with_non_draft_quality():
    with pytest.raises(SystemExit):
        cli._render_suffix(argparse.Namespace(width=None, draft=True, quality="preview"))


def test_beats_suffix_uses_existing_render_suffix_logic():
    args = argparse.Namespace(width="1080p", draft=False, quality="upload")
    assert cli._render_suffix(args) == "_1920w_upload"


def test_resolve_edit_requires_default_when_missing():
    with pytest.raises(SystemExit):
        cli._resolve_edit(None, cli.DevlogConfig())


def test_resolve_edit_prefers_explicit_value():
    cfg = cli.DevlogConfig(default_edit="demo.edits.youtube")
    assert cli._resolve_edit("other.edits.youtube", cfg) == "other.edits.youtube"
    assert cli._resolve_edit(None, cfg) == "demo.edits.youtube"


def test_iter_shortcut_defaults_to_fast_draft_render():
    args = cli.build_parser().parse_args(["iter", "--beat", "intro"])

    cli._apply_iter_shortcut_defaults(args)

    assert args.width == "540p"
    assert args.quality == "draft"
    assert args.beat == "intro"
    assert args.no_review is True
    assert args.final is False


def test_iter_shortcut_accepts_stale_flag():
    args = cli.build_parser().parse_args(["iter", "--stale"])

    cli._apply_iter_shortcut_defaults(args)

    assert args.stale is True
    assert args.width == "540p"
    assert args.quality == "draft"


def test_final_shortcut_enables_final_preflight():
    args = cli.build_parser().parse_args(["final"])

    cli._apply_final_shortcut_defaults(args)

    assert args.final is True
    assert args.draft is False
    assert args.skip_final_preflight is False


def test_new_scaffold_creates_importable_project_shape(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    agents = tmp_path / "trolley/.claude/agents"
    agents.mkdir(parents=True)
    (agents / "vo-reviewer.md").write_text("vo", encoding="utf-8")
    (agents / "video-reviewer.md").write_text("video", encoding="utf-8")
    cli.cmd_new(argparse.Namespace(project="sampledevlog", edit="youtube", force=False))
    root = tmp_path / "sampledevlog"
    assert (root / "shared/palette.py").exists()
    assert (root / "edits/youtube/beats.py").exists()
    assert (root / "edits/youtube/design.py").exists()
    assert (root / "edits/youtube/__init__.py").exists()
    assert (root / ".claude/agents/vo-reviewer.md").read_text(encoding="utf-8") == "vo"


def test_new_video_imports_script_into_scaffold(tmp_path: Path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    script = tmp_path / "script.md"
    script.write_text("# Hook\nHello world.\n\n# Proof\nSecond beat.", encoding="utf-8")

    cli.cmd_new_video(argparse.Namespace(
        project="samplevideo",
        edit="youtube",
        script=str(script),
        force=False,
        prefix="b",
        output="data/finalize/iter01.mp4",
        max_chunk_words=18,
    ))

    beats_py = tmp_path / "samplevideo/edits/youtube/beats.py"
    text = beats_py.read_text(encoding="utf-8")
    assert "'hook': Beat(" in text
    assert "'proof': Beat(" in text
    assert 'Replace this with your recorded voiceover text.' not in text


def test_final_preflight_blocks_missing_assets(tmp_path: Path):
    pal = Palette(bg=(0, 0, 0), gold=(1, 1, 1), gold_dim=(2, 2, 2), red=(3, 3, 3))
    fonts = Fonts(display=str(tmp_path / "display.ttf"), text=str(tmp_path / "text.ttf"))
    (tmp_path / "display.ttf").write_bytes(b"font")
    (tmp_path / "text.ttf").write_bytes(b"font")
    (tmp_path / "data/finalize").mkdir(parents=True)
    (tmp_path / "data/finalize/a_words.json").write_text(
        '{"words":[{"word":"one","start":0,"end":0.5}]}',
        encoding="utf-8",
    )
    edit = Edit(
        name="youtube",
        design=Design(resolution=(1920, 1080), fps=30, palette=pal, fonts=fonts),
        output="data/finalize/out.mp4",
        order=["a"],
        beats={
            "a": Beat(
                audio="data/finalize/missing.wav",
                words="data/finalize/a_words.json",
                chunks=[Chunk(words=(0, 0), kind="image", src="data/missing.png")],
            )
        },
    )
    with pytest.raises(SystemExit):
        cli._run_final_preflight(edit, tmp_path, 3840)
