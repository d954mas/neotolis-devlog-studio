"""Audio processing pipeline: raw recording → normalized wav + words.json.

Four-stage chain via ffmpeg + Whisper:
  1. silenceremove + highpass + adeclip   → strip leading silence, kill rumble
  2. loudnorm pass 1 (measure)           → analyze loudness profile
  3. loudnorm pass 2 (apply)             → normalize to -14 LUFS / -1 TP
  4. whisper transcription               → word-level timestamps

Loudness target -14 LUFS matches YouTube spoken-word recommendations.
"""
from __future__ import annotations
import json
import os
import re
import subprocess
from pathlib import Path

from .transcribe import transcribe


def _run(cmd: list[str]) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, capture_output=True, text=True)


def process_beat_audio(
    beat_id: str,
    recording_filename: str,
    loudness_target: float = -14.0,
    true_peak: float = -1.0,
    lra: float = 11.0,
    whisper_model: str = "medium",
    language: str = "ru",
    insecure_ssl: bool = False,
) -> None:
    """Process one beat's raw recording into normalized audio + words.json.

    Writes (relative to cwd):
      data/finalize/<beat>_preprocessed.wav   (intermediate, safe to delete)
      data/finalize/<beat>_audio_final.wav    (loudnorm output, used by compose)
      data/finalize/<beat>_words.json         (whisper output)
    """
    rec_path = f"data/recordings/{recording_filename}"
    out_pre = f"data/finalize/{beat_id}_preprocessed.wav"
    out_final = f"data/finalize/{beat_id}_audio_final.wav"
    out_words = f"data/finalize/{beat_id}_words.json"

    Path("data/finalize").mkdir(parents=True, exist_ok=True)

    # ── Stage 1: extract + leading-silence trim + highpass + adeclip ──
    print(f"[{beat_id}] Step 1: preprocess audio")
    r = _run([
        "ffmpeg", "-y", "-i", rec_path,
        "-vn", "-ac", "1", "-ar", "48000",
        "-af", "silenceremove=start_periods=1:start_duration=0.2:start_threshold=-40dB,highpass=f=60:poles=2,adeclip",
        "-c:a", "pcm_s16le", out_pre,
    ])
    if not os.path.exists(out_pre):
        raise SystemExit(f"[{beat_id}] FAILED preprocess: {r.stderr}")

    # ── Stage 2: loudnorm pass 1 — measure ──
    print(f"[{beat_id}] Step 2: measure loudness")
    r = _run([
        "ffmpeg", "-i", out_pre,
        "-af", f"loudnorm=I={loudness_target}:TP={true_peak}:LRA={lra}:print_format=json",
        "-f", "null", "-",
    ])
    output = r.stderr if r.stderr else r.stdout
    m = re.search(r'\{[^}]*"input_i"[^}]*\}', output, re.DOTALL)
    if not m:
        raise SystemExit(f"[{beat_id}] FAILED loudnorm measure: {output[-500:]}")
    measured = json.loads(m.group(0))

    # ── Stage 3: loudnorm pass 2 — apply linear normalization ──
    print(f"[{beat_id}] Step 3: apply loudnorm")
    r = _run([
        "ffmpeg", "-y", "-i", out_pre,
        "-af", (
            f"loudnorm=I={loudness_target}:TP={true_peak}:LRA={lra}:"
            f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
            f"offset={measured['target_offset']}:linear=true"
        ),
        "-ar", "48000", "-c:a", "pcm_s16le", out_final,
    ])
    if not os.path.exists(out_final):
        raise SystemExit(f"[{beat_id}] FAILED loudnorm apply: {r.stderr}")

    # ── Stage 4: whisper word-level transcription ──
    print(f"[{beat_id}] Step 4: whisper")
    transcribe(out_final, out_words, model_size=whisper_model,
               language=language, insecure_ssl=insecure_ssl)
    print(f"[{beat_id}] DONE")
