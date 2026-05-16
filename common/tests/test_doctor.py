import subprocess

from devlog.doctor import format_doctor, run_doctor


def test_doctor_checks_required_tools(monkeypatch):
    monkeypatch.setattr("devlog.doctor.shutil.which", lambda exe: f"/bin/{exe}")
    monkeypatch.setattr(
        "devlog.doctor.subprocess.run",
        lambda cmd, **kwargs: subprocess.CompletedProcess(cmd, 0, stdout=f"{cmd[0]} version\n", stderr=""),
    )
    checks = run_doctor(with_whisper=False)
    names = {c.name for c in checks}
    assert {"ffmpeg", "ffprobe", "PIL", "numpy"} <= names
    text = format_doctor(checks)
    assert "[OK] ffmpeg" in text


def test_doctor_reports_missing_command(monkeypatch):
    monkeypatch.setattr("devlog.doctor.shutil.which", lambda exe: None)
    checks = run_doctor(with_whisper=False)
    ffmpeg = next(c for c in checks if c.name == "ffmpeg")
    assert ffmpeg.ok is False
    assert "not found" in ffmpeg.detail
