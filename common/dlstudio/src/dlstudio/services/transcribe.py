"""Word-level transcription: normalized wav -> words.json.

Writes the v1 words.json schema `dlstudio.compile.words.load_words` parses
(verified against legacy common/devlog/audio/transcribe.py and real fixtures
under neotolis_diary/data/finalize/*_words.json — see compile/words.py's
module docstring for the authoritative schema note):

    {
      "audio": "<path>", "duration": <float>, "language": "<lang>",
      "text": "<full transcript>",
      "words": [{"word": str, "start": float, "end": float, "prob": float}, ...]
    }

Only `words[].word/start/end` is load-bearing for compile; `prob` and the
top-level `audio`/`duration`/`language`/`text` fields are cheap extras kept
because legacy wrote them and reviewer tooling/humans find them useful for
debugging a transcript without opening the audio.

Two backends, selected by `backend`:

- "whisper"  — openai-whisper, legacy-compatible params (word_timestamps=True,
  temperature=0, condition_on_previous_text=False — the same knobs
  common/devlog/audio/transcribe.py used, chosen there to avoid
  hallucinated continuations across segments).
- "whisperx" — preferred when available: a forced-alignment pass gives
  materially tighter word start/end boundaries than plain Whisper's decoder-
  attention timestamps, which matters here because words ARE the master
  clock (docs/ARCHITECTURE_V2.md) that every chunk window and SFX anchor is
  resolved from.
- "auto"     — whisperx if importable, else whisper. Resolution is exposed
  as `_resolve_backend`/`_backend_available` so tests can monkeypatch
  availability without either package installed.

Both backends are heavy (torch, model downloads) so imports are LAZY --
performed inside the backend functions, never at module import time
(services/__init__.py contract). No test in this package's suite imports
whisper/whisperx or runs a real model; backend result shaping is tested by
monkeypatching `_run_whisper`/`_run_whisperx`.

Deliberately dropped from legacy: the `insecure_ssl` global
`ssl._create_default_https_context = ssl._create_unverified_context`
monkeypatch legacy used to work around a corporate TLS proxy when
downloading model weights. That patches process-wide SSL verification for
every subsequent HTTPS connection in the interpreter, not just the whisper
model download — an insecure default no other code in this process should
silently inherit. If a future environment needs it, it belongs at the
environment/certificate-trust layer, not inside a transcription call.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path

_KNOWN_BACKENDS = ("whisper", "whisperx")


def _backend_available(name: str) -> bool:
    """Whether `name` is importable, without actually importing it (heavy
    deps stay lazy even during backend selection). A separate function
    (rather than inlining importlib.util.find_spec at the call site) so
    tests can monkeypatch availability for whisperx/whisper without either
    package installed."""
    try:
        return importlib.util.find_spec(name) is not None
    except (ImportError, ValueError):
        # find_spec can raise for a dotted name whose parent package isn't
        # importable; treat that the same as "not available".
        return False


def _resolve_backend(backend: str) -> str:
    if backend == "auto":
        return "whisperx" if _backend_available("whisperx") else "whisper"
    if backend not in _KNOWN_BACKENDS:
        raise ValueError(
            f"transcribe: unknown backend {backend!r} "
            f"(expected 'auto', {', '.join(repr(b) for b in _KNOWN_BACKENDS)})"
        )
    return backend


def _run_whisper(wav: Path, *, language: str, model: str) -> dict:
    """openai-whisper backend. Ported params from legacy
    common/devlog/audio/transcribe.py: word_timestamps=True (per-word
    timing), temperature=0.0 (deterministic), no_speech_threshold=0.4,
    condition_on_previous_text=False (avoid hallucinations carried across
    segments)."""
    import whisper  # heavy, lazy import

    loaded = whisper.load_model(model)
    result = loaded.transcribe(
        str(wav),
        language=language,
        word_timestamps=True,
        temperature=0.0,
        no_speech_threshold=0.4,
        condition_on_previous_text=False,
        verbose=False,
    )

    words: list[dict] = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            words.append({
                "word": w["word"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
                "prob": round(w.get("probability", 1.0), 3),
            })

    segments = result.get("segments", [])
    duration = round(segments[-1].get("end", 0), 3) if segments else 0.0
    return {
        "language": result.get("language"),
        "text": result.get("text", "").strip(),
        "duration": duration,
        "words": words,
    }


def _run_whisperx(wav: Path, *, language: str, model: str) -> dict:
    """whisperx backend: transcribe, then a forced-alignment pass for
    tighter word boundaries. Not exercised by this package's test suite
    (whisperx is a heavy optional dependency, not installed in CI) --
    structure mirrors whisperx's documented transcribe+align flow."""
    import torch  # heavy, lazy import
    import whisperx  # heavy, lazy import

    device = "cuda" if torch.cuda.is_available() else "cpu"
    compute_type = "float16" if device == "cuda" else "int8"

    asr_model = whisperx.load_model(model, device, compute_type=compute_type, language=language)
    audio = whisperx.load_audio(str(wav))
    result = asr_model.transcribe(audio, language=language)

    align_language = result.get("language", language)
    align_model, align_meta = whisperx.load_align_model(language_code=align_language, device=device)
    aligned = whisperx.align(
        result["segments"], align_model, align_meta, audio, device,
        return_char_alignments=False,
    )

    words: list[dict] = []
    for seg in aligned.get("segments", []):
        for w in seg.get("words", []):
            # whisperx leaves start/end unset for some punctuation-only
            # tokens it couldn't align; they carry no timing so they can't
            # serve as chunk-window anchors and are dropped rather than
            # written with a fabricated timestamp.
            if "start" not in w or "end" not in w:
                continue
            words.append({
                "word": str(w["word"]).strip(),
                "start": round(float(w["start"]), 3),
                "end": round(float(w["end"]), 3),
                "prob": round(float(w.get("score", 1.0)), 3),
            })

    text = " ".join(seg.get("text", "").strip() for seg in aligned.get("segments", [])).strip()
    duration = words[-1]["end"] if words else 0.0
    return {"language": align_language, "text": text, "duration": duration, "words": words}


def _dispatch(backend: str, wav: Path, *, language: str, model: str) -> dict:
    """Call the resolved backend's runner, looked up by name through the
    module's own globals (rather than a dict built at import time) so tests
    can `monkeypatch.setattr(transcribe_mod, "_run_whisper", fake)` and have
    `transcribe()` actually pick up the replacement."""
    fn = globals()[f"_run_{backend}"]
    return fn(wav, language=language, model=model)


def _write_words_json(out_json: Path, *, wav: Path, result: dict, language: str) -> None:
    payload = {
        "audio": str(wav),
        "duration": result.get("duration", 0.0),
        "language": result.get("language") or language,
        "text": result.get("text", ""),
        "words": result["words"],
    }
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")


def transcribe(
    wav: Path,
    out_json: Path,
    *,
    language: str = "ru",
    model: str = "medium",
    backend: str = "auto",
) -> Path:
    """Transcribe `wav` to per-word timestamps and write `out_json` in the
    v1 words.json schema (see module docstring). Returns `out_json`.

    `backend`: "whisperx" (preferred when importable), "whisper", or "auto"
    (whisperx if importable else whisper). Raises `ValueError` for any other
    value.
    """
    wav = Path(wav)
    out_json = Path(out_json)
    resolved = _resolve_backend(backend)
    result = _dispatch(resolved, wav, language=language, model=model)
    _write_words_json(out_json, wav=wav, result=result, language=language)
    return out_json
