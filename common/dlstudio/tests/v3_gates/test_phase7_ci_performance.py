from __future__ import annotations

import json
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).parents[4]


@pytest.mark.reference_performance
@pytest.mark.performance_smoke
def test_reference_performance_report_is_within_budgets() -> None:
    config = json.loads(
        (REPO_ROOT / "tools" / "studio_v3_verify" / "config.json").read_text(
            encoding="utf-8"
        )
    )
    contract = config["reference_performance"]
    report = json.loads(
        (REPO_ROOT / contract["report_path"]).read_text(encoding="utf-8")
    )
    measurements = report["measurements"]
    budgets = contract["budgets"]

    assert report["schema"] == "dlstudio.reference_performance"
    assert report["version"] == 1
    assert report["reference_machine"] == {
        "operating_system": "Windows",
        "python": "3.12.4",
    }
    assert measurements["cli_help"]["runs"] == 15
    assert measurements["status_query"]["runs"] == 2000
    assert measurements["compile_check"]["runs"] == 300

    for name in ("cli_help", "status_query", "compile_check"):
        assert measurements[name]["fixture"]
        assert measurements[name]["mode"]
        assert measurements[name]["unit"]
        assert measurements[name]["p50"] <= measurements[name]["p95"]
    assert measurements["orchestration_memory"]["fixture"]
    assert measurements["orchestration_memory"]["unit"] == "bytes"
    assert measurements["cli_help"]["cold"] <= budgets["cli_help"]["cold_ms_max"]
    assert measurements["cli_help"]["p95"] <= budgets["cli_help"]["p95_ms_max"]
    assert (
        measurements["status_query"]["p95"]
        <= budgets["status_query"]["p95_ms_max"]
    )
    assert (
        measurements["compile_check"]["p95"]
        <= budgets["compile_check"]["p95_seconds_max"]
    )
    assert (
        measurements["orchestration_memory"]["peak"]
        <= budgets["orchestration_memory"]["peak_bytes_max"]
    )


def test_phase7_ci_runs_locked_cross_platform_cutover_gates() -> None:
    workflow = (REPO_ROOT / ".github" / "workflows" / "tests.yml").read_text(
        encoding="utf-8"
    )

    for required in (
        "ubuntu-24.04",
        "windows-2022",
        'python-version: "3.12.4"',
        'node-version: "22.14.0"',
        "npm ci",
        "Install FFmpeg on Ubuntu",
        "sudo apt-get install --yes ffmpeg",
        "Install FFmpeg on Windows",
        "choco install ffmpeg --yes --no-progress --limit-output",
        "ffmpeg -version",
        "Build and install the dlstudio wheel",
        "python tools/studio_v3_installed_smoke.py",
        "python -m tools.studio_v3_verify --profile cutover --scope full",
    ):
        assert required in workflow

    assert "--editable common/dlstudio" not in workflow
    smoke = (REPO_ROOT / "tools" / "studio_v3_installed_smoke.py").read_text(
        encoding="utf-8"
    )
    assert "source checkout imported instead of wheel" in smoke
    assert "installed wheel is missing dashboard assets" in smoke
