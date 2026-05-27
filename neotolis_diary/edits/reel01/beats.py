"""Reel 01: fast hook about why the diary exists."""
from devlog.types import Beat, Chunk, Scene


FEED_TOP = "data/screens/real_prod_reel/feed_top_portrait.png"
FEED_SCROLL = "data/screens/real_prod_reel/feed_scroll_portrait.png"
ADD_EVENT = "data/screens/real_prod_reel/add_event_portrait.png"


BEATS: dict[str, Beat] = {
    "main": Beat(
        title="Reel 01: коротко о проблеме и дневнике",
        vo=(
            "Да, продвигаешь игру, легко обмануться. Вроде я что-то делал. "
            "А через неделю уже не помнишь, что именно, сколько раз и был ли от этого эффект. "
            "Поэтому я сделал маленький дневник продвижения для игры. "
            "Это Neotolis Diary. Сюда я складываю все действия по продвижению игры."
        ),
        stage="Плотный vertical edit: боль, забывание, решение, реальная лента.",
        audio="data/reels/reel01_fast_end_audio.wav",
        words="data/reels/reel01_fast_end_words.json",
        chunks=[
            Chunk(
                words=(0, 4),
                kind="overlay",
                text="ЛЕГКО ОБМАНУТЬСЯ",
                subtitle="ПРОДВИГАЕШЬ ИГРУ",
                size=245,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=FEED_TOP),
            ),
            Chunk(
                words=(5, 9),
                kind="overlay",
                text="ВРОДЕ ЧТО-ТО ДЕЛАЛ",
                subtitle="НО ЧТО СРАБОТАЛО?",
                size=250,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=ADD_EVENT),
            ),
            Chunk(
                words=(10, 17),
                kind="overlay",
                text="ЧЕРЕЗ НЕДЕЛЮ НЕ ПОМНИШЬ",
                subtitle="ЧТО ИМЕННО?",
                size=220,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=FEED_SCROLL),
            ),
            Chunk(
                words=(18, 31),
                kind="overlay",
                text="ДНЕВНИК ВМЕСТО ПАМЯТИ",
                subtitle="НЕ GOOGLE SHEETS",
                size=235,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=FEED_TOP),
            ),
            Chunk(
                words=(32, 35),
                kind="overlay",
                text="NEOTOLIS DIARY",
                subtitle="РЕАЛЬНЫЙ САЙТ",
                size=255,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=ADD_EVENT),
            ),
            Chunk(
                words=(36, 43),
                kind="overlay",
                text="NEOTOLIS-DIARY.DEV",
                subtitle="ДНЕВНИК ДЛЯ ИГРЫ",
                size=245,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=FEED_TOP),
            ),
        ],
        face="none",
    ),
}

CONCAT_ORDER: list[str] = ["main"]
OUTPUT = "data/reels/reel01_problem_diary_vertical.mp4"
