"""beats.py — биты, чанки и аудио-микс. Дидактический минимум: по одному
примеру на каждый механизм v2 (plate / overlay / image / video / scene /
music / SFX / transition / scratch-VO).

Мастер-часы — word-индексы: Chunk.words=(start, end) указывает в words
JSON бита; compile сам превращает индексы в секунды.

Ассеты ниже ещё не существуют — `dl2 check <edit>` перечислит недостающие
файлы; этот список и есть TODO по ассетам для агента.
"""
from __future__ import annotations

from dlstudio.model import (
    Beat,
    Chunk,
    ImageShot,
    Mix,
    MusicRegion,
    Overlay,
    Plate,
    Scene,
    SfxEvent,
    Transition,
    VideoShot,
)

BEATS = {
    # ── b01: хук ────────────────────────────────────────────────────────
    # Scratch-VO конвенция: `dl2 scratch-tts <edit> b01` синтезирует
    # черновую озвучку из `vo`, `dl2 transcribe` делает word-level JSON;
    # затем агент обновляет пути audio/words ниже на полученные файлы
    # (а после записи реального голоса — на финальные).
    "b01": Beat(
        audio="data/audio/b01_scratch_tts.wav",
        words="data/audio/b01_words.json",
        vo="Привет! Это новый девлог про мою игру: что нового за неделю.",
        # Beat-level scene: фоновое видео под всеми plate/overlay чанками
        # бита (chunk.scene, если задан, перекрывает его).
        scene=Scene(
            kind="video",
            src="data/footage/gameplay_01.mp4",
            asset_id="capture:gameplay_01",
            editorial_role="gameplay",
            expected_state_id="replace-with-game-state-id",
            expected_build_id="exe-sha256:" + "0" * 64,
            expected_action_id="replace-with-visible-action-id",
            offset=5.0,
            loop=False,
        ),
        chunks=[
            # Plate: полноэкранный центрированный текст; transition на
            # чанке — переход ВНУТРЬ чанка.
            Chunk(
                words=(0, 3),
                content=Plate(text="Новый девлог", style="plate.climax"),
                transition=Transition(kind="fade", dur=0.25),
            ),
            # Overlay: текстовая плашка поверх сцены.
            Chunk(
                words=(4, 10),
                content=Overlay(text="Что нового за неделю", variant="band"),
            ),
        ],
        # SFX: one-shot звук, привязанный к word-индексу VO этого бита.
        sfx=[SfxEvent(src="data/sfx/whoosh.wav", word=4, gain_db=-6.0)],
        # Transition на бите: переход в СЛЕДУЮЩИЙ бит (применяет assemble).
        transition_out=Transition(kind="dip_black", dur=0.4),
    ),
    # ── b02: демо ───────────────────────────────────────────────────────
    "b02": Beat(
        audio="data/audio/b02_scratch_tts.wav",
        words="data/audio/b02_words.json",
        vo=(
            "Сначала скриншот новой фичи, потом короткое видео геймплея, "
            "а в конце график роста вишлистов, отрендеренный из HTML шаблона."
        ),
        chunks=[
            # ImageShot: картинка как собственный визуал чанка.
            Chunk(
                words=(0, 3),
                content=ImageShot(src="data/images/screenshot_01.png", ken_burns=True),
            ),
            # VideoShot: видеофрагмент как собственный визуал чанка.
            Chunk(
                words=(4, 7),
                content=VideoShot(
                    src="data/footage/feature_demo.mp4",
                    asset_id="capture:feature_demo",
                    editorial_role="gameplay",
                    expected_state_id="replace-with-game-state-id",
                    expected_build_id="exe-sha256:" + "0" * 64,
                    expected_action_id="replace-with-visible-action-id",
                    offset=5.0,
                ),
            ),
            # Инфографика: MP4, отрендеренный из HTML-исходника
            # (data/hyperframes/) командой `dl2 gen-html` — подключается
            # как обычное видео.
            Chunk(
                words=(8, 17),
                content=VideoShot(
                    src="data/infographics/wishlist_chart.mp4",
                    render_manifest=(
                        "data/infographics/wishlist_chart.mp4.render.json"
                    ),
                    editorial_role="presentation",
                ),
            ),
        ],
    ),
}

ORDER = ["b01", "b02"]

MIX = Mix(
    music=[
        # Музыкальная подложка ПОВЕРХ границ битов; from/to — id битов
        # (включительно), duck=True приглушает её под VO (sidechain).
        MusicRegion(
            src="data/music/theme.mp3",
            from_beat="b01",
            to_beat="b02",
            gain_db=-18.0,
            fade_in=1.0,
            fade_out=1.5,
        ),
    ],
)
