"""api — the typed FastAPI Studio backend (Phase 3).

`create_app(edit_module)` is the single public entry point; the `dl2 studio`
CLI command serves it with uvicorn (127.0.0.1 only). fastapi/uvicorn live in
the `[studio]` extra — importing this package requires them, so the CLI
imports it lazily behind a clear "install [studio]" error.
"""
from __future__ import annotations

from .app import create_app

__all__ = ["create_app"]
