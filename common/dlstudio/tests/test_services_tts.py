"""services.tts: scratch VO synthesis backend registry.

The backend-registry error path is platform-independent and always runs.
The real SAPI synthesis test is skipped on non-Windows platforms and when no
SAPI voice is installed (matches vo/tts CLI conventions elsewhere in this
repo of skipif-ing on the real external tool rather than mocking it away).
"""
from __future__ import annotations

import importlib
import sys

import pytest

from dlstudio.services import UnknownTTSBackendError, scratch_tts

tts_mod = importlib.import_module("dlstudio.services.tts")


def _has_sapi_voice() -> bool:
    if sys.platform != "win32":
        return False
    try:
        return bool(tts_mod.list_sapi_voices())
    except Exception:
        return False


pytestmark_sapi = pytest.mark.skipif(
    not _has_sapi_voice(), reason="Windows SAPI with an installed voice is required"
)


# ─── backend registry ───────────────────────────────────────────────────────

def test_scratch_tts_unknown_backend_raises(tmp_path):
    with pytest.raises(UnknownTTSBackendError, match="unknown backend"):
        scratch_tts("hello", tmp_path / "out.wav", backend="nope")


def test_scratch_tts_unknown_backend_is_a_value_error(tmp_path):
    # UnknownTTSBackendError should be catchable as a plain ValueError too.
    with pytest.raises(ValueError):
        scratch_tts("hello", tmp_path / "out.wav", backend="nope")


def test_scratch_tts_empty_text_raises(tmp_path):
    with pytest.raises(ValueError, match="empty"):
        scratch_tts("   ", tmp_path / "out.wav")


def test_scratch_tts_piper_backend_not_implemented_yet(tmp_path):
    with pytest.raises(NotImplementedError, match="piper"):
        scratch_tts("hello", tmp_path / "out.wav", backend="piper")


def test_scratch_tts_silero_backend_not_implemented_yet(tmp_path):
    with pytest.raises(NotImplementedError, match="silero"):
        scratch_tts("hello", tmp_path / "out.wav", backend="silero")


def test_backend_registry_contains_documented_slots():
    assert set(tts_mod._BACKENDS) == {"sapi", "piper", "silero"}


# ─── real Windows SAPI synthesis ────────────────────────────────────────────

@pytestmark_sapi
def test_scratch_tts_sapi_writes_wav(tmp_path):
    out = tmp_path / "scratch.wav"
    result = scratch_tts("hello from a test", out, backend="sapi")
    assert result == out
    assert out.exists()
    assert out.stat().st_size > 0


@pytestmark_sapi
def test_scratch_tts_sapi_supports_russian_text(tmp_path):
    voices = tts_mod.list_sapi_voices()
    ru_voice = next((v["Name"] for v in voices if v.get("Culture", "").startswith("ru")), None)
    if ru_voice is None:
        pytest.skip("no ru-RU SAPI voice installed")
    out = tmp_path / "scratch_ru.wav"
    scratch_tts("привет, это тестовая озвучка", out, backend="sapi", voice=ru_voice)
    assert out.exists()
    assert out.stat().st_size > 0


@pytestmark_sapi
def test_list_sapi_voices_returns_dicts_with_expected_keys():
    voices = tts_mod.list_sapi_voices()
    assert voices, "expected at least one installed SAPI voice"
    for v in voices:
        assert {"Name", "Culture", "Gender", "Age"} <= v.keys()
