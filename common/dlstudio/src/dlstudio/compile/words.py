"""Whisper words.json parsing — v1 schema.

The transcript is the master clock (docs/ARCHITECTURE_V2.md). Every chunk
window and every SFX anchor is resolved from word indices into this list.

v1 schema (verified against legacy common/devlog/audio/transcribe.py and real
fixtures under neotolis_diary/data/finalize/*_words.json):

    {
      "audio": "<path>", "duration": <float>, "language": "<lang>",
      "text": "<full transcript>",
      "words": [{"word": str, "start": float, "end": float, "prob": float}, ...]
    }

Only the `words` array is load-bearing here; `word`/`start`/`end` map onto
WordSpan.text/t0/t1. The top-level `duration` field is NOT used — beat duration
is authoritative from the VO audio probe (v1 used audio_dur, not the transcript
duration, and the two genuinely differ: e.g. b01 audio 24.85s vs words 24.36s).
"""
from __future__ import annotations

import json
from pathlib import Path

from dlstudio.ir import WordSpan


def load_words(path: str) -> list[WordSpan]:
    """Read a v1 words.json and return WordSpans (beat-relative seconds)."""
    text = Path(path).read_text(encoding="utf-8")
    return parse_words(text, source=path)


def parse_words(raw: str, *, source: str = "<string>") -> list[WordSpan]:
    """Parse words.json content into WordSpans. Kept separate from file IO so
    tests can exercise malformed payloads without touching disk."""
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as e:  # pragma: no cover - defensive
        raise ValueError(f"words json {source!r} is not valid JSON: {e}") from e

    if not isinstance(data, dict) or "words" not in data:
        raise ValueError(
            f"words json {source!r} missing top-level 'words' array "
            f"(v1 schema: {{'words': [{{'word','start','end'}}]}})"
        )

    out: list[WordSpan] = []
    for idx, w in enumerate(data["words"]):
        try:
            out.append(
                WordSpan(
                    text=str(w["word"]),
                    t0=float(w["start"]),
                    t1=float(w["end"]),
                )
            )
        except (KeyError, TypeError, ValueError) as e:
            raise ValueError(
                f"words json {source!r} word #{idx} malformed "
                f"(need 'word'/'start'/'end'): {w!r}"
            ) from e
    return out
