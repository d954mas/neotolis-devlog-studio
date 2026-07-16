"""cache — atomic, content-addressable render cache.

OWNER: cli-agent.

v2 requirements (fixes v1's known risks):
- ATOMIC publish: temp file + os.replace; parallel workers racing on one
  key or a crash mid-copy must never leave a truncated MP4 as a hit.
- Engine hash AUTO-DERIVED from the dlstudio package source tree (glob
  all *.py under dlstudio/) — no manual _ENGINE_FILES list to forget.
- Key inputs: IRBeat (model_dump_json), Design, RenderOpts-equivalent
  flags, and identity (size + mtime) of every referenced asset path.
- Levels: beat MP4 now; chunk-PNG level may be added later.
"""
from __future__ import annotations

from pathlib import Path

from dlstudio.ir import IRBeat
from dlstudio.model import Design

CACHE_DIR = Path("data/finalize/.cache2")


def beat_key(beat: IRBeat, design: Design, *, quality: str, width: int | None, gpu: bool) -> str:
    raise NotImplementedError("cli-agent implements this")


def get(key: str, out_path: Path) -> bool:
    raise NotImplementedError("cli-agent implements this")


def put(key: str, rendered_path: Path) -> None:
    raise NotImplementedError("cli-agent implements this")
