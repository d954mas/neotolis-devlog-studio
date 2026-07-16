"""2026-06-03 reel: wishlist graphs and promotion signals."""
from devlog.types import Beat, Chunk, Scene


FEED_TOP = "data/screens/real_prod_reel/feed_top_portrait.png"
DASHBOARD = "data/infographics/reel_20260603_wishlist_graphs_dashboard_overview.png"
CHART_FOCUS = "data/infographics/reel_20260603_wishlist_graphs_dashboard_chart_focus.png"
WISHLIST_GROWTH = "data/infographics/reel_20260603_wishlist_graphs_growth.mp4"
HERO_MOTION = "data/infographics/reel_20260603_wishlist_graphs_hero.mp4"
DASHBOARD_MOTION = "data/infographics/reel_20260603_wishlist_graphs_dashboard_motion.mp4"
GROWTH_MOTION = "data/infographics/reel_20260603_wishlist_graphs_growth_motion.mp4"
CHAIN_MOTION = "data/infographics/reel_20260603_wishlist_graphs_chain_motion.mp4"
OUTRO_MOTION = "data/infographics/reel_20260603_wishlist_graphs_outro_motion.mp4"
SMOOTH_SCROLL = "data/infographics/reel_20260603_wishlist_graphs_light_smooth_scroll.mp4"


def moving_shot(src: str, zoom: float = 0.08) -> Scene:
    return Scene(kind="image", src=src, ken_burns=True, kb_zoom=zoom)


def motion_clip(src: str) -> Scene:
    return Scene(kind="video", src=src, loop=True)


BEATS: dict[str, Beat] = {
    "main": Beat(
        scene=motion_clip(SMOOTH_SCROLL),
        title="Reel 2026-06-03: prod wishlist graphs",
        vo=(
            "Neotolis Diary теперь показывает не только действия, но и результат. "
            "Я добавил страницу игры с графиками: как меняются вишлисты, какие события были рядом, "
            "и где продвижение дало сигнал. Теперь можно смотреть: вот активность, вот реакция, вот рост. "
            "Не вспоминать всё в голове, а видеть это на одной странице."
        ),
        stage="Черновик без финальной озвучки: тестовый SAPI VO нужен только для тайминга визуала.",
        audio="data/reels/reel_20260603_wishlist_graphs_scratch_audio.wav",
        words="data/reels/reel_20260603_wishlist_graphs_scratch_words.json",
        chunks=[
            Chunk(
                words=(0, 47),
                kind="overlay",
                text="",
                subtitle=None,
                size=120,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
                scene=motion_clip(SMOOTH_SCROLL),
            ),
        ],
        face="none",
    ),
}

CONCAT_ORDER: list[str] = ["main"]
OUTPUT = "data/reels/reel_20260603_wishlist_graphs_light_vertical.mp4"
