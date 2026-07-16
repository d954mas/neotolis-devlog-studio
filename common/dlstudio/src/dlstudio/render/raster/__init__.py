"""render.raster — PIL pre-render of chunk visuals to RGBA PNGs.

OWNER: raster-agent (port of legacy plate/overlay/image/effects/text
renderers to the v2 composition model).

Rules:
- (spec, design) discipline: styling comes from Design.styles / Palette;
  no module-level brand constants.
- Content variants (Plate/Overlay/ImageShot) map to renderers; the
  `decorations` list composes on top (Underline, Badge, FramedCard,
  Vignette, Label, CaptionPill each render as an independent pass).
- Cyrillic-capable font selection: port from legacy render/text.py.
- px()/scale semantics: port from legacy devlog/types.py Design.px —
  if legacy semantics differ from dlstudio.model.Design.px, align the
  model helper to legacy behavior and note it in the commit.
"""
from __future__ import annotations

from pathlib import Path

from PIL import Image

from dlstudio.model import Chunk, Design


def render_chunk_png(chunk: Chunk, design: Design, out_path: Path) -> Path:
    """Render the chunk's visual (content + decorations) to an RGBA PNG at
    design resolution. Deterministic: same inputs -> byte-stable output
    (required for cache correctness and golden tests)."""
    raise NotImplementedError("raster-agent implements this")


def render_chunk_image(chunk: Chunk, design: Design) -> Image.Image:
    """Same as render_chunk_png but returns the PIL image (for tests)."""
    raise NotImplementedError("raster-agent implements this")
