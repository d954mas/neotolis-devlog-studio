"""Background-segment building: same-source merge matrix (mirrors legacy
common/tests/test_scene_merge.py), ImageShot/VideoShot-as-segment, xfade
transitions, and the offset-past-EOF clamp.

build_segments takes explicit tiling windows so these mirror the legacy
_ch(t_start) fixtures directly.
"""
from __future__ import annotations

from _builders import mk_design, probe
from dlstudio.compile.segments import build_segments
from dlstudio.model import Chunk, Scene
from dlstudio.model.content import ImageShot, Plate, Transition, VideoShot

D = mk_design()


def _pl(scene=None, transition=None):
    return Chunk(words=(0, 0), content=Plate(text="x"), scene=scene,
                 transition=transition)


# ── legacy scene-merge matrix ────────────────────────────────────────────────

def test_no_scenes_returns_empty():
    chunks = [_pl(), _pl(), _pl()]
    wins = [(0.0, 3.0), (3.0, 6.0), (6.0, 10.0)]
    segs, warns, _diags = build_segments(chunks, wins, None, 10.0, D, {})
    assert segs == []
    assert warns == []


def test_single_default_scene_spans_audio():
    default = Scene(kind="video", src="bg.mp4")
    chunks = [_pl(), _pl(), _pl()]
    wins = [(0.0, 3.0), (3.0, 6.0), (6.0, 10.0)]
    segs, _, _diags = build_segments(chunks, wins, default, 10.0, D, {})
    assert len(segs) == 1
    assert (segs[0].src, segs[0].t0, segs[0].t1) == ("bg.mp4", 0.0, 10.0)


def test_first_chunk_with_scene_after_t0_creates_gap():
    daily = Scene(kind="video", src="daily.mp4")
    chunks = [_pl(), _pl(daily), _pl(daily)]
    wins = [(0.0, 3.5), (3.5, 8.0), (8.0, 15.0)]
    segs, _, _diags = build_segments(chunks, wins, None, 15.0, D, {})
    assert len(segs) == 1
    assert (segs[0].src, segs[0].t0, segs[0].t1) == ("daily.mp4", 3.5, 15.0)


def test_same_src_consecutive_chunks_merge_first_offset_wins():
    s = Scene(kind="video", src="bg.mp4", offset=0.0)
    s2 = Scene(kind="video", src="bg.mp4", offset=5.0)
    chunks = [_pl(s), _pl(s2), _pl(s2)]
    wins = [(0.0, 3.0), (3.0, 7.0), (7.0, 10.0)]
    segs, _, _diags = build_segments(chunks, wins, None, 10.0, D, {})
    assert len(segs) == 1
    assert segs[0].offset == 0.0        # first chunk's offset, later ignored


def test_different_src_creates_new_segment():
    a = Scene(kind="image", src="a.png")
    b = Scene(kind="image", src="b.png")
    chunks = [_pl(a), _pl(b)]
    wins = [(0.0, 4.0), (4.0, 10.0)]
    segs, _, _diags = build_segments(chunks, wins, None, 10.0, D, {})
    assert len(segs) == 2
    assert (segs[0].src, segs[0].t0, segs[0].t1) == ("a.png", 0.0, 4.0)
    assert (segs[1].src, segs[1].t0, segs[1].t1) == ("b.png", 4.0, 10.0)


def test_plate_chunks_between_scenes_extend_current():
    s = Scene(kind="image", src="img.png")
    chunks = [_pl(s), _pl(), _pl(s)]
    wins = [(0.0, 2.0), (2.0, 5.0), (5.0, 8.0)]
    segs, _, _diags = build_segments(chunks, wins, None, 8.0, D, {})
    assert len(segs) == 1
    assert (segs[0].src, segs[0].t0, segs[0].t1) == ("img.png", 0.0, 8.0)


def test_default_scene_replaced_by_chunk_scene():
    default = Scene(kind="image", src="default.png")
    explicit = Scene(kind="image", src="other.png")
    chunks = [_pl(explicit), _pl()]
    wins = [(0.0, 5.0), (5.0, 10.0)]
    segs, _, _diags = build_segments(chunks, wins, default, 10.0, D, {})
    assert any(s.src == "other.png" for s in segs)
    assert all(s.src != "default.png" for s in segs)


def test_audio_dur_caps_last_segment():
    s = Scene(kind="video", src="bg.mp4")
    chunks = [_pl(s)]
    wins = [(0.0, 27.42)]
    segs, _, _diags = build_segments(chunks, wins, None, 27.42, D, {})
    assert len(segs) == 1
    assert segs[0].t1 == 27.42


# ── ImageShot / VideoShot content as its own segment ─────────────────────────

