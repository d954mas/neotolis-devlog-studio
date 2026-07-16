"""dlstudio — Studio v2 engine.

Architecture contract: docs/ARCHITECTURE_V2.md at the workspace root.

Layers (import direction goes downward only):
    model/    user-facing DSL (pydantic): Edit, Beat, Chunk, styles, mix
    ir.py     Timeline IR — compile output, render input, JSON-serializable
    compile/  DSL + words.json + ffprobe facts -> Timeline
    check/    gates as code, run on Timeline (VQ-* codes)
    render/   the ONLY backend: FFmpeg (graph AST, beat render, assemble)
    cache/    atomic content-addressable cache
    services/ plugins with lazy heavy deps (transcribe, tts, capture, ...)
    cli/      `dl2` entry point

The legacy v1 engine lives at common/devlog and is frozen — read it for
reference (hard-won ffmpeg traps, raster rendering), never import from it.
"""

__version__ = "0.1.0"
