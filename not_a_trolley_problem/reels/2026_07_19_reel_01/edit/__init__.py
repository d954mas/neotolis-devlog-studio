"""Шаблон v2-эдита — то, что `dl2 new-video` копирует в новый проект.

Конвенция загрузки: `dl2` находит edit по dotted module path
(<project>.edits.<имя>) и требует module-level EDIT именно в __init__.py;
Studio hot-reload следит за <module>, <module>.beats и <module>.design.
Поэтому структура пакета фиксирована: __init__.py (собирает EDIT) +
beats.py + design.py. Файл edit.py этой конвенцией не поддерживается.
"""
from __future__ import annotations

from dlstudio.model import Edit

from .beats import BEATS, MIX, ORDER
from .design import DESIGN

EDIT = Edit(
    name="not_a_trolley_problem_2026_07_19_reel_01",
    design=DESIGN,
    beats=BEATS,
    order=ORDER,
    mix=MIX,
    output="data/finalize/video.mp4",
)
