from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import pytest

from dlstudio.cli import CliError
from dlstudio.cli import delivery as cli_delivery


def _production(tmp_path: Path, *, kind: str = "reel") -> tuple[Path, str]:
    workspace = tmp_path / "workspace"
    product = workspace / "fixture_product"
    production_id = f"2026_07_18_{kind}_01"
    collection = "reels" if kind == "reel" else "devlogs"
    root = product / collection / production_id
    (root / "edit").mkdir(parents=True)
    for subdir in ("finalize", "publish", "review"):
        (root / "data" / subdir).mkdir(parents=True)
    (product / "delivery" / collection).mkdir(parents=True)
    (workspace / "devlog.toml").write_text("[v2]\n", encoding="utf-8")
    (product / "product.toml").write_text(
        'id = "fixture_product"\n'
        'title = "Fixture Product"\n'
        'game_root = "."\n\n'
        "[sources]\n",
        encoding="utf-8",
    )
    orientation = "vertical" if kind == "reel" else "landscape"
    (root / "production.toml").write_text(
        f'id = "{production_id}"\n'
        f'kind = "{kind}"\n'
        'date = "2026-07-18"\n'
        f'orientation = "{orientation}"\n'
        'edit_path = "edit"\n'
        'data_root = "data"\n'
        f'delivery_root = "../../delivery/{collection}/{production_id}"\n',
        encoding="utf-8",
    )
    (root / "edit" / "__init__.py").write_text(
        "from dlstudio.model import Edit\n"
        "from .beats import BEATS\n"
        "from .design import DESIGN\n"
        "EDIT = Edit(name='fixture', beats=BEATS, order=[], design=DESIGN, "
        "output='data/finalize/video.mp4')\n",
        encoding="utf-8",
    )
    (root / "edit" / "beats.py").write_text("BEATS = {}\n", encoding="utf-8")
    (root / "edit" / "design.py").write_text(
        "from dlstudio.model import Design, Fonts, Palette\n"
        "DESIGN = Design(resolution=(1080, 1920), "
        "palette=Palette(tokens={'bg': '#000000', 'text': '#ffffff'}), "
        "fonts=Fonts(main='data/fonts/main.ttf'))\n",
        encoding="utf-8",
    )
    return root, f"fixture_product:{production_id}"


def _write_inputs(root: Path, *, kind: str = "reel") -> None:
    (root / "data/finalize/video.mp4").write_bytes(b"video")
    (root / "data/publish/video.mp4").write_bytes(b"video")
    (root / "data/publish/metadata.md").write_text(
        "## Title\nA Reel\n\n"
        "## Description\nA description.\n\n"
        "## YouTube tags\ngame development, indie game\n\n"
        "## Hashtags\n#GameDev #IndieGame\n",
        encoding="utf-8",
    )
    image = "cover.png" if kind == "reel" else "thumbnail.png"
    (root / "data/publish" / image).write_bytes(b"image")
    video_path = (root / "data/publish/video.mp4").resolve()
    metadata_path = (root / "data/publish/metadata.md").resolve()
    image_path = (root / "data/publish" / image).resolve()
    (root / "data/publish/evidence.json").write_text(json.dumps({
        "version": 1,
        "product_id": "fixture_product",
        "production_id": root.name,
        "video": {
            "publish_path": str(video_path),
            "sha256": hashlib.sha256(video_path.read_bytes()).hexdigest(),
        },
        "metadata": {
            "path": str(metadata_path),
            "sha256": hashlib.sha256(metadata_path.read_bytes()).hexdigest(),
        },
        "image": {
            "path": str(image_path),
            "sha256": hashlib.sha256(image_path.read_bytes()).hexdigest(),
        },
    }), encoding="utf-8")


def test_deliver_uses_production_scoped_defaults_and_records_telemetry(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root, edit_ref = _production(tmp_path)
    _write_inputs(root)
    monkeypatch.chdir(root)
    args = argparse.Namespace(
        edit=edit_ref,
        video=None,
        metadata=None,
        image=None,
        overwrite=False,
    )

    assert cli_delivery.cmd_deliver(args) == 0

    destination = root.parents[1] / "delivery/reels/2026_07_18_reel_01"
    assert (destination / "video.mp4").read_bytes() == b"video"
    assert (destination / "metadata.md").is_file()
    assert (destination / "cover.png").read_bytes() == b"image"
    lines = (root / "data/review/telemetry.jsonl").read_text(
        encoding="utf-8"
    ).splitlines()
    event = json.loads(lines[-1])
    assert event["stage"] == "delivery"
    assert event["agent_role"] == "packager"
    assert event["product_id"] == "fixture_product"
    assert event["production_id"] == "2026_07_18_reel_01"
    assert event["artifact_paths"] == [
        "delivery/reels/2026_07_18_reel_01/video.mp4",
        "delivery/reels/2026_07_18_reel_01/metadata.md",
        "delivery/reels/2026_07_18_reel_01/cover.png",
        "delivery/reels/2026_07_18_reel_01/delivery_manifest.json",
    ]


def test_deliver_rejects_publish_artifact_mutated_after_evidence(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root, edit_ref = _production(tmp_path)
    _write_inputs(root)
    (root / "data/publish/video.mp4").write_bytes(b"mutated")
    monkeypatch.chdir(root)
    args = argparse.Namespace(
        edit=edit_ref,
        video=None,
        metadata=None,
        image=None,
        overwrite=False,
    )

    with pytest.raises(CliError, match="video SHA-256 is stale"):
        cli_delivery.cmd_deliver(args)


def test_deliver_explicit_paths_must_stay_inside_production(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    root, edit_ref = _production(tmp_path)
    _write_inputs(root)
    outside = tmp_path / "outside.mp4"
    outside.write_bytes(b"outside")
    monkeypatch.chdir(root)
    args = argparse.Namespace(
        edit=edit_ref,
        video=str(outside),
        metadata=None,
        image=None,
        overwrite=False,
    )

    with pytest.raises(CliError, match="inside production data"):
        cli_delivery.cmd_deliver(args)


def test_deliver_parser_exposes_optional_scoped_artifact_flags():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest="command", required=True)
    cli_delivery.add_subparser(sub)

    args = parser.parse_args(
        [
            "deliver",
            "fixture_product:2026_07_18_reel_01",
            "--video",
            "data/finalize/custom.mp4",
            "--metadata",
            "data/publish/custom.md",
            "--image",
            "data/publish/custom.png",
            "--overwrite",
        ]
    )

    assert args.func is cli_delivery.cmd_deliver
    assert args.video == "data/finalize/custom.mp4"
    assert args.metadata == "data/publish/custom.md"
    assert args.image == "data/publish/custom.png"
    assert args.overwrite is True
