"""Text rendering helpers: language-aware font selection.

Cyrillic glyphs (especially Й/Ё with diacritics) render cleaner in fonts
designed for them. Engine picks `design.fonts.text` for any text containing
Cyrillic, otherwise `design.fonts.display` (geometric, good for numbers/Latin).
"""
from __future__ import annotations
from devlog.types import Design


def has_cyrillic(text: str) -> bool:
    """True if text contains any Cyrillic character (basic + extended)."""
    return any('Ѐ' <= ch <= 'ӿ' for ch in text)


def pick_font(text: str, design: Design) -> str:
    """Return the TTF path appropriate for the script in `text`."""
    return design.fonts.text if has_cyrillic(text) else design.fonts.display
