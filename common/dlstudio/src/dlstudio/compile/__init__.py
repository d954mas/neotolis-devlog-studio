"""compile — DSL + words.json + ffprobe facts -> Timeline IR.

OWNER: compile-agent (implementation may restructure submodules freely,
but this public signature is the contract).

Responsibilities:
- parse Whisper words JSON (v1 schema — see legacy common/devlog/audio/transcribe.py)
- probe referenced assets via ffprobe (skippable for unit tests)
- resolve chunk word-index windows to beat-relative seconds (+ pads)
- merge consecutive same-source scenes into segments (v1 semantics:
  first offset wins; see legacy tests common/tests/test_scene_merge.py)
- clamp offsets past EOF with a warning (v1 trap: silent audio-only render)
- compute beat durations (VO audio is authoritative), absolute placements
- resolve MusicRegions/SfxEvents onto the timeline
"""
from __future__ import annotations

from dlstudio.ir import Timeline
from dlstudio.model import Edit


def build_timeline(edit: Edit, *, probe: bool = True) -> Timeline:
    """Compile an Edit into a Timeline. `probe=False` skips ffprobe calls
    (unit tests inject AssetProbe facts instead)."""
    raise NotImplementedError("compile-agent implements this")
