"""Path-safety helpers for the Studio API — ports of legacy
common/devlog/web/serve.py `_safe_filename` semantics, hardened for v2.

Two levels of check:

- `safe_component` guards a single path SEGMENT (a beat id, an uploaded
  filename): no traversal (`..`), no separators, no NUL, bounded length.
  This is the legacy `_safe_filename` rule verbatim.
- `safe_join` guards an arbitrary RELATIVE path that the client supplies to
  read a file under the project root (`GET /api/file?path=...`). It rejects
  absolute paths, Windows drive/UNC anchors, NUL, and — the load-bearing
  check — any path that resolves OUTSIDE the project root, which catches
  `../` traversal (raw or percent-decoded by Starlette before it reaches us)
  even when the path legitimately contains sub-directory separators.
"""
from __future__ import annotations

from pathlib import Path

_MAX_NAME = 200


def safe_component(name: str) -> str | None:
    """A single path component (beat id / filename). Returns the name if it
    is safe, else None. Mirrors legacy `_safe_filename`."""
    if not name:
        return None
    if ".." in name or "/" in name or "\\" in name or "\x00" in name:
        return None
    if len(name) > _MAX_NAME:
        return None
    return name


def safe_join(root: Path, rel: str) -> Path | None:
    """Resolve `rel` under `root`. Returns the resolved absolute Path (which
    need not exist) when it stays inside `root`, else None.

    Rejects: empty/NUL input, absolute paths, drive/UNC-anchored paths, and
    anything that escapes `root` after resolution (`..` traversal, symlink
    escapes). Percent-encoded traversal is already decoded to real `..` by
    Starlette's query parsing, so it is caught by the resolve + containment
    check here."""
    if not rel or "\x00" in rel:
        return None
    p = Path(rel)
    # Absolute, drive-letter (C:\...), or UNC (\\host\share) paths are never
    # "under root" — reject before any resolution.
    if p.is_absolute() or p.drive or p.anchor not in ("", "/", "\\"):
        return None
    root_r = root.resolve()
    candidate = (root_r / p).resolve()
    try:
        candidate.relative_to(root_r)
    except ValueError:
        return None
    return candidate
