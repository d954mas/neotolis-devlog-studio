"""Environment diagnostics for the devlog CLI."""
from __future__ import annotations

import importlib.util
import shutil
import subprocess
from dataclasses import dataclass


@dataclass(frozen=True)
class DoctorCheck:
    name: str
    ok: bool
    detail: str
    required: bool = True


def _command_version(exe: str) -> str:
    path = shutil.which(exe)
    if not path:
        return ""
    try:
        r = subprocess.run([exe, "-version"], capture_output=True, text=True, timeout=5)
    except Exception:
        return path
    first = (r.stdout or r.stderr).splitlines()
    return first[0] if first else path


def run_doctor(with_whisper: bool = False) -> list[DoctorCheck]:
    checks: list[DoctorCheck] = []
    for exe in ("ffmpeg", "ffprobe"):
        version = _command_version(exe)
        checks.append(DoctorCheck(exe, bool(version), version or "not found on PATH"))

    for module in ("PIL", "numpy"):
        found = importlib.util.find_spec(module) is not None
        checks.append(DoctorCheck(module, found, "importable" if found else "not importable"))

    if with_whisper:
        found = importlib.util.find_spec("whisper") is not None
        checks.append(DoctorCheck("whisper", found, "importable" if found else "not importable"))
    return checks


def format_doctor(checks: list[DoctorCheck]) -> str:
    lines = []
    for check in checks:
        tag = "OK" if check.ok else ("FAIL" if check.required else "WARN")
        lines.append(f"[{tag}] {check.name}: {check.detail}")
    return "\n".join(lines)
