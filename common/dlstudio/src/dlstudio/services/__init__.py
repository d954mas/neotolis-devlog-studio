"""services — plugins with lazy heavy dependencies. Phase 4 scope.

Implemented so far (record -> process -> render loop, Phase 3 Studio):
  audio.py       process_take()  — VO take -> loudness-normalized wav
                  (ffmpeg-only; no heavy deps at all).
  transcribe.py  transcribe()    — wav -> words.json (whisper | whisperx).
  tts.py         scratch_tts()   — throwaway VO for pacing checks
                  (sapi implemented; piper | silero are documented slots,
                  see docs/issues/local-russian-tts-research.md).

Still planned: audiofix/ (DeepFilterNet-class cleanup), capture/ (CDP +
obs-websocket), stock/ (thin provider wrappers), publish/ (YouTube package
generation).

Contract: heavy imports (whisper, whisperx, torch, ...) happen INSIDE
functions, never at module import time — this __init__ and every module
here must stay importable with only the stdlib + whatever's already a
dlstudio dependency. transcribe.py's backend functions are the only place
that imports whisper/whisperx, and only when actually invoked.
"""
from __future__ import annotations

from .audio import AudioStageError, ProcessResult, process_take
from .transcribe import transcribe
from .tts import UnknownTTSBackendError, list_sapi_voices, scratch_tts

__all__ = [
    "AudioStageError",
    "ProcessResult",
    "process_take",
    "transcribe",
    "UnknownTTSBackendError",
    "list_sapi_voices",
    "scratch_tts",
]
