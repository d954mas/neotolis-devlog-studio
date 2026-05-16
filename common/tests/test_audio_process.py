import subprocess

from devlog.audio.process import _run


def test_audio_run_uses_arg_list_without_shell(monkeypatch):
    seen = {}

    def fake_run(cmd, **kwargs):
        seen["cmd"] = cmd
        seen["kwargs"] = kwargs
        return subprocess.CompletedProcess(cmd, 0, stdout="", stderr="")

    monkeypatch.setattr("devlog.audio.process.subprocess.run", fake_run)
    _run(["ffmpeg", "-version"])
    assert seen["cmd"] == ["ffmpeg", "-version"]
    assert "shell" not in seen["kwargs"]
    assert seen["kwargs"]["capture_output"] is True
