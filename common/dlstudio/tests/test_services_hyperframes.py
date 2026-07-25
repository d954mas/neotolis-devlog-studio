"""Tests for dlstudio.services.hyperframes -- the `npx hyperframes` bridge.

`subprocess.run` and `shutil.which` are monkeypatched on the module under
test, so no test here ever needs node/npx installed or spawns a real
process: render tests assert on the argv/env/kwargs the bridge would have
handed to subprocess (mocking style of test_services_stock.py /
test_services_tts.py). `init_project` is pure filesystem work and runs for
real against tmp_path.
"""
from __future__ import annotations

import hashlib
import json
import re
import subprocess
from pathlib import Path

import pytest

from dlstudio.services import hyperframes as hf
from dlstudio.services import visual_block_evidence as vbe

FAKE_NPX = "C:/fake/node/npx.cmd"


def _sha256(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _completed(rc: int = 0, stdout: str = "", stderr: str = ""):
    return subprocess.CompletedProcess(args=[], returncode=rc, stdout=stdout, stderr=stderr)


def _production(tmp_path: Path) -> Path:
    production_id = "2026_07_25_devlog_01"
    (tmp_path / "product.toml").write_text(
        "\n".join([
            'id = "test_game"',
            'title = "TEST GAME"',
            "version = 1",
            'game_root = "game-root"',
            "",
            "[sources]",
            'steam = "https://store.steampowered.com/app/123/Test_Game/"',
            "",
            "[paths]",
            'devlogs = "devlogs"',
            'reels = "reels"',
            'shared = "shared"',
            'delivery = "delivery"',
        ]),
        encoding="utf-8",
    )
    production = tmp_path / "devlogs" / production_id
    edit = production / "edit"
    edit.mkdir(parents=True)
    (edit / "__init__.py").write_text("", encoding="utf-8")
    (production / "production.toml").write_text(
        "\n".join([
            f'id = "{production_id}"',
            'kind = "devlog"',
            'date = "2026-07-25"',
            'orientation = "landscape"',
            "version = 1",
            'edit_path = "edit"',
            'data_root = "data"',
            f'delivery_root = "../../delivery/devlogs/{production_id}"',
        ]),
        encoding="utf-8",
    )
    return production


def _mock_toolchain(monkeypatch, captured: dict, *, rc: int = 0, stderr: str = ""):
    """Fake both `shutil.which` (npx present) and `subprocess.run` (records
    argv + kwargs, returns a canned CompletedProcess)."""
    monkeypatch.setattr(hf.shutil, "which", lambda name: FAKE_NPX)

    def fake_run(cmd, **kwargs):
        captured["cmd"] = cmd
        captured["kwargs"] = kwargs
        return _completed(rc=rc, stderr=stderr)

    monkeypatch.setattr(hf.subprocess, "run", fake_run)


def _approved_source(video: Path) -> tuple[Path, str, Path, object]:
    from dlstudio.services.asset_registry import (
        _register_ingested_captures,
        approve_asset,
        load_asset_registry,
    )

    source = video / "data" / "footage" / "source.mp4"
    source.parent.mkdir(parents=True)
    source.write_bytes(b"registered-source")
    source_hash = _sha256(source)
    metadata = source.with_suffix(".mp4.capture.json")
    metadata.write_bytes(b"metadata")
    game_report = source.with_suffix(".mp4.game.json")
    game_report.write_bytes(b"game-report")
    batch = video / "data" / "plan" / "capture_batch.json"
    batch.parent.mkdir(parents=True)
    batch.write_bytes(b"batch")
    results = video / "data" / "plan" / "capture_results.json"
    results.write_bytes(b"results")
    facts = {
        "request_id": "day4_visual",
        "artifact_path": "data/footage/source.mp4",
        "artifact_sha256": source_hash,
        "metadata_path": "data/footage/source.mp4.capture.json",
        "metadata_sha256": _sha256(metadata),
        "game_report_path": "data/footage/source.mp4.game.json",
        "game_report_sha256": _sha256(game_report),
        "capture_batch_path": "data/plan/capture_batch.json",
        "capture_batch_sha256": _sha256(batch),
        "capture_results_path": "data/plan/capture_results.json",
        "capture_results_sha256": _sha256(results),
        "editorial_role": "gameplay",
        "capture_method": "realtime_window",
        "state_id": "day4.paper",
        "build_id": "exe-sha256:" + "a" * 64,
        "action_id": "paper_visual_pass",
        "seed": 42,
        "parameters": {},
        "initial_semantic_hash": "00000001",
        "action_semantic_hash": "00000002",
        "actual_width": 1920,
        "actual_height": 1080,
        "actual_fps": 30,
        "actual_duration": 15,
        "simulation_rate": 1.0,
        "continuous": True,
        "clean_ui": True,
        "client_area": True,
        "cursor_visible": False,
        "content_seconds": 5,
        "head_handle_seconds": 5,
        "tail_handle_seconds": 5,
        "frame_audit_passed": True,
        "game_elapsed_seconds": 15,
        "measured_playback_rate": 1.0,
        "presentation": {"fit": "contain", "scale": 1.0},
    }
    registry = _register_ingested_captures(video, [facts])
    current = registry.assets[0]
    asset_id = "capture:day4_visual"
    approve_asset(
        video,
        asset_id,
        expected_sha256=source_hash,
        expected_revision=current.revision,
        expected_validation_sha256=current.validation_sha256,
        approved_by="test",
    )
    catalog = video / "data" / "assets" / "catalog.json"
    catalog.write_text(json.dumps({"assets": [{
        "path": "data/footage/source.mp4",
        "sha256": source_hash,
        "source_role": "real_product",
    }]}), encoding="utf-8")
    geometry = video / "data" / "review" / "geometry_report.json"
    geometry.parent.mkdir(parents=True)
    geometry.write_text(json.dumps({
        "schema_version": 1,
        "output_resolution": [1920, 1080],
        "segments": [{
            "beat_id": "day4",
            "segment_index": 0,
            "src": "data/footage/source.mp4",
            "asset_id": asset_id,
            "resolved": True,
            "geometry": {
                "fit": "cover",
                "anchor_x": 0.5,
                "anchor_y": 0.5,
                "source_width": 1920,
                "source_height": 1080,
                "scaled_width": 1920,
                "scaled_height": 1080,
                "output_width": 1920,
                "output_height": 1080,
                "crop_x": 0,
                "crop_y": 0,
                "crop_width": 1920,
                "crop_height": 1080,
                "pad_x": None,
                "pad_y": None,
            },
        }],
    }), encoding="utf-8")
    record = load_asset_registry(video).assets[0]
    return source, asset_id, geometry, record


# ─── init_project ───────────────────────────────────────────────────────

def test_init_project_scaffolds_expected_files(tmp_path):
    root = hf.init_project(tmp_path / "bar_demo")
    assert root == tmp_path / "bar_demo"
    assert (root / "index.html").is_file()
    assert (root / "meta.json").is_file()
    assert (root / "compositions").is_dir()
    assert (root / "assets").is_dir()

    meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))
    assert meta["name"] == "bar_demo"
    assert meta["id"] == "bar_demo"
    assert meta["createdBy"] == "dl2 gen-html --init"


