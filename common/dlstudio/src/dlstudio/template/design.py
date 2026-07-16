"""design.py — разрешение, fps, палитра, шрифты и именованные стили текста.

Ориентация ролика задаётся ТОЛЬКО кортежем RESOLUTION (поля `format` в
модели нет): `dl2 new-video --format vertical` переписывает строку ниже
на (1080, 1920). Размеры стилей заданы для ширины 1920 — Design.px()
масштабирует их под фактическое разрешение автоматически.
"""
from __future__ import annotations

from dlstudio.model import Design, Fonts, Palette, TextStyle

RESOLUTION = (1920, 1080)

DESIGN = Design(
    resolution=RESOLUTION,
    fps=30,
    palette=Palette(tokens={
        "bg": "#101014",        # фон
        "text": "#ffffff",      # основной текст
        "accent": "#ff3355",    # акцент (climax-плейты, подчёркивания)
    }),
    # Положи реальный TTF в data/fonts/main.ttf — пока файла нет,
    # `dl2 check` покажет это ошибкой (это нормально для свежего проекта).
    fonts=Fonts(main="data/fonts/main.ttf"),
    styles={
        "plate.default": TextStyle(size=200),
        "plate.climax": TextStyle(size=280, color="accent", caps=True),
        "overlay.default": TextStyle(size=110),
    },
)
