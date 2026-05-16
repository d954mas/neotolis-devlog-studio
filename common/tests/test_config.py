from pathlib import Path
import argparse

from devlog.config import find_config_path, load_config
from devlog import cli


def test_load_config_searches_upward(tmp_path: Path):
    cfg = tmp_path / "devlog.toml"
    cfg.write_text(
        'default_edit = "demo.edits.youtube"\n'
        '[defaults]\nwidth = "540p"\nquality = "draft"\nparallel = 5\n',
        encoding="utf-8",
    )
    nested = tmp_path / "demo/edits/youtube"
    nested.mkdir(parents=True)
    assert find_config_path(nested) == cfg
    loaded = load_config(nested)
    assert loaded.default_edit == "demo.edits.youtube"
    assert loaded.defaults["parallel"] == 5


def test_render_defaults_fill_from_config(tmp_path: Path):
    (tmp_path / "devlog.toml").write_text(
        'default_edit = "demo.edits.youtube"\n'
        '[defaults]\nwidth = "540p"\nquality = "draft"\nparallel = 6\n'
        '[final]\nwidth = "4k"\nquality = "upload"\nparallel = 4\ngpu = true\n',
        encoding="utf-8",
    )
    cfg = load_config(tmp_path)
    args = argparse.Namespace(width=None, quality=None, draft=False, parallel=None, final=False, gpu=False)
    cli._apply_render_defaults(args, cfg)
    assert args.width == "540p"
    assert args.quality == "draft"
    assert args.parallel == 6

    final_args = argparse.Namespace(width=None, quality=None, draft=False, parallel=None, final=True, gpu=False)
    cli._apply_render_defaults(final_args, cfg)
    assert final_args.width == "4k"
    assert final_args.quality == "upload"
    assert final_args.parallel == 4
    assert final_args.gpu is True
