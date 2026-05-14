"""devlog — reusable video production engine.

Public API:
    from devlog.types import Design, Palette, Fonts, Beat, Chunk, Scene, Edit

Subpackages:
    devlog.render   — beat composition (plate, overlay, image, video)
    devlog.charts   — bar/timeline/anim chart primitives
    devlog.audio    — whisper transcription + ffmpeg loudness
    devlog.cli      — `devlog` command-line entry points
    devlog.web      — HTML tools (recorder, preview) + serve.py

Used by per-project edits in <project>/edits/<edit_name>/{beats.py, design.py}.
"""
__version__ = "0.1.0"
