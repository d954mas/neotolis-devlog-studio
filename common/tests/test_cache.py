"""Cache key stability: same beat → same hash, mtime change → new hash."""
import time
from devlog.types import Palette, Fonts, Design, Scene, Chunk, Beat
from devlog.cache import beat_hash, _walk_asset_paths


def _make_beat(audio_path: str, words_path: str):
    return Beat(
        audio=audio_path,
        words=words_path,
        chunks=[Chunk(words=(0, 5), kind="overlay", text="hi")],
    )


def _make_design():
    pal = Palette(bg=(0,0,0), gold=(1,1,1), gold_dim=(2,2,2), red=(3,3,3))
    fonts = Fonts(display="a.ttf", text="b.ttf")
    return Design(resolution=(1920, 1080), fps=30, palette=pal, fonts=fonts)


def test_walk_asset_paths():
    b = Beat(
        audio="a.wav", words="a.json",
        scene=Scene(kind="video", src="bg.mp4"),
        chunks=[
            Chunk(words=(0,5), kind="plate", text="hi", bg_image="plate_bg.png"),
            Chunk(words=(6,10), kind="image", src="img.png"),
            Chunk(words=(11,15), kind="overlay", text="x",
                  scene=Scene(kind="image", src="overlay_bg.png")),
        ],
    )
    paths = set(_walk_asset_paths(b))
    assert "a.wav" in paths
    assert "a.json" in paths
    assert "bg.mp4" in paths
    assert "plate_bg.png" in paths
    assert "img.png" in paths
    assert "overlay_bg.png" in paths


def test_hash_stable_for_same_inputs(tmp_path):
    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00" * 100)
    words = tmp_path / "a.json"; words.write_text("{}")
    b = _make_beat(str(audio), str(words))
    d = _make_design()
    assert beat_hash(b, d) == beat_hash(b, d)


def test_hash_changes_on_mtime(tmp_path):
    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00" * 100)
    words = tmp_path / "a.json"; words.write_text("{}")
    b = _make_beat(str(audio), str(words))
    d = _make_design()
    h1 = beat_hash(b, d)
    time.sleep(0.05)
    audio.write_bytes(b"\x01" * 100)
    assert beat_hash(b, d) != h1


def test_hash_changes_on_design_resolution(tmp_path):
    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00" * 100)
    words = tmp_path / "a.json"; words.write_text("{}")
    b = _make_beat(str(audio), str(words))
    pal = Palette(bg=(0,0,0), gold=(1,1,1), gold_dim=(2,2,2), red=(3,3,3))
    fonts = Fonts(display="a.ttf", text="b.ttf")
    d1 = Design(resolution=(1920, 1080), fps=30, palette=pal, fonts=fonts)
    d2 = Design(resolution=(960, 540), fps=30, palette=pal, fonts=fonts)
    assert beat_hash(b, d1) != beat_hash(b, d2)


def test_hash_changes_on_draft_flag(tmp_path):
    audio = tmp_path / "a.wav"; audio.write_bytes(b"\x00" * 100)
    words = tmp_path / "a.json"; words.write_text("{}")
    b = _make_beat(str(audio), str(words))
    d = _make_design()
    assert beat_hash(b, d, draft=False) != beat_hash(b, d, draft=True)
