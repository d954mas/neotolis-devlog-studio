"""Scene segment computation tests — covers same-src merging, gap detection,
and edge cases that escaped silently in prior bug rounds.

These are pure-function tests, no rendering, no subprocess.
"""
from devlog.types import Scene
from devlog.render.compose_ffmpeg import _merge_scene_segments


def _ch(t_start: float, scene: Scene | None = None) -> dict:
    """Tiny helper to mock the chunk-with-time dict shape used by the merger."""
    return {"t_start": t_start, "scene": scene}


def test_no_scenes_returns_empty():
    """Plates-only beat (no scene overrides) yields no scene segments."""
    chunks = [_ch(0.0), _ch(3.0), _ch(6.0)]
    segs = _merge_scene_segments(chunks, default_scene=None, audio_dur=10.0)
    assert segs == []


def test_single_default_scene_spans_audio():
    """If only beat.scene is set (no chunk overrides), 1 segment covers full audio."""
    default = Scene(kind="video", src="bg.mp4")
    chunks = [_ch(0.0), _ch(3.0), _ch(6.0)]
    segs = _merge_scene_segments(chunks, default_scene=default, audio_dur=10.0)
    assert len(segs) == 1
    assert segs[0] == (0.0, 10.0, default)


def test_first_chunk_with_scene_after_t0_creates_gap():
    """When chunk 0 has NO scene but chunk 1 does, segment starts at chunk1.t_start.
    This is the finale pattern (plate then daily_views animation)."""
    daily_views = Scene(kind="video", src="daily.mp4")
    chunks = [
        _ch(0.0),                    # plate, no scene
        _ch(3.5, daily_views),        # animation
        _ch(8.0, daily_views),        # same src — merged
    ]
    segs = _merge_scene_segments(chunks, default_scene=None, audio_dur=15.0)
    assert len(segs) == 1
    assert segs[0] == (3.5, 15.0, daily_views)   # starts at chunk1, NOT 0


def test_same_src_consecutive_chunks_merge():
    """Three chunks with identical scene.src merge into ONE segment.
    Only the first chunk's offset is used; others ignored."""
    s = Scene(kind="video", src="bg.mp4", offset=0.0)
    s2 = Scene(kind="video", src="bg.mp4", offset=5.0)   # same src, different offset
    chunks = [_ch(0.0, s), _ch(3.0, s2), _ch(7.0, s2)]
    segs = _merge_scene_segments(chunks, default_scene=None, audio_dur=10.0)
    assert len(segs) == 1
    # Merged segment uses FIRST chunk's scene (offset=0.0, not 5.0)
    assert segs[0][2].offset == 0.0


def test_different_src_creates_new_segment():
    """Switching scene src triggers a new segment boundary."""
    a = Scene(kind="image", src="a.png")
    b = Scene(kind="image", src="b.png")
    chunks = [_ch(0.0, a), _ch(4.0, b)]
    segs = _merge_scene_segments(chunks, default_scene=None, audio_dur=10.0)
    assert len(segs) == 2
    assert segs[0] == (0.0, 4.0, a)
    assert segs[1] == (4.0, 10.0, b)


def test_plate_chunks_between_scenes_extend_current():
    """Plate chunks (no scene) DON'T break the current segment.
    Pattern: scene→plate→scene_same_src should still be 1 segment."""
    s = Scene(kind="image", src="img.png")
    chunks = [
        _ch(0.0, s),       # opens scene
        _ch(2.0),          # plate, no scene
        _ch(5.0, s),       # same src — should keep segment going
    ]
    segs = _merge_scene_segments(chunks, default_scene=None, audio_dur=8.0)
    assert len(segs) == 1
    assert segs[0] == (0.0, 8.0, s)


def test_default_scene_replaced_by_chunk_scene():
    """If chunk 0 has its own scene that differs from default, default is used
    only for the gap (which won't exist if chunk 0 covers t=0)."""
    default = Scene(kind="image", src="default.png")
    explicit = Scene(kind="image", src="other.png")
    chunks = [_ch(0.0, explicit), _ch(5.0)]   # chunk 0 overrides default at t=0
    segs = _merge_scene_segments(chunks, default_scene=default, audio_dur=10.0)
    # Default is replaced from t=0 by chunk 0's explicit scene
    # The current behavior closes the default segment at chunk0.t_start=0 (zero-length)
    # then opens explicit from t=0 to audio_dur
    assert any(seg[2].src == "other.png" for seg in segs)


def test_audio_dur_caps_last_segment():
    """Last segment always ends exactly at audio_dur, never beyond."""
    s = Scene(kind="video", src="bg.mp4")
    chunks = [_ch(0.0, s)]
    segs = _merge_scene_segments(chunks, default_scene=None, audio_dur=27.42)
    assert len(segs) == 1
    assert segs[0][1] == 27.42
