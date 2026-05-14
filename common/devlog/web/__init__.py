"""Web tools: recorder.html, preview.html, and local server.

The local HTML pages live in this directory and load BEATS via
GET /api/project (no more inline `const BEATS = [...]`). Static HTML/JS
are served from the project root by serve.py — copy or symlink the page
files into your project's web/ folder when starting a new edit.
"""
from .serve import serve

