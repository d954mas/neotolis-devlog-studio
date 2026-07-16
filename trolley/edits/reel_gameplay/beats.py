"""Reel 02: what the Trolley game actually became after 13 days."""
from devlog.types import Beat, Chunk, Scene


def video(src: str, offset: float = 0.0, loop: bool = False) -> Scene:
    return Scene(kind="video", src=src, offset=offset, loop=loop)


def image(src: str, zoom: float = 0.08) -> Scene:
    return Scene(kind="image", src=src, ken_burns=True, kb_zoom=zoom)


BEATS: dict[str, Beat] = {
    "main": Beat(
        title="Reel gameplay: contextual feature reel",
        vo=(
            "За тринадцать дней — вот что получилось. Липкий палец — ядро механики. "
            "Пять миров, в каждом свой босс. Прокачиваешь ранг — можешь сделать "
            "трамвайный выбор. Например: кот Шредингера или учёный. Мимы или клоуны. "
            "Десять таких карточек. Апгрейд-дерево — пятьдесят девять нод. "
            "Полное прохождение — пятнадцать-двадцать минут."
        ),
        stage="Быстрый feature barrage: каждый факт получает новый визуальный удар.",
        audio="data/reels/reel_gameplay_cut_audio.wav",
        words="data/reels/reel_gameplay_cut_words.json",
        scene=video("data/trailer/trailer_vertical_final.mp4", offset=1.0, loop=True),
        chunks=[
            Chunk(
                words=(0, 5),
                kind="overlay",
                text="ИГРА ПРО ТРАМВАЙ",
                subtitle="NOT A TROLLEY PROBLEM · 13 ДНЕЙ",
                size=230,
                sub_ratio=0.50,
                line_gap_ratio=0.05,
                position="bottom",
                style="band",
            ),
            Chunk(
                words=(6, 10),
                kind="overlay",
                text="ЛИПКИЙ ПАЛЕЦ",
                subtitle="ЯДРО МЕХАНИКИ",
                size=245,
                sub_ratio=0.58,
                position="bottom",
                style="band",
                scene=video("data/itch/sticky_finger_gameplay.mp4", offset=0.4, loop=True),
            ),
            Chunk(
                words=(11, 17),
                kind="overlay",
                text="ТРАМВАЙНЫЙ ВЫБОР",
                subtitle="КАЖДЫЙ ЗАБЕГ НОВЫЙ",
                size=232,
                sub_ratio=0.56,
                line_gap_ratio=0.06,
                position="middle",
                style="card",
                scene=video("data/reels/visuals/choices_energy.mp4", loop=True),
            ),
            Chunk(
                words=(18, 22),
                kind="overlay",
                text="КОТ ШРЁДИНГЕРА?",
                subtitle="ИЛИ УЧЁНЫЙ · АБСУРДНЫЕ ДИЛЕММЫ",
                size=225,
                sub_ratio=0.54,
                line_gap_ratio=0.07,
                position="bottom",
                style="band",
                scene=video("data/itch/choice_schrodinger.mp4", offset=7.0, loop=True),
            ),
            Chunk(
                words=(23, 28),
                kind="overlay",
                text="МИМЫ ИЛИ КЛОУНЫ?",
                subtitle="10 КАРТОЧЕК ВЫБОРА",
                size=225,
                sub_ratio=0.54,
                line_gap_ratio=0.06,
                position="bottom",
                style="band",
                scene=video("data/itch/choice_mimes.mp4", offset=3.5, loop=True),
            ),
            Chunk(
                words=(29, 33),
                kind="overlay",
                text="59 АПГРЕЙДОВ",
                size=248,
                subtitle="ДЕРЕВО ПРОКАЧКИ",
                sub_ratio=0.52,
                position="bottom",
                style="band",
                scene=video("data/reels/visuals/upgrade_energy.mp4", loop=True),
            ),
            Chunk(
                words=(34, 39),
                kind="overlay",
                text="СЫГРАЛ БЫ?",
                subtitle="15-20 МИНУТ · NOT A TROLLEY PROBLEM",
                size=255,
                sub_ratio=0.44,
                position="middle",
                style="hero",
                scene=video("data/trailer/trailer_vertical_final.mp4", offset=13.2),
            ),
        ],
        face="none",
    ),
}


CONCAT_ORDER: list[str] = ["main"]
OUTPUT = "data/reels/reel_gameplay_features_vertical.mp4"
