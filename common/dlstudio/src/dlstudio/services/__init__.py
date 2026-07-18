"""services — plugins with lazy heavy dependencies. Phase 4 scope.

Implemented so far (record -> process -> render loop, Phase 3 Studio):
  audio.py       process_take()  — VO take -> loudness-normalized wav
                  (ffmpeg-only; no heavy deps at all).
  transcribe.py  transcribe()    — wav -> words.json (whisper | whisperx).
  tts.py         scratch_tts()   — throwaway VO for pacing checks
                  (sapi implemented; piper | silero are documented slots,
                  see docs/issues/local-russian-tts-research.md).
  speech_edit.py agent plan + deterministic FFmpeg cuts + words remapping.

Phase 4 additions:
  stock.py       search()/download() — thin Pexels/Pixabay b-roll wrapper,
                  requests imported lazily, no heavy deps.
  publish.py     generate_youtube_package() — title/description/tags/
                  chapters -> youtube_package.md (no heavy deps at all).

Production-plan §1.5 addition:
  hyperframes.py init_project()/render_html() — thin `npx hyperframes`
                  bridge for HTML/GSAP motion assets (stdlib-only module;
                  node/npx is probed only when render_html actually runs).

Production-plan §1.3 addition:
  review.py      make_contact_sheet()/extract_keyframes() — review
                  artifacts from a finished MP4 (plain ffmpeg passes,
                  decoupled from the render pipeline; used by dl2 preview).

Still planned: audiofix/ (DeepFilterNet-class cleanup), capture/ (CDP +
obs-websocket).

Contract: heavy imports (whisper, whisperx, torch, requests, ...) happen
INSIDE functions, never at module import time — this __init__ and every
module here must stay importable with only the stdlib + whatever's already
a dlstudio dependency. transcribe.py's backend functions are the only place
that imports whisper/whisperx, and only when actually invoked; stock.py's
provider functions are the only place that imports requests, same rule.
"""
from __future__ import annotations

from .audio import AudioStageError, ProcessResult, process_take
from .hyperframes import init_project, render_html
from .publish import generate_youtube_package
from .review import extract_keyframes, make_contact_sheet
from .speech_edit import (
    SpeechCut,
    SpeechEditPlan,
    SpeechEditResult,
    SpeechEditStageError,
    ResolvedSpeechCuts,
    build_automatic_plan,
    build_automatic_plan_from_files,
    detect_silences,
    execute_speech_edit,
    resolve_safe_cuts,
    sha256_file,
)
from .stock import StockConfigError, StockResult, download, search
from .transcribe import transcribe
from .tts import UnknownTTSBackendError, list_sapi_voices, scratch_tts

__all__ = [
    "AudioStageError",
    "ProcessResult",
    "process_take",
    "init_project",
    "render_html",
    "extract_keyframes",
    "make_contact_sheet",
    "SpeechCut",
    "SpeechEditPlan",
    "SpeechEditResult",
    "SpeechEditStageError",
    "ResolvedSpeechCuts",
    "build_automatic_plan",
    "build_automatic_plan_from_files",
    "detect_silences",
    "execute_speech_edit",
    "resolve_safe_cuts",
    "sha256_file",
    "generate_youtube_package",
    "StockConfigError",
    "StockResult",
    "download",
    "search",
    "transcribe",
    "UnknownTTSBackendError",
    "list_sapi_voices",
    "scratch_tts",
]
