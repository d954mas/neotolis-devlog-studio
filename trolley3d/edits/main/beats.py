"""beats.py — рилс: возвращение к Not a Trolley Problem (3D, свой движок).

Без голоса: немые VO-дорожки держат тайминги, текст — явные Overlay-карточки
(ровно 2 строки, фиксированная позиция), музыка без дакинга.

b01  канвас: рефы + мудборд-генерации (реальная запись браузера)
b02  первый человечек ходит в движке (реальный движковый захват)
b03  толпа + трамвай в движке, финальный титул
"""
from __future__ import annotations

from dlstudio.model import (
    Beat,
    Chunk,
    Mix,
    MusicRegion,
    Overlay,
    Plate,
    Scene,
    Transition,
)

BEATS = {
    # ── b01: хук + канвас ───────────────────────────────────────────────
    "b01": Beat(
        audio="data/scratch/b01_scratch_tts.wav",
        words="data/scratch/b01_words.json",
        vo=(
            "Not a Trolley Problem переезжает в 3D — на движок, "
            "который я пишу сам. Начал со стиля: рефы и мудборд."
        ),
        scene=Scene(kind="video", src="data/footage/canvas_beat.mp4"),
        chunks=[
            Chunk(
                words=(0, 5),
                content=Overlay(
                    text="Вернулся к Not a Trolley Problem",
                    variant="band",
                    position="bottom",
                    y_ratio=0.73,
                    style="overlay.title",
                ),
                transition=Transition(kind="fade", dur=0.2),
            ),
            Chunk(
                words=(6, 11),
                transition=Transition(kind="fade", dur=0.25),
                content=Overlay(
                    text="В 3д, на своем движке",
                    variant="band",
                    position="bottom",
                    y_ratio=0.73,
                    style="overlay.title",
                ),
            ),
            Chunk(
                words=(12, 17),
                transition=Transition(kind="fade", dur=0.25),
                content=Overlay(
                    text="Начал с поиска рефов и стиля",
                    variant="band",
                    position="bottom",
                    y_ratio=0.73,
                    style="overlay.title",
                ),
            ),
        ],
        transition_out=Transition(kind="dip_black", dur=0.3),
    ),
    # ── b02: первый человечек ───────────────────────────────────────────
    "b02": Beat(
        audio="data/scratch/b02_scratch_tts.wav",
        words="data/scratch/b02_words.json",
        vo="Первый житель уже ходит в движке.",
        scene=Scene(kind="video", src="data/footage/walker_v.mp4"),
        chunks=[
            Chunk(
                words=(0, 5),
                content=Overlay(
                    text="Первый вариант человечка",
                    variant="band",
                    position="bottom",
                    y_ratio=0.73,
                    style="overlay.title",
                ),
                pad_after=0.9,
            ),
        ],
        transition_out=Transition(kind="fade", dur=0.25),
    ),
    # ── b03: толпа + трамвай, финал ─────────────────────────────────────
    "b03": Beat(
        audio="data/scratch/b03_scratch_tts.wav",
        words="data/scratch/b03_words.json",
        vo="А за ним — четыреста человечков и трамвай. Дальше — больше.",
        chunks=[
            Chunk(
                words=(0, 6),
                content=Overlay(
                    text="Будет много людей",
                    variant="band",
                    position="bottom",
                    y_ratio=0.73,
                    style="overlay.title",
                ),
                scene=Scene(kind="video", src="data/footage/game_v.mp4"),
            ),
            Chunk(
                words=(7, 8),
                content=Plate(text="Not a Trolley Problem", style="plate.title"),
                transition=Transition(kind="fade", dur=0.25),
                pad_after=1.0,
            ),
        ],
    ),
}

ORDER = ["b01", "b02", "b03"]

MIX = Mix(
    music=[
        MusicRegion(
            src="data/music/groove_grove.mp3",
            from_beat="b01",
            to_beat="b03",
            gain_db=-10.0,
            duck=False,
            fade_in=0.6,
            fade_out=1.8,
        ),
    ],
)