def test_init_project_starter_registers_paused_window_timelines(tmp_path):
    root = hf.init_project(tmp_path / "tl_demo")
    html = (root / "index.html").read_text(encoding="utf-8")
    # the deterministic-seek contract: a paused timeline registered under
    # the composition root's data-composition-id
    assert "gsap.timeline({ paused: true })" in html
    assert 'window.__timelines["root"] = tl;' in html
    assert 'data-composition-id="root"' in html


@pytest.mark.parametrize(
    "template",
    ("day-card", "before-after", "focus-callout", "cta-endcard", "explain-steps"),
)
def test_init_project_scaffolds_reusable_visual_blocks(tmp_path, template):
    root = hf.init_project(tmp_path / template, template=template)
    html = (root / "index.html").read_text(encoding="utf-8")
    meta = json.loads((root / "meta.json").read_text(encoding="utf-8"))

    assert "data-composition-variables=" in html
    assert 'data-duration="' in html
    assert 'data-width="1920"' in html
    assert 'data-height="1080"' in html
    assert "gsap.timeline({ paused: true })" in html
    assert 'window.__timelines["root"] = tl;' in html
    assert "Math.random" not in html
    assert "setTimeout" not in html
    assert meta["template"] == template
    assert meta["orientation"] == "landscape"
    assert meta["purpose"]


def test_visual_block_variable_declaration_is_raw_valid_json(tmp_path):
    root = hf.init_project(tmp_path / "day", template="day-card")
    html = (root / "index.html").read_text(encoding="utf-8")
    match = re.search(r"data-composition-variables='([^']+)'", html)
    assert match is not None
    declarations = json.loads(match.group(1))
    assert declarations[0]["id"] == "day"
    assert declarations[0]["default"] == "ДЕНЬ 1"


def test_init_project_visual_block_supports_vertical_orientation(tmp_path):
    root = hf.init_project(
        tmp_path / "vertical_day",
        template="day-card",
        orientation="vertical",
    )
    html = (root / "index.html").read_text(encoding="utf-8")
    assert 'data-width="1080"' in html
    assert 'data-height="1920"' in html


