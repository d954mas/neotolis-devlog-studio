"""0.12 regression (PLAN_STUDIO_V2): text-mode subprocess calls must pin
`encoding="utf-8", errors="replace"`.

On Russian Windows, `text=True` without `encoding=` decodes child output with
the ANSI code page (cp1251). ffmpeg/ffprobe emit UTF-8 — a Cyrillic asset
path in stderr (e.g. "И" = 0xD0 0x98, and 0x98 is unmapped in cp1251) raised
UnicodeDecodeError inside `subprocess.run` itself; `dl2 final` crashed in
assemble's `_loudnorm_measure`. Cyrillic project paths are the TARGET
environment, so this is enforced package-wide by AST scan: any new call site
that decodes child output without pinning utf-8 fails this test.
"""
from __future__ import annotations

import ast
from pathlib import Path

import dlstudio

PKG_DIR = Path(dlstudio.__file__).resolve().parent

_SUBPROCESS_FNS = {"run", "Popen", "check_output", "check_call", "call"}


def _subprocess_calls():
    """Yield (file, ast.Call) for every `subprocess.<fn>(...)` in the package."""
    for py in sorted(PKG_DIR.rglob("*.py")):
        tree = ast.parse(py.read_text(encoding="utf-8"), filename=str(py))
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            fn = node.func
            if (
                isinstance(fn, ast.Attribute)
                and fn.attr in _SUBPROCESS_FNS
                and isinstance(fn.value, ast.Name)
                and fn.value.id == "subprocess"
            ):
                yield py, node


def _const_equals(node: ast.expr | None, expected: object) -> bool:
    return isinstance(node, ast.Constant) and node.value == expected


def test_every_text_mode_subprocess_call_pins_utf8_replace():
    offenders: list[str] = []
    for py, call in _subprocess_calls():
        kwargs = {k.arg: k.value for k in call.keywords if k.arg is not None}
        decodes = (
            "text" in kwargs
            or "universal_newlines" in kwargs
            or "encoding" in kwargs
        )
        if not decodes:
            continue  # bytes mode (or inherited console) — nothing to decode
        if not _const_equals(kwargs.get("encoding"), "utf-8") or not _const_equals(
            kwargs.get("errors"), "replace"
        ):
            rel = py.relative_to(PKG_DIR).as_posix()
            offenders.append(f"{rel}:{call.lineno}")
    assert not offenders, (
        "text-mode subprocess calls missing encoding='utf-8', errors='replace' "
        "(UnicodeDecodeError on Cyrillic paths under ru-Windows): "
        + ", ".join(offenders)
    )


def test_scan_actually_sees_the_engine_call_sites():
    """Guard the guard: if the AST scan ever stops matching (import style
    change, package move), it would vacuously pass. The engine is known to
    shell out from these modules — require the scan to find calls there."""
    seen_files = {py.relative_to(PKG_DIR).as_posix() for py, _ in _subprocess_calls()}
    for expected in (
        "render/beat.py",
        "render/assemble.py",
        "compile/probe.py",
        "check/__init__.py",
    ):
        assert expected in seen_files, f"AST scan lost sight of {expected}"
