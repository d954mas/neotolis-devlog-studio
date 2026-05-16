"""Fast workspace self-test orchestration."""
from __future__ import annotations

import os
import importlib.util
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

from devlog.config import DevlogConfig


@dataclass(frozen=True)
class SmokeStep:
    name: str
    command: list[str]
    returncode: int


def workspace_root(config: DevlogConfig) -> Path:
    if config.path:
        return config.path.parent
    return Path.cwd()


def run_smoke(config: DevlogConfig, *, skip_tests: bool = False, deep_check: bool = False) -> list[SmokeStep]:
    root = workspace_root(config)
    commands: list[tuple[str, list[str]]] = []
    if not skip_tests and (root / "common" / "tests").exists() and importlib.util.find_spec("pytest") is not None:
        commands.append(("tests", [sys.executable, "-m", "pytest", "common/tests", "-q"]))
    check_cmd = [sys.executable, "-m", "devlog", "check"]
    if deep_check:
        check_cmd.append("--deep")
    commands.append(("check", check_cmd))
    commands.append(("beats", [sys.executable, "-m", "devlog", "beats", "--missing-only"]))

    env = os.environ.copy()
    py_path = [str(root / "common"), str(root)]
    old = env.get("PYTHONPATH")
    if old:
        py_path.append(old)
    env["PYTHONPATH"] = os.pathsep.join(py_path)

    steps: list[SmokeStep] = []
    for name, cmd in commands:
        r = subprocess.run(cmd, cwd=root, env=env, check=False)
        steps.append(SmokeStep(name=name, command=cmd, returncode=r.returncode))
        if r.returncode != 0:
            break
    return steps


def format_smoke(steps: list[SmokeStep]) -> str:
    lines = []
    for step in steps:
        tag = "OK" if step.returncode == 0 else "FAIL"
        lines.append(f"[{tag}] {step.name}: {' '.join(step.command)}")
    return "\n".join(lines)
