from __future__ import annotations

from pathlib import Path

from dlstudio import cli


def _production(tmp_path: Path, monkeypatch) -> Path:
    (tmp_path / "devlog.toml").write_text("", encoding="utf-8")
    product = tmp_path / "game"
    production = product / "reels" / "2026_07_18_reel_01"
    (production / "edit").mkdir(parents=True)
    (production / "edit" / "__init__.py").write_text("", encoding="utf-8")
    (product / "product.toml").write_text(
        'id="game"\ntitle="Game"\ngame_root="."\n[sources]\n', encoding="utf-8"
    )
    (production / "production.toml").write_text(
        '\n'.join((
            'id="2026_07_18_reel_01"', 'kind="reel"', 'date="2026-07-18"',
            'orientation="vertical"', 'edit_path="edit"', 'data_root="data"',
            'delivery_root="../../delivery/reels/2026_07_18_reel_01"',
        )), encoding="utf-8"
    )
    monkeypatch.chdir(tmp_path)
    return production


def test_record_stage_cli_attributes_role_tokens_and_artifact(tmp_path, monkeypatch):
    production = _production(tmp_path, monkeypatch)
    artifact = production / "data" / "review" / "review.txt"
    artifact.parent.mkdir(parents=True)
    artifact.write_text("review", encoding="utf-8")

    args = cli._build_parser().parse_args([
        "record-stage", str(production), "--stage", "review", "--role", "reviewer",
        "--wall-ms", "1200", "--input-tokens", "50", "--cached-input-tokens", "40",
        "--output-tokens", "10", "--artifact", str(artifact),
    ])
    assert args.func(args) == 0

    import json
    summary = json.loads((production / "data/review/telemetry_summary.json").read_text(encoding="utf-8"))
    assert summary["by_stage"]["review"]["input_tokens"] == 50
    assert summary["by_agent_role"]["reviewer"]["output_tokens"] == 10


def test_human_checkpoint_is_attributed_to_run(tmp_path, monkeypatch):
    from dlstudio.cli.telemetry import record_human_checkpoint

    production = _production(tmp_path, monkeypatch)
    state = production / "data/review/autopilot_run.json"
    state.parent.mkdir(parents=True)
    state.write_text("{}", encoding="utf-8")

    record_human_checkpoint(
        production,
        run_id="run_20260718_human",
        human_active_ms=480000,
        artifact_paths=(state,),
    )

    import json
    summary = json.loads((production / "data/review/telemetry_summary.json").read_text(encoding="utf-8"))
    assert summary["by_run_id"]["run_20260718_human"]["human_wait_ms"] == 480000
    assert summary["by_agent_role"]["author"]["events"] == 1