def test_init_project_rejects_vertical_legacy_starter_without_writing(tmp_path):
    target = tmp_path / "legacy_vertical"
    with pytest.raises(ValueError, match="applies to a visual-block template"):
        hf.init_project(target, orientation="vertical")
    assert not target.exists()


def test_init_project_rejects_unknown_visual_block_before_writing_files(tmp_path):
    target = tmp_path / "bad"
    with pytest.raises(ValueError, match="unknown visual-block template"):
        hf.init_project(target, template="glossy-dashboard")
    assert not target.exists()


def test_shared_cta_template_has_no_project_specific_release_claims(tmp_path):
    root = hf.init_project(tmp_path / "cta", template="cta-endcard")
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "NOT A TROLLEY PROBLEM" not in html
    assert "4654990" not in html
    assert "СТРАНИЦА УЖЕ В STEAM" not in html
    assert "YOUR GAME" in html


@pytest.mark.parametrize(
    ("template", "forbidden"),
    [
        ("day-card", "Бумага + графит"),
        ("before-after", "Слой бумаги и графит"),
        ("focus-callout", "БУМАЖНЫЙ СЛОЙ"),
        ("cta-endcard", "NOT A TROLLEY PROBLEM"),
        ("explain-steps", "Бумажный слой"),
    ],
)
def test_shared_templates_have_neutral_preview_defaults(tmp_path, template, forbidden):
    root = hf.init_project(tmp_path / template, template=template)
    html = (root / "index.html").read_text(encoding="utf-8")
    assert forbidden not in html


def test_init_project_title_is_escaped_into_index(tmp_path):
    root = hf.init_project(tmp_path / "titled", title="A<B & C")
    html = (root / "index.html").read_text(encoding="utf-8")
    assert "A&lt;B &amp; C" in html


def test_init_project_refuses_non_empty_dir(tmp_path):
    target = tmp_path / "existing"
    target.mkdir()
    (target / "keep.txt").write_text("x", encoding="utf-8")
    with pytest.raises(FileExistsError, match="not empty"):
        hf.init_project(target)
    assert (target / "keep.txt").exists()  # untouched


def test_init_project_force_overwrites_starter_files(tmp_path):
    target = tmp_path / "existing"
    hf.init_project(target)
    root = hf.init_project(target, force=True, title="SECOND RUN")
    assert "SECOND RUN" in (root / "index.html").read_text(encoding="utf-8")


# ─── render_html: argv / env / kwargs ───────────────────────────────────

def test_render_html_builds_expected_npx_argv(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "bars")
    out = tmp_path / "infographics" / "bars.mp4"

    result = hf.render_html(project, out)

    assert result == out.resolve()
    cmd = captured["cmd"]
    assert cmd[0] == FAKE_NPX
    assert cmd[1:4] == ["-y", "hyperframes", "render"]
    assert cmd[4] == str(project.resolve())
    assert cmd[cmd.index("--output") + 1] == str(out.resolve())
    assert cmd[cmd.index("--quality") + 1] == "draft"
    assert captured["kwargs"]["cwd"] == project.resolve()


def test_render_html_out_dir_is_auto_created(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "bars")
    out = tmp_path / "deep" / "nested" / "bars.mp4"
    assert not out.parent.exists()
    hf.render_html(project, out)
    assert out.parent.is_dir()


def test_render_html_quality_final_maps_to_high(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "bars")
    hf.render_html(project, tmp_path / "out.mp4", quality="final")
    cmd = captured["cmd"]
    assert cmd[cmd.index("--quality") + 1] == "high"


def test_render_html_passes_existing_variables_file(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "steps", template="explain-steps")
    values = tmp_path / "steps.json"
    values.write_text(json.dumps({
        "title": "HOW IT WORKS",
        "step_1": "ONE",
        "step_2": "TWO",
        "step_3": "THREE",
        "step_4": "FOUR",
    }, ensure_ascii=False), encoding="utf-8")

    hf.render_html(project, tmp_path / "out.mp4", variables_file=values)

    cmd = captured["cmd"]
    assert cmd[cmd.index("--variables-file") + 1] == str(values.resolve())
    assert "--strict-variables" in cmd


