"""Silent-first reel: nominal 30 fps capture versus a smooth re-capture."""
from __future__ import annotations

from dlstudio.model import Beat, Chunk, Mix, MusicRegion, Transition, VideoShot


BEATS = {
    "b01": Beat(
        title="30 FPS только на бумаге",
        vo="",
        stage=(
            "Немой рилс: три коротких сообщения встроены в HyperFrames; "
            "silence.wav и words.json служат только носителями тайминга."
        ),
        audio="data/audio/silence.wav",
        words="data/scratch/words.json",
        subtitles=False,
        chunks=[
            Chunk(
                words=(0, 2),
                content=VideoShot(src="data/infographics/temporal_before_after.mp4"),
            )
        ],
        transition_out=Transition(kind="cut", dur=0.0),
    )
}

ORDER = ["b01"]

MIX = Mix(
    music=[
        MusicRegion(
            src="data/music/first_day_in_a_loop.ogg",
            from_beat="b01",
            to_beat="b01",
            offset=22.0,
            gain_db=-11.0,
            fade_in=0.25,
            fade_out=0.7,
            duck=False,
        )
    ],
    target_lufs=-14.0,
    true_peak_db=-1.0,
)
