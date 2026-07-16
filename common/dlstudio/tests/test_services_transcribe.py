"""services.transcribe: backend selection + words.json schema writing.

No test here imports or runs whisper/whisperx (heavy, optional deps; not
installed in CI). Backend selection is tested by monkeypatching
`_backend_available`; schema writing is tested by monkeypatching the
backend functions (`_run_whisper`/`_run_whisperx`) with a fake in-memory
result. The schema-compatibility test feeds the written JSON straight
through `dlstudio.compile.words.load_words` -- the actual consumer -- to
confirm the output this module writes is what compile/words.py expects.
"""
from __future__ import annotations

import importlib
import json

import pytest

from dlstudio.compile.words import load_words
from dlstudio.services import transcribe as transcribe_fn

# `dlstudio.services.__init__` does `from .transcribe import transcribe`,
# which -- because the submodule and the re-exported function share the
# name "transcribe" -- overwrites the `dlstudio.services.transcribe`
# ATTRIBUTE with the function (same reason `dlstudio.render` exports
# `render_beat`, not `beat`, as its top-level name: it avoids exactly this
# collision). `importlib.import_module` looks the submodule up by its
# sys.modules key instead of via that (shadowed) attribute, so it reliably
# returns the actual module regardless.
transcribe_mod = importlib.import_module("dlstudio.services.transcribe")


# ─── backend resolution ─────────────────────────────────────────────────────

def test_resolve_backend_explicit_whisper():
    assert transcribe_mod._resolve_backend("whisper") == "whisper"


def test_resolve_backend_explicit_whisperx():
    assert transcribe_mod._resolve_backend("whisperx") == "whisperx"


def test_resolve_backend_unknown_raises():
    with pytest.raises(ValueError, match="unknown backend"):
        transcribe_mod._resolve_backend("nope")


def test_resolve_backend_auto_prefers_whisperx_when_available(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "_backend_available", lambda name: name == "whisperx")
    assert transcribe_mod._resolve_backend("auto") == "whisperx"


def test_resolve_backend_auto_falls_back_to_whisper_when_whisperx_missing(monkeypatch):
    monkeypatch.setattr(transcribe_mod, "_backend_available", lambda name: False)
    assert transcribe_mod._resolve_backend("auto") == "whisper"


def test_backend_available_reflects_real_import_machinery():
    # whisperx is not installed in this environment/CI; whisper (per this
    # repo's baseline test env) is. Exercises the real importlib.util.find_spec
    # path (not monkeypatched) so the two branches above have real cover too.
    assert transcribe_mod._backend_available("definitely_not_a_real_module_xyz") is False


def test_transcribe_unknown_backend_raises_without_touching_filesystem(tmp_path):
    wav = tmp_path / "in.wav"
    out = tmp_path / "words.json"
    with pytest.raises(ValueError, match="unknown backend"):
        transcribe_fn(wav, out, backend="nope")
    assert not out.exists()


# ─── schema writing (faked backend, no real model) ─────────────────────────

_FAKE_RESULT = {
    "language": "ru",
    "text": "hello world",
    "duration": 1.234,
    "words": [
        {"word": "hello", "start": 0.0, "end": 0.4, "prob": 0.99},
        {"word": "world", "start": 0.5, "end": 1.0, "prob": 0.95},
    ],
}


def test_transcribe_writes_expected_schema(tmp_path, monkeypatch):
    monkeypatch.setattr(transcribe_mod, "_run_whisper", lambda wav, *, language, model: dict(_FAKE_RESULT))
    wav = tmp_path / "take.wav"
    wav.write_bytes(b"")  # transcribe() never opens the audio itself
    out_json = tmp_path / "sub" / "take_words.json"

    returned = transcribe_fn(wav, out_json, backend="whisper")

    assert returned == out_json
    assert out_json.exists()
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["audio"] == str(wav)
    assert data["language"] == "ru"
    assert data["text"] == "hello world"
    assert data["duration"] == 1.234
    assert data["words"] == _FAKE_RESULT["words"]


def test_transcribe_whisperx_backend_selected_and_used(tmp_path, monkeypatch):
    calls = []

    def fake_whisperx(wav, *, language, model):
        calls.append((wav, language, model))
        return dict(_FAKE_RESULT)

    monkeypatch.setattr(transcribe_mod, "_run_whisperx", fake_whisperx)
    wav = tmp_path / "take.wav"
    out_json = tmp_path / "take_words.json"

    transcribe_fn(wav, out_json, backend="whisperx", language="en", model="small")

    assert calls == [(wav, "en", "small")]
    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["words"][0]["word"] == "hello"


def test_transcribe_auto_uses_whisperx_when_available(tmp_path, monkeypatch):
    monkeypatch.setattr(transcribe_mod, "_backend_available", lambda name: name == "whisperx")
    used = {}

    def _mark(name):
        def _fn(wav, *, language, model):
            used["backend"] = name
            return dict(_FAKE_RESULT)
        return _fn

    monkeypatch.setattr(transcribe_mod, "_run_whisperx", _mark("whisperx"))
    monkeypatch.setattr(transcribe_mod, "_run_whisper", _mark("whisper"))

    transcribe_fn(tmp_path / "t.wav", tmp_path / "t_words.json", backend="auto")

    assert used["backend"] == "whisperx"


def test_transcribe_falls_back_to_language_kwarg_when_backend_omits_language(tmp_path, monkeypatch):
    result_without_language = {**_FAKE_RESULT, "language": None}
    monkeypatch.setattr(transcribe_mod, "_run_whisper",
                        lambda wav, *, language, model: dict(result_without_language))
    out_json = tmp_path / "words.json"

    transcribe_fn(tmp_path / "t.wav", out_json, language="ru", backend="whisper")

    data = json.loads(out_json.read_text(encoding="utf-8"))
    assert data["language"] == "ru"


# ─── schema compatibility with compile/words.py (the real consumer) ────────

def test_transcribe_output_parses_via_compile_words(tmp_path, monkeypatch):
    monkeypatch.setattr(transcribe_mod, "_run_whisper", lambda wav, *, language, model: dict(_FAKE_RESULT))
    out_json = tmp_path / "words.json"

    transcribe_fn(tmp_path / "take.wav", out_json, backend="whisper")

    spans = load_words(str(out_json))
    assert len(spans) == 2
    assert spans[0].text == "hello"
    assert spans[0].t0 == 0.0
    assert spans[0].t1 == 0.4
    assert spans[1].text == "world"
    assert spans[1].t1 == 1.0


def test_transcribe_output_parses_via_compile_words_whisperx_backend(tmp_path, monkeypatch):
    monkeypatch.setattr(transcribe_mod, "_run_whisperx", lambda wav, *, language, model: dict(_FAKE_RESULT))
    out_json = tmp_path / "words.json"

    transcribe_fn(tmp_path / "take.wav", out_json, backend="whisperx")

    spans = load_words(str(out_json))
    assert [s.text for s in spans] == ["hello", "world"]