def test_imageshot_content_is_its_own_segment():
    chunks = [
        _pl(Scene(kind="video", src="bg.mp4")),
        Chunk(words=(0, 0), content=ImageShot(src="photo.png", ken_burns=True)),
        _pl(),   # reverts to inherited scene bg.mp4
    ]
    wins = [(0.0, 2.0), (2.0, 4.0), (4.0, 6.0)]
    segs, _, _diags = build_segments(chunks, wins, Scene(kind="video", src="bg.mp4"),
                             6.0, D, {})
    assert [s.src for s in segs] == ["bg.mp4", "photo.png", "bg.mp4"]
    photo = segs[1]
    assert photo.kind == "image" and photo.ken_burns is True
    assert (photo.t0, photo.t1) == (2.0, 4.0)


def test_videoshot_content_is_video_segment():
    chunks = [Chunk(words=(0, 0), content=VideoShot(src="clip.mp4", offset=3.0))]
    wins = [(0.0, 5.0)]
    segs, _, _diags = build_segments(chunks, wins, None, 5.0, D, {})
    assert len(segs) == 1
    assert (segs[0].kind, segs[0].src, segs[0].offset) == ("video", "clip.mp4", 3.0)


# ── crossfade transitions between segments ───────────────────────────────────

def test_segment_boundaries_get_default_crossfade():
    a = Scene(kind="image", src="a.png")
    b = Scene(kind="image", src="b.png")
    segs, _, _diags = build_segments([_pl(a), _pl(b)], [(0.0, 4.0), (4.0, 10.0)],
                             None, 10.0, D, {})
    assert segs[0].xfade is not None
    assert segs[0].xfade.kind == "fade"
    assert segs[0].xfade.dur == D.crossfade_dur
    assert segs[1].xfade is None        # last segment: no outgoing xfade


def test_chunk_transition_overrides_segment_xfade():
    a = Scene(kind="image", src="a.png")
    b = Scene(kind="image", src="b.png")
    # transition on the chunk that OPENS the next segment wins
    chunks = [_pl(a), _pl(b, transition=Transition(kind="dip_black", dur=0.5))]
    segs, _, _diags = build_segments(chunks, [(0.0, 4.0), (4.0, 10.0)], None, 10.0, D, {})
    assert segs[0].xfade.kind == "dip_black"
    assert segs[0].xfade.dur == 0.5


# ── offset-past-EOF clamp (VQ-OFFSET) ────────────────────────────────────────

def test_video_offset_past_eof_clamped_with_warning():
    scene = Scene(kind="video", src="short.mp4", offset=20.0)
    assets = {"short.mp4": probe("short.mp4", "video", duration=8.0,
                                 width=1080, height=1920)}
    # window length 3.0 -> clamp offset to max(0, 8.0 - 3.0) = 5.0
    segs, warns, diags = build_segments([_pl(scene)], [(0.0, 3.0)], None, 3.0, D, assets)
    assert segs[0].offset == 5.0
    assert len(warns) == 1
    assert warns[0].startswith("VQ-OFFSET:")
    assert "short.mp4" in warns[0]
    # structured CheckIssue mirrors the string (compile/check migration):
    # severity=warn, code=VQ-OFFSET, `where` left blank here -- the caller
    # (_compile_beat) fills it in with the beat id.
    assert len(diags) == 1
    assert diags[0].severity == "warn" and diags[0].code == "VQ-OFFSET"
    assert diags[0].where == ""
    assert "short.mp4" in diags[0].message


def test_video_offset_clamped_to_zero_floor_when_window_longer_than_source():
    scene = Scene(kind="video", src="short.mp4", offset=20.0)
    assets = {"short.mp4": probe("short.mp4", "video", duration=4.0,
                                 width=1080, height=1920)}
    # window 10s longer than source 4s -> max(0, 4-10)=0
    segs, warns, _diags = build_segments([_pl(scene)], [(0.0, 10.0)], None, 10.0, D, assets)
    assert segs[0].offset == 0.0
    assert len(warns) == 1


def test_video_offset_within_source_no_warning():
    scene = Scene(kind="video", src="ok.mp4", offset=2.0)
    assets = {"ok.mp4": probe("ok.mp4", "video", duration=30.0,
                              width=1080, height=1920)}
    segs, warns, _diags = build_segments([_pl(scene)], [(0.0, 5.0)], None, 5.0, D, assets)
    assert segs[0].offset == 2.0
    assert warns == []


def test_image_offset_never_clamped():
    # images have no duration -> EOF logic skipped entirely
    scene = Scene(kind="image", src="pic.png", offset=99.0)
    assets = {"pic.png": probe("pic.png", "image", width=1080, height=1920)}
    segs, warns, _diags = build_segments([_pl(scene)], [(0.0, 5.0)], None, 5.0, D, assets)
    assert warns == []
