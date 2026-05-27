"""Reel 02: fast hook about sources and reaction signals."""
from devlog.types import Beat, Chunk, Scene


FEED_TOP = "data/screens/real_prod_reel/feed_top_portrait.png"
FEED_SCROLL = "data/screens/real_prod_reel/feed_scroll_portrait.png"
SOURCES = "data/screens/real_prod_reel/sources_portrait.png"


BEATS: dict[str, Beat] = {
    "main": Beat(
        title="Reel 02: ручные события, источники и реакции",
        vo=(
            "Это Neotolis Diary. Сюда я складываю все действия по продвижению игры. "
            "События можно добавлять руками, можно подключить источники. "
            "Я уже подключил YouTube и Reddit, "
            "и новые ролики или посты сами попадают в ленту. "
            "Плюс к ним подтягивается просмотр, лайки, комментарии и ответы."
        ),
        stage="Самостоятельный vertical edit: сначала объяснить продукт, потом источники и реакцию.",
        audio="data/reels/reel02_product_intro_end_audio.wav",
        words="data/reels/reel02_product_intro_end_words.json",
        chunks=[
            Chunk(
                words=(0, 3),
                kind="overlay",
                text="NEOTOLIS DIARY",
                subtitle="ДНЕВНИК ПРОДВИЖЕНИЯ",
                size=255,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=FEED_TOP),
            ),
            Chunk(
                words=(4, 11),
                kind="overlay",
                text="ВСЕ ДЕЙСТВИЯ В ОДНОЙ ЛЕНТЕ",
                subtitle="ПО ПРОДВИЖЕНИЮ ИГРЫ",
                size=245,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=FEED_TOP),
            ),
            Chunk(
                words=(12, 15),
                kind="overlay",
                text="МОЖНО ДОБАВЛЯТЬ РУКАМИ",
                subtitle="ПОСТ · РОЛИК · УПОМИНАНИЕ",
                size=220,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=FEED_TOP),
            ),
            Chunk(
                words=(16, 18),
                kind="overlay",
                text="ИЛИ ПОДКЛЮЧИТЬ ИСТОЧНИКИ",
                subtitle="АВТОМАТОМ",
                size=220,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=SOURCES),
            ),
            Chunk(
                words=(19, 24),
                kind="overlay",
                text="YOUTUBE + REDDIT",
                subtitle="ИСТОЧНИКИ ДАННЫХ",
                size=255,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=SOURCES),
            ),
            Chunk(
                words=(25, 33),
                kind="overlay",
                text="ПОСТЫ САМИ В ЛЕНТУ",
                subtitle="РОЛИКИ И ПОСТЫ",
                size=235,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=FEED_TOP),
            ),
            Chunk(
                words=(34, 41),
                kind="overlay",
                text="СРАЗУ ВИДНО РЕАКЦИЮ",
                subtitle="VIEWS · LIKES · COMMENTS",
                size=235,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=Scene(kind="image", src=FEED_SCROLL),
            ),
            Chunk(
                words=(42, 42),
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
OUTPUT = "data/reels/reel02_sources_reactions_vertical.mp4"