def test_successful_render_writes_hash_bound_manifest(tmp_path, monkeypatch):
    monkeypatch.setattr(hf.shutil, "which", lambda name: FAKE_NPX)

    def fake_run(cmd, **kwargs):
        output = Path(cmd[cmd.index("--output") + 1])
        output.write_bytes(b"rendered-mp4")
        return _completed()

    monkeypatch.setattr(hf.subprocess, "run", fake_run)
    project = hf.init_project(tmp_path / "steps", template="explain-steps")
    values = tmp_path / "steps.json"
    values.write_text(json.dumps({
        "title": "HOW IT WORKS",
        "step_1": "ONE",
        "step_2": "TWO",
        "step_3": "THREE",
        "step_4": "FOUR",
    }), encoding="utf-8")
    out = tmp_path / "out.mp4"

    hf.render_html(project, out, quality="draft", variables_file=values)

    manifest = json.loads(
        (tmp_path / "out.mp4.render.json").read_text(encoding="utf-8")
    )
    assert manifest["schema"] == "devlog.hyperframes_render/v2"
    assert manifest["template"] == "explain-steps"
    assert manifest["artifact"]["path"] == "out.mp4"
    assert manifest["artifact"]["sha256"] == _sha256(out)
    assert manifest["project"]["path"] == "steps"
    assert manifest["project"]["entry_sha256"] == _sha256(project / "index.html")
    assert manifest["variables"]["sha256"] == _sha256(values)

    hf.validate_hyperframes_render_manifest(
        out,
        tmp_path / "out.mp4.render.json",
        tmp_path,
    )

    with pytest.raises(RuntimeError, match="quality=final"):
        hf.validate_hyperframes_render_manifest(
            out,
            tmp_path / "out.mp4.render.json",
            tmp_path,
            require_final=True,
        )


