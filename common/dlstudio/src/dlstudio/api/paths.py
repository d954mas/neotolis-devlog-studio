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

from pathlib import Path, PureWindowsPath

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


def _strip_extended_prefix(p: Path) -> Path:
    """Normalize Windows extended-length forms (`\\\\?\\C:\\...`,
    `\\\\?\\UNC\\host\\...`) back to the plain form.

    Under CONCURRENT directory creation/removal (two Studio jobs churning
    data/finalize), `Path.resolve()` on Windows can transiently return the
    `\\\\?\\`-prefixed form for one path and the plain form for another —
    making `relative_to` fail for a path that IS inside the root, so
    `safe_join` intermittently rejected the beat's own declared wav/words
    paths. Canonicalizing the prefix keeps the containment check about the
    actual path, not about which form the resolver happened to emit."""
    s = str(p)
    if s.startswith("\\\\?\\UNC\\"):
        return Path("\\\\" + s[8:])
    if s.startswith("\\\\?\\"):
        return Path(s[4:])
    return p


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
    windows_path = PureWindowsPath(rel)
    # Absolute, drive-letter (C:\...), or UNC (\\host\share) paths are never
    # "under root" — reject before any resolution.
    if (
        p.is_absolute()
        or p.drive
        or p.anchor not in ("", "/", "\\")
        or windows_path.drive
        or windows_path.root
    ):
        return None
    root_r = _strip_extended_prefix(root.resolve())
    # Two attempts: under concurrent create/delete churn Windows can also
    # transiently resolve THROUGH a just-deleted directory (an NTFS
    # `C:\\$Extend\\$Deleted\\...` tombstone path). One immediate re-resolve
    # sees the settled tree; a genuine traversal fails both times.
    candidate = None
    for _ in range(2):
        candidate = _strip_extended_prefix((root_r / p).resolve())
        try:
            candidate.relative_to(root_r)
            return candidate
        except ValueError:
            continue
    return None
