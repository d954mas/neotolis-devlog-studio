"""Whisper word-level transcription.

Runs Whisper on an audio file and writes a words.json with per-word start/end
timestamps. Used both standalone (`devlog transcribe`) and as the final stage
of process_beat_audio.

The language is parameterized but defaults to 'ru' since that's what trolley
needs; future projects can override per-call.
"""
from __future__ import annotations
import json
from pathlib import Path


def transcribe(
    audio_path: str,
    output_json: str,
    model_size: str = "medium",
    language: str = "ru",
    insecure_ssl: bool = False,
) -> None:
    """Transcribe audio to per-word timestamps and write JSON.

    Output format (matches the existing scripts/whisper_words.py contract):
        { "audio": <path>, "duration": <float>, "language": <lang>,
          "text": <full transcript>,
          "words": [{ "word": str, "start": float, "end": float, "prob": float }] }
    """
    if insecure_ssl:
        import ssl
        ssl._create_default_https_context = ssl._create_unverified_context

    import whisper

    print(f"[whisper] loading model '{model_size}'...")
    model = whisper.load_model(model_size)

    print(f"[whisper] transcribing {audio_path}...")
    result = model.transcribe(
        audio_path,
        language=language,
        word_timestamps=True,
        temperature=0.0,                                     # deterministic
        no_speech_threshold=0.4,
        condition_on_previous_text=False,                    # avoid hallucinations from prior context
        verbose=False,
    )

    words = []
    for seg in result.get("segments", []):
        for w in seg.get("words", []):
            words.append({
                "word": w["word"].strip(),
                "start": round(w["start"], 3),
                "end": round(w["end"], 3),
                "prob": round(w.get("probability", 1.0), 3),
            })

    out = {
        "audio": audio_path,
        "duration": round(result.get("segments", [{}])[-1].get("end", 0), 3),
        "language": result.get("language"),
        "text": result.get("text", "").strip(),
        "words": words,
    }
    Path(output_json).parent.mkdir(parents=True, exist_ok=True)
    with open(output_json, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    print(f"[whisper] {len(words)} words, duration {out['duration']}s → {output_json}")