def test_legacy_devlog_root_keeps_manifest_paths_project_relative(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(hf.shutil, "which", lambda name: FAKE_NPX)

    def fake_run(cmd, **kwargs):
        Path(cmd[cmd.index("--output") + 1]).write_bytes(b"rendered-mp4")
        return _completed()

    monkeypatch.setattr(hf.subprocess, "run", fake_run)
    (tmp_path / "devlog.toml").write_text("[v2]\n", encoding="utf-8")
    project = hf.init_project(
        tmp_path / "data" / "hyperframes" / "steps",
        template="explain-steps",
    )
    values = tmp_path / "data" / "hyperframes" / "steps.json"
    values.write_text(json.dumps({
        "title": "HOW IT WORKS",
        "step_1": "ONE",
        "step_2": "TWO",
        "step_3": "THREE",
        "step_4": "FOUR",
    }), encoding="utf-8")
    out = tmp_path / "data" / "infographics" / "steps.mp4"

    hf.render_html(project, out, quality="final", variables_file=values)

    manifest_path = out.with_suffix(".mp4.render.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifact"]["path"] == "data/infographics/steps.mp4"
    assert manifest["project"]["path"] == "data/hyperframes/steps"
    hf.validate_hyperframes_render_manifest(
        out,
        manifest_path,
        tmp_path,
        require_final=True,
    )


def test_new_video_layout_infers_root_without_manifest_files(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setattr(hf.shutil, "which", lambda name: FAKE_NPX)

    def fake_run(cmd, **kwargs):
        Path(cmd[cmd.index("--output") + 1]).write_bytes(b"rendered-mp4")
        return _completed()

    monkeypatch.setattr(hf.subprocess, "run", fake_run)
    project = hf.init_project(
        tmp_path / "data" / "hyperframes" / "card",
    )
    out = tmp_path / "data" / "infographics" / "card.mp4"

    hf.render_html(project, out, quality="final")

    manifest_path = out.with_suffix(".mp4.render.json")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["artifact"]["path"] == "data/infographics/card.mp4"
    assert manifest["project"]["path"] == "data/hyperframes/card"
    hf.validate_hyperframes_render_manifest(
        out,
        manifest_path,
        tmp_path,
        require_final=True,
    )


def test_render_manifest_revalidation_rejects_tampered_artifact(tmp_path, monkeypatch):
    monkeypatch.setattr(hf.shutil, "which", lambda name: FAKE_NPX)

    def fake_run(cmd, **kwargs):
        Path(cmd[cmd.index("--output") + 1]).write_bytes(b"rendered-mp4")
        return _completed()

    monkeypatch.setattr(hf.subprocess, "run", fake_run)
    project = hf.init_project(tmp_path / "steps", template="explain-steps")
    values = tmp_path / "steps.json"
    values.write_text(json.dumps({
        "title": "HOW IT WORKS",
        "step_1": "ONE",
        "step_2": "TWO",
        "step_3": "THREE",
        "step_4": "FOUR",
    }), encoding="utf-8")
    out = tmp_path / "out.mp4"
    hf.render_html(project, out, variables_file=values)
    out.write_bytes(b"tampered")

    with pytest.raises(RuntimeError, match="artifact file is missing or stale"):
        hf.validate_hyperframes_render_manifest(
            out,
            tmp_path / "out.mp4.render.json",
            tmp_path,
        )


def test_render_visual_block_requires_release_values_before_npx(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "cta", template="cta-endcard")

    with pytest.raises(RuntimeError, match="requires --variables-file"):
        hf.render_html(project, tmp_path / "out.mp4")
    assert "cmd" not in captured


def test_render_visual_block_rejects_missing_required_values(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "cta", template="cta-endcard")
    values = tmp_path / "cta.json"
    values.write_text('{"cta":"wishlist"}', encoding="utf-8")

    with pytest.raises(RuntimeError, match="missing required variables"):
        hf.render_html(project, tmp_path / "out.mp4", variables_file=values)
    assert "cmd" not in captured


def test_render_visual_block_rejects_bad_cta_semantics(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "cta", template="cta-endcard")
    background = project / "assets" / "game.png"
    background.write_bytes(b"game")
    values = tmp_path / "cta.json"
    values.write_text(json.dumps({
        "game_title": "TEST GAME",
        "eyebrow": "Следующая остановка — Steam",
        "cta": "Следить за игрой",
        "steam_url": "https://example.test/",
        "episode": "DEVLOG 1",
        "background_image": "assets/game.png",
    }, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(RuntimeError, match="future stop"):
        hf.render_html(project, tmp_path / "out.mp4", variables_file=values)
    assert "cmd" not in captured


def test_render_visual_block_rejects_internal_label_in_release_variables(
    tmp_path,
    monkeypatch,
):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "steps", template="explain-steps")
    values = tmp_path / "steps.json"
    values.write_text(json.dumps({
        "title": "VERSION 12",
        "step_1": "ONE",
        "step_2": "TWO",
        "step_3": "THREE",
        "step_4": "FOUR",
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="internal production label"):
        hf.render_html(project, tmp_path / "out.mp4", variables_file=values)
    assert "cmd" not in captured


def test_render_focus_requires_explicit_coordinates(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "focus", template="focus-callout")
    image = project / "assets" / "game.png"
    image.write_bytes(b"game")
    values = tmp_path / "focus.json"
    values.write_text(json.dumps({
        "image": "assets/game.png",
        "label": "Look",
        "explanation": "Here",
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match=r"focus_x.*focus_y"):
        hf.render_html(project, tmp_path / "out.mp4", variables_file=values)
    assert "cmd" not in captured


def test_render_cta_rejects_future_stop_in_any_public_copy(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "cta", template="cta-endcard")
    background = project / "assets" / "game.png"
    background.write_bytes(b"game")
    values = tmp_path / "cta.json"
    values.write_text(json.dumps({
        "game_title": "TEST GAME",
        "eyebrow": "PAGE IS LIVE",
        "cta": "Следующая остановка — Steam. Добавь в вишлист",
        "steam_url": "https://store.steampowered.com/app/123/Test_Game/",
        "episode": "DEVLOG 1",
        "background_image": "assets/game.png",
    }, ensure_ascii=False), encoding="utf-8")

    with pytest.raises(RuntimeError, match="future stop"):
        hf.render_html(project, tmp_path / "out.mp4", variables_file=values)
    assert "cmd" not in captured


def test_render_cta_rejects_steam_substring_on_foreign_host(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "cta", template="cta-endcard")
    background = project / "assets" / "game.png"
    background.write_bytes(b"game")
    values = tmp_path / "cta.json"
    values.write_text(json.dumps({
        "game_title": "TEST GAME",
        "eyebrow": "PAGE IS LIVE",
        "cta": "ADD TO WISHLIST",
        "steam_url": "https://evil.test/?next=store.steampowered.com/app/123",
        "episode": "DEVLOG 1",
        "background_image": "assets/game.png",
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="canonical Steam app URL"):
        hf.render_html(project, tmp_path / "out.mp4", variables_file=values)
    assert "cmd" not in captured


def test_render_cta_requires_canonical_product_title_and_steam_url(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    production = _production(tmp_path)
    project = hf.init_project(
        production / "data" / "hyperframes" / "cta",
        template="cta-endcard",
    )
    background = project / "assets" / "game.png"
    background.write_bytes(b"game")
    values = production / "data" / "cta.json"
    values.write_text(json.dumps({
        "game_title": "WRONG GAME",
        "eyebrow": "PAGE IS LIVE",
        "cta": "ADD TO WISHLIST",
        "steam_url": "https://store.steampowered.com/app/123/Test_Game/",
        "episode": "DEVLOG 1",
        "background_image": "assets/game.png",
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="canonical product.toml title"):
        hf.render_html(
            project,
            production / "data" / "infographics" / "cta.mp4",
            variables_file=values,
            production_root=production,
        )
    assert "cmd" not in captured


def test_render_before_after_requires_existing_distinct_project_assets(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "compare", template="before-after")
    image = project / "assets" / "same.png"
    image.write_bytes(b"same-image")
    values = tmp_path / "compare.json"
    values.write_text(json.dumps({
        "before_image": "assets/same.png",
        "after_image": "assets/same.png",
        "claim": "Changed",
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="identical inputs"):
        hf.render_html(project, tmp_path / "out.mp4", variables_file=values)
    assert "cmd" not in captured


def test_render_before_after_accepts_hash_registered_controlled_pair(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    video = tmp_path / "video"
    project = hf.init_project(
        tmp_path / "some" / "deep" / "compare",
        template="before-after",
    )
    before = project / "assets" / "before.png"
    after = project / "assets" / "after.png"
    before.write_bytes(b"before")
    after.write_bytes(b"after")
    source, asset_id, geometry, record = _approved_source(video)
    values = video / "compare.json"
    values.write_text(json.dumps({
        "before_image": "assets/before.png",
        "after_image": "assets/after.png",
        "claim": "Changed",
    }), encoding="utf-8")
    evidence = video / "compare.evidence.json"
    evidence.write_text(json.dumps({
        "schema": "devlog.visual_block_evidence/v2",
        "template": "before-after",
        "source": {
            "asset_id": asset_id,
            "path": "data/footage/source.mp4",
            "sha256": _sha256(source),
            "registry_revision": record.revision,
            "validation_sha256": record.validation_sha256,
        },
        "geometry_report": {
            "path": "data/review/geometry_report.json",
            "sha256": _sha256(geometry),
            "record": {"beat_id": "day4", "segment_index": 0},
        },
        "assets": {
            "before_image": {
                "path": "assets/before.png",
                "sha256": _sha256(before),
                "source_asset_id": asset_id,
                "source_sha256": _sha256(source),
                "recipe": {
                    "source_time_seconds": 1.0,
                    "crop": [0, 0, 1920, 1080],
                    "output": [1920, 1080],
                },
            },
            "after_image": {
                "path": "assets/after.png",
                "sha256": _sha256(after),
                "source_asset_id": asset_id,
                "source_sha256": _sha256(source),
                "recipe": {
                    "source_time_seconds": 3.0,
                    "crop": [0, 0, 1920, 1080],
                    "output": [1920, 1080],
                },
            },
        },
    }), encoding="utf-8")
    expected = {
        1.0: _sha256(before),
        3.0: _sha256(after),
    }
    monkeypatch.setattr(
        vbe,
        "_recompute_derived_hash",
        lambda source_path, recipe: expected[recipe["source_time_seconds"]],
    )

    hf.render_html(
        project,
        video / "compare.mp4",
        variables_file=values,
        evidence_file=evidence,
        production_root=video,
    )
    assert "cmd" in captured


def test_render_proof_rejects_reapproved_metadata_revision_with_same_media(
    tmp_path,
    monkeypatch,
):
    from dlstudio.services.asset_registry import (
        _register_ingested_captures,
        approve_asset,
    )

    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    video = tmp_path / "video"
    source, asset_id, geometry, old_record = _approved_source(video)
    metadata = video / "data" / "footage" / "source.mp4.capture.json"
    game_report = video / "data" / "footage" / "source.mp4.game.json"
    batch = video / "data" / "plan" / "capture_batch.json"
    results = video / "data" / "plan" / "capture_results.json"
    registry = _register_ingested_captures(video, [{
        "request_id": "day4_visual",
        "artifact_path": "data/footage/source.mp4",
        "artifact_sha256": _sha256(source),
        "metadata_path": "data/footage/source.mp4.capture.json",
        "metadata_sha256": _sha256(metadata),
        "game_report_path": "data/footage/source.mp4.game.json",
        "game_report_sha256": _sha256(game_report),
        "capture_batch_path": "data/plan/capture_batch.json",
        "capture_batch_sha256": _sha256(batch),
        "capture_results_path": "data/plan/capture_results.json",
        "capture_results_sha256": _sha256(results),
        "editorial_role": "gameplay",
        "capture_method": "realtime_window",
        "state_id": "day4.different_state",
        "build_id": "exe-sha256:" + "b" * 64,
        "action_id": "different_visual_pass",
        "seed": 43,
        "parameters": {},
        "initial_semantic_hash": "00000003",
        "action_semantic_hash": "00000004",
        "actual_width": 1920,
        "actual_height": 1080,
        "actual_fps": 30,
        "actual_duration": 15,
        "simulation_rate": 1.0,
        "continuous": True,
        "clean_ui": True,
        "client_area": True,
        "cursor_visible": False,
        "content_seconds": 5,
        "head_handle_seconds": 5,
        "tail_handle_seconds": 5,
        "frame_audit_passed": True,
        "game_elapsed_seconds": 15,
        "measured_playback_rate": 1.0,
        "presentation": {"fit": "contain", "scale": 1.0},
    }])
    current = registry.assets[0]
    approve_asset(
        video,
        asset_id,
        expected_sha256=_sha256(source),
        expected_revision=current.revision,
        expected_validation_sha256=current.validation_sha256,
        approved_by="test",
    )
    project = hf.init_project(tmp_path / "proof", template="before-after")
    before = project / "assets" / "before.png"
    after = project / "assets" / "after.png"
    before.write_bytes(b"before")
    after.write_bytes(b"after")
    values = video / "values.json"
    values.write_text(json.dumps({
        "before_image": "assets/before.png",
        "after_image": "assets/after.png",
        "claim": "Changed",
    }), encoding="utf-8")
    evidence = video / "evidence.json"
    evidence.write_text(json.dumps({
        "schema": "devlog.visual_block_evidence/v2",
        "template": "before-after",
        "source": {
            "asset_id": asset_id,
            "path": "data/footage/source.mp4",
            "sha256": _sha256(source),
            "registry_revision": old_record.revision,
            "validation_sha256": old_record.validation_sha256,
        },
        "geometry_report": {
            "path": "data/review/geometry_report.json",
            "sha256": _sha256(geometry),
            "record": {"beat_id": "day4", "segment_index": 0},
        },
        "assets": {},
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="exact approved registry revision"):
        hf.render_html(
            project,
            video / "out.mp4",
            variables_file=values,
            evidence_file=evidence,
            production_root=video,
        )
    assert "cmd" not in captured


def test_render_proof_rejects_recipe_outside_a3_geometry(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    video = tmp_path / "video"
    source, asset_id, geometry, record = _approved_source(video)
    project = hf.init_project(tmp_path / "proof", template="before-after")
    before = project / "assets" / "before.png"
    after = project / "assets" / "after.png"
    before.write_bytes(b"before")
    after.write_bytes(b"after")
    values = video / "values.json"
    values.write_text(json.dumps({
        "before_image": "assets/before.png",
        "after_image": "assets/after.png",
        "claim": "Changed",
    }), encoding="utf-8")
    common_source = {
        "source_asset_id": asset_id,
        "source_sha256": _sha256(source),
    }
    evidence = video / "evidence.json"
    evidence.write_text(json.dumps({
        "schema": "devlog.visual_block_evidence/v2",
        "template": "before-after",
        "source": {
            "asset_id": asset_id,
            "path": "data/footage/source.mp4",
            "sha256": _sha256(source),
            "registry_revision": record.revision,
            "validation_sha256": record.validation_sha256,
        },
        "geometry_report": {
            "path": "data/review/geometry_report.json",
            "sha256": _sha256(geometry),
            "record": {"beat_id": "day4", "segment_index": 0},
        },
        "assets": {
            "before_image": {
                **common_source,
                "path": "assets/before.png",
                "sha256": _sha256(before),
                "recipe": {
                    "source_time_seconds": 1.0,
                    "crop": [10, 0, 1910, 1080],
                    "output": [1920, 1080],
                },
            },
            "after_image": {
                **common_source,
                "path": "assets/after.png",
                "sha256": _sha256(after),
                "recipe": {
                    "source_time_seconds": 3.0,
                    "crop": [10, 0, 1910, 1080],
                    "output": [1920, 1080],
                },
            },
        },
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="does not match the A3 geometry"):
        hf.render_html(
            project,
            video / "out.mp4",
            variables_file=values,
            evidence_file=evidence,
            production_root=video,
        )
    assert "cmd" not in captured


def test_render_before_after_rejects_stale_evidence_hash(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    video = tmp_path / "video"
    project = hf.init_project(
        video / "data" / "hyperframes" / "compare",
        template="before-after",
    )
    before = project / "assets" / "before.png"
    after = project / "assets" / "after.png"
    before.write_bytes(b"before")
    after.write_bytes(b"after")
    source, asset_id, geometry, record = _approved_source(video)
    values = video / "compare.json"
    values.write_text(json.dumps({
        "before_image": "assets/before.png",
        "after_image": "assets/after.png",
        "claim": "Changed",
    }), encoding="utf-8")
    evidence = video / "compare.evidence.json"
    evidence.write_text(json.dumps({
        "schema": "devlog.visual_block_evidence/v2",
        "template": "before-after",
        "source": {
            "asset_id": asset_id,
            "path": "data/footage/source.mp4",
            "sha256": "0" * 64,
            "registry_revision": record.revision,
            "validation_sha256": record.validation_sha256,
        },
        "geometry_report": {
            "path": "data/review/geometry_report.json",
            "sha256": _sha256(geometry),
            "record": {"beat_id": "day4", "segment_index": 0},
        },
        "assets": {},
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="exact approved registry revision"):
        hf.render_html(
            project,
            video / "compare.mp4",
            variables_file=values,
            evidence_file=evidence,
        )
    assert "cmd" not in captured


def test_render_visual_block_rejects_asset_outside_project(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "focus", template="focus-callout")
    outside = tmp_path / "outside.png"
    outside.write_bytes(b"png")
    values = tmp_path / "focus.json"
    values.write_text(json.dumps({
        "image": "../outside.png",
        "label": "Look",
        "explanation": "Here",
        "focus_x": 50,
        "focus_y": 50,
    }), encoding="utf-8")

    with pytest.raises(RuntimeError, match="must stay inside"):
        hf.render_html(project, tmp_path / "out.mp4", variables_file=values)
    assert "cmd" not in captured


def test_render_html_rejects_missing_variables_file_before_subprocess(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "cta", template="cta-endcard")

    with pytest.raises(RuntimeError, match="variables file not found"):
        hf.render_html(
            project,
            tmp_path / "out.mp4",
            variables_file=tmp_path / "missing.json",
        )
    assert "cmd" not in captured


def test_render_html_rejects_unknown_quality(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "bars")
    with pytest.raises(ValueError, match="unsupported quality"):
        hf.render_html(project, tmp_path / "out.mp4", quality="ultra")
    assert "cmd" not in captured  # rejected before any subprocess work


def test_render_html_env_carries_use_system_ca_and_no_color(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    monkeypatch.delenv("NODE_OPTIONS", raising=False)
    project = hf.init_project(tmp_path / "bars")
    hf.render_html(project, tmp_path / "out.mp4")
    env = captured["kwargs"]["env"]
    assert env["NODE_OPTIONS"] == "--use-system-ca"
    assert env["NO_COLOR"] == "1"


def test_render_html_preserves_existing_node_options(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    monkeypatch.setenv("NODE_OPTIONS", "--max-old-space-size=4096")
    project = hf.init_project(tmp_path / "bars")
    hf.render_html(project, tmp_path / "out.mp4")
    node_options = captured["kwargs"]["env"]["NODE_OPTIONS"]
    assert "--max-old-space-size=4096" in node_options
    assert "--use-system-ca" in node_options


def test_render_html_does_not_duplicate_use_system_ca(tmp_path, monkeypatch):
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    monkeypatch.setenv("NODE_OPTIONS", "--use-system-ca")
    project = hf.init_project(tmp_path / "bars")
    hf.render_html(project, tmp_path / "out.mp4")
    node_options = captured["kwargs"]["env"]["NODE_OPTIONS"]
    assert node_options.count("--use-system-ca") == 1


def test_render_html_subprocess_decodes_utf8_with_replace(tmp_path, monkeypatch):
    # 0.12 class: child output must be decoded as utf-8+replace, never the
    # ANSI code page (Cyrillic paths are the target environment).
    captured: dict = {}
    _mock_toolchain(monkeypatch, captured)
    project = hf.init_project(tmp_path / "bars")
    hf.render_html(project, tmp_path / "out.mp4")
    kwargs = captured["kwargs"]
    assert kwargs["encoding"] == "utf-8"
    assert kwargs["errors"] == "replace"
    assert kwargs["text"] is True
    assert kwargs["capture_output"] is True


# ─── render_html: error paths ───────────────────────────────────────────

def test_render_html_missing_npx_raises_clear_error(tmp_path, monkeypatch):
    monkeypatch.setattr(hf.shutil, "which", lambda name: None)
    project = hf.init_project(tmp_path / "bars")
    with pytest.raises(RuntimeError, match="Node.js 22"):
        hf.render_html(project, tmp_path / "out.mp4")


def test_render_html_missing_entry_file_raises_before_npx_probe(tmp_path, monkeypatch):
    # entry check comes first, so the most actionable error wins even on a
    # machine without node -- which() returning None must not mask it
    monkeypatch.setattr(hf.shutil, "which", lambda name: None)
    empty = tmp_path / "empty_project"
    empty.mkdir()
    with pytest.raises(RuntimeError, match="index.html"):
        hf.render_html(empty, tmp_path / "out.mp4")


def test_render_html_failure_raises_with_stderr_tail(tmp_path, monkeypatch):
    captured: dict = {}
    stderr = "\n".join([f"noise line {i}" for i in range(30)] + ["boom: chrome not found"])
    _mock_toolchain(monkeypatch, captured, rc=1, stderr=stderr)
    project = hf.init_project(tmp_path / "bars")
    out = tmp_path / "out" / "bars.mp4"

    with pytest.raises(RuntimeError, match="rc=1") as excinfo:
        hf.render_html(project, out)
    assert "boom: chrome not found" in str(excinfo.value)

    debug = out.resolve().with_suffix(".mp4.hyperframes_error.txt")
    assert debug.is_file()
    assert "boom: chrome not found" in debug.read_text(encoding="utf-8")
