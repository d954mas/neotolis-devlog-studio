"""Reel 01: a simple no-code game hook for a broad audience."""
from devlog.types import Beat, Chunk, Scene


def video(src: str, offset: float = 0.0, loop: bool = False) -> Scene:
    return Scene(kind="video", src=src, offset=offset, loop=loop)


BEATS: dict[str, Beat] = {
    "hook": Beat(
        title="Reel 30k: hook",
        vo="Ни одной строчки кода в этой игре я не написал сам.",
        stage="Открыть с прямого контраста: игра есть, ручного кода нет.",
        audio="data/reels/reel_no_code_hook_fast_audio.wav",
        words="data/reels/reel_no_code_hook_fast_words.json",
        scene=video("data/trailer/trailer_vertical_final.mp4", offset=1.0, loop=True),
        chunks=[
            Chunk(
                words=(0, 3),
                kind="overlay",
                text="ИГРА ПРО ТРАМВАЙ",
                subtitle="НАПИСАЛ РУКАМИ: 0",
                size=225,
                sub_ratio=0.58,
                line_gap_ratio=0.08,
                position="bottom",
                style="band",
            ),
            Chunk(
                words=(4, 10),
                kind="overlay",
                text="Я НЕ ПИСАЛ КОД",
                subtitle="NOT A TROLLEY PROBLEM",
                size=245,
                sub_ratio=0.58,
                position="bottom",
                style="band",
            ),
        ],
        face="none",
    ),
    "ai_tail": Beat(
        title="Reel no-code: AI made it",
        vo="И всё это написал ИИ. Я говорил, что делать, Клод делал.",
        stage="Максимально простое объяснение: не цифры, а кто реально делал.",
        audio="data/reels/reel_no_code_ai_tail_fast_audio.wav",
        words="data/reels/reel_no_code_ai_tail_fast_words.json",
        chunks=[
            Chunk(
                words=(0, 4),
                kind="overlay",
                text="ИИ СОБРАЛ ИГРУ",
                subtitle="Я ДАВАЛ ИДЕЮ",
                size=250,
                sub_ratio=0.58,
                position="bottom",
                style="band",
                scene=video("data/reels/visuals/ai_made_it_energy.mp4", loop=True),
            ),
            Chunk(
                words=(5, 10),
                kind="overlay",
                text="ТЫ БЫ ТАК СДЕЛАЛ?",
                subtitle="Я РУЛИЛ — ИИ ДЕЛАЛ",
                size=220,
                sub_ratio=0.58,
                line_gap_ratio=0.06,
                position="bottom",
                style="band",
                scene=video("data/reels/visuals/ai_made_it_energy.mp4", offset=2.8, loop=True),
            ),
        ],
        face="none",
    ),
}


CONCAT_ORDER: list[str] = ["hook", "ai_tail"]
OUTPUT = "data/reels/reel_no_code_game_vertical.mp4"
