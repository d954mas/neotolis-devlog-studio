import subprocess
import sys

from devlog.config import DevlogConfig
from devlog.smoke import format_smoke, run_smoke


def test_run_smoke_builds_check_and_beats_commands(tmp_path, monkeypatch):
    (tmp_path / "devlog.toml").write_text('default_edit = "demo.edits.youtube"\n', encoding="utf-8")
    seen = []

    def fake_run(cmd, **kwargs):
        seen.append((cmd, kwargs))
        return subprocess.CompletedProcess(cmd, 0)

    monkeypatch.setattr("devlog.smoke.subprocess.run", fake_run)
    steps = run_smoke(DevlogConfig(path=tmp_path / "devlog.toml"), skip_tests=True, deep_check=True)
    assert [s.name for s in steps] == ["check", "beats"]
    assert seen[0][0] == [sys.executable, "-m", "devlog", "check", "--deep"]
    assert seen[1][0] == [sys.executable, "-m", "devlog", "beats", "--missing-only"]
    assert "PYTHONPATH" in seen[0][1]["env"]


def test_format_smoke_marks_failures():
    text = format_smoke([
        type("Step", (), {"name": "check", "command": ["x"], "returncode": 1})()
    ])
    assert "[FAIL] check" in text
