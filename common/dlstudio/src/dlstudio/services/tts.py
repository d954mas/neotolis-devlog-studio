"""Scratch VO synthesis: throwaway TTS for pacing/timing checks before a real
recording session.

Port of legacy `dl scratch-tts` (common/devlog/cli.py `cmd_scratch_tts` /
`_windows_sapi_tts` / `_windows_sapi_voices`): Windows SAPI via
`System.Speech.Synthesis.SpeechSynthesizer`, driven through a base64
`-EncodedCommand` PowerShell invocation (avoids all quoting/escaping issues
for arbitrary — including Cyrillic — text; text and params cross the process
boundary via a temp file + env vars, exactly like legacy, rather than
interpolated into the script string).

Backend registry (`_BACKENDS`): "sapi" is implemented; "piper" and "silero"
are documented slots for docs/issues/local-russian-tts-research.md's
candidates (Russian ONNX / neural TTS) — calling them raises
`NotImplementedError` with a pointer to that doc until one is built out.
Callers select a backend by name so adding piper/silero later is a new
registry entry, not a signature change.
"""
from __future__ import annotations

import base64
import subprocess
import sys
from pathlib import Path
from typing import Callable


class UnknownTTSBackendError(ValueError):
    """`scratch_tts(..., backend=...)` named a backend not in the registry."""


def _powershell_encoded(script: str) -> str:
    return base64.b64encode(script.encode("utf-16le")).decode("ascii")


def _run_powershell(script: str, *, env: dict[str, str] | None = None,
                    check: bool = True) -> subprocess.CompletedProcess:
    return subprocess.run(
        ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass",
         "-EncodedCommand", _powershell_encoded(script)],
        env=env, capture_output=True, text=True, check=check,
        # PS 5.1's ConvertTo-Json escapes non-ASCII to \uXXXX, so the payload
        # survives any codec; utf-8+replace only guards stderr from raising
        # UnicodeDecodeError on localized error text (defect 0.12 class).
        encoding="utf-8", errors="replace",
    )


_LIST_VOICES_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voices = @()
foreach ($voice in $s.GetInstalledVoices()) {
  $info = $voice.VoiceInfo
  $voices += [PSCustomObject]@{
    Name = $info.Name
    Culture = $info.Culture.Name
    Gender = $info.Gender.ToString()
    Age = $info.Age.ToString()
  }
}
$voices | ConvertTo-Json -Compress
"""

_SPEAK_SCRIPT = r"""
$ErrorActionPreference = 'Stop'
$ProgressPreference = 'SilentlyContinue'
Add-Type -AssemblyName System.Speech
$s = New-Object System.Speech.Synthesis.SpeechSynthesizer
$voice = $env:DEVLOG_TTS_VOICE
if ($voice) {
  $s.SelectVoice($voice)
}
$s.Rate = [Math]::Max(-10, [Math]::Min(10, [int]$env:DEVLOG_TTS_RATE))
$s.Volume = [Math]::Max(0, [Math]::Min(100, [int]$env:DEVLOG_TTS_VOLUME))
$text = Get-Content -LiteralPath $env:DEVLOG_TTS_TEXT -Raw -Encoding UTF8
$s.SetOutputToWaveFile($env:DEVLOG_TTS_OUT)
$s.Speak($text)
$s.Dispose()
"""


def list_sapi_voices() -> list[dict[str, str]]:
    """Installed Windows SAPI voices as `{"Name", "Culture", "Gender",
    "Age"}` dicts (ported from legacy `_windows_sapi_voices`). Windows-only;
    raises `RuntimeError` elsewhere."""
    if sys.platform != "win32":
        raise RuntimeError("list_sapi_voices: Windows SAPI is only available on Windows.")
    proc = _run_powershell(_LIST_VOICES_SCRIPT)
    payload = proc.stdout.strip()
    if not payload:
        return []
    import json
    parsed = json.loads(payload)
    return parsed if isinstance(parsed, list) else [parsed]


def _sapi_tts(text: str, out_wav: Path, *, voice: str | None, rate: int, volume: int) -> Path:
    if sys.platform != "win32":
        raise RuntimeError("scratch_tts: backend 'sapi' only works on Windows.")

    out_wav.parent.mkdir(parents=True, exist_ok=True)
    text_path = out_wav.with_suffix(".txt")
    text_path.write_text(text, encoding="utf-8")

    import os
    env = os.environ.copy()
    env.update({
        "DEVLOG_TTS_TEXT": str(text_path.resolve()),
        "DEVLOG_TTS_OUT": str(out_wav.resolve()),
        "DEVLOG_TTS_VOICE": voice or "",
        "DEVLOG_TTS_RATE": str(rate),
        "DEVLOG_TTS_VOLUME": str(volume),
    })
    _run_powershell(_SPEAK_SCRIPT, env=env)
    return out_wav


def _piper_tts(text: str, out_wav: Path, *, voice: str | None, rate: int, volume: int) -> Path:
    raise NotImplementedError(
        "scratch_tts: backend 'piper' is not implemented yet. See "
        "docs/issues/local-russian-tts-research.md — candidate ru voices "
        "(rhasspy/piper-voices ru/ru_RU): denis, dmitri, irina, ruslan. "
        "Blocked on: confirming a maintained fork/tooling (upstream "
        "rhasspy/piper is archived)."
    )


def _silero_tts(text: str, out_wav: Path, *, voice: str | None, rate: int, volume: int) -> Path:
    raise NotImplementedError(
        "scratch_tts: backend 'silero' is not implemented yet. See "
        "docs/issues/local-russian-tts-research.md — candidate speakers: "
        "aidar, baya, kseniya, xenia, eugene. Blocked on: PyTorch + model "
        "download (not zero-dependency) and confirming license terms for "
        "production/commercial output."
    )


_BACKENDS: dict[str, Callable[..., Path]] = {
    "sapi": _sapi_tts,
    "piper": _piper_tts,
    "silero": _silero_tts,
}


def scratch_tts(
    text: str,
    out_wav: Path,
    *,
    backend: str = "sapi",
    voice: str | None = None,
    rate: int = 1,
    volume: int = 100,
) -> Path:
    """Synthesize `text` to `out_wav` via a scratch (throwaway-quality) TTS
    backend, for pacing/timing checks before a real VO recording.

    `backend`: one of `_BACKENDS` ("sapi" implemented now; "piper"/"silero"
    are documented future slots that raise `NotImplementedError`). Raises
    `UnknownTTSBackendError` (a `ValueError`) for any other name.
    """
    if not text.strip():
        raise ValueError("scratch_tts: text is empty")
    if backend not in _BACKENDS:
        raise UnknownTTSBackendError(
            f"scratch_tts: unknown backend {backend!r} "
            f"(available: {sorted(_BACKENDS)})"
        )
    out_wav = Path(out_wav)
    return _BACKENDS[backend](text, out_wav, voice=voice, rate=rate, volume=volume)
