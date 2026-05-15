"""xfade chain offset math tests — covers the bug where I had offset=
cumulative-crossfade (wrong, scenes started 0.6s early) vs offset=cumulative
(correct, scenes start at their slot in output time)."""
from devlog.types import Palette, Fonts, Design
from devlog.render.compose_ffmpeg import _chain_xfade


def _design(W=1920, H=1080):
    pal = Palette(bg=(0,0,0), gold=(1,1,1), gold_dim=(2,2,2), red=(3,3,3))
    fonts = Fonts(display="a.ttf", text="b.ttf")
    return Design(resolution=(W,H), fps=30, palette=pal, fonts=fonts)


def test_single_scene_no_xfade():
    """One scene = no chain needed. Returns empty string and that label."""
    s, label = _chain_xfade(["s0"], [10.0], 0.6, _design())
    assert s == ""
    assert label == "s0"


def test_two_scenes_one_xfade():
    """Two scenes = one xfade. Offset = seg_durs[0] (output time where
    transition begins) — not seg_durs[0] - crossfade_dur (old bug)."""
    s, label = _chain_xfade(["s0", "s1"], [5.0, 4.0], 0.6, _design())
    assert "xfade=transition=fade:duration=0.600:offset=5.000" in s
    assert "[s0][s1]" in s
    assert label == "xf1"


def test_three_scenes_two_xfades_cumulative_offsets():
    """Each xfade's offset is the sum of all PRIOR seg_durs.
    For [5, 4, 6]: xfade1 offset=5, xfade2 offset=9 (5+4)."""
    s, label = _chain_xfade(["s0", "s1", "s2"], [5.0, 4.0, 6.0], 0.6, _design())
    assert "offset=5.000" in s
    assert "offset=9.000" in s
    # Chain: s0 → xf1 → xf2 (final)
    assert "[s0][s1]" in s
    assert "[xf1][s2]" in s
    assert label == "xf2"


def test_nine_scenes_eight_xfades_offsets_monotonic():
    """Reality check from b3 (9 scenes). Offsets should be strictly increasing
    and equal to running sums."""
    durs = [3.0, 4.0, 5.0, 3.5, 2.5, 4.0, 3.0, 4.5, 2.0]
    s, label = _chain_xfade([f"s{i}" for i in range(9)], durs, 0.6, _design())
    # Final label after 8 xfades
    assert label == "xf8"
    # All 8 offsets are present
    expected_offsets = [3.0, 7.0, 12.0, 15.5, 18.0, 22.0, 25.0, 29.5]
    for off in expected_offsets:
        assert f"offset={off:.3f}" in s, f"missing offset={off}"


def test_zero_crossfade_dur():
    """Crossfade duration 0 still works (hard cut via xfade duration=0)."""
    s, label = _chain_xfade(["s0", "s1"], [5.0, 4.0], 0.0, _design())
    assert "duration=0.000" in s
    assert label == "xf1"


def test_gap_pad_as_first_scene():
    """When a 'gap0' color pad is the first scene, it behaves like any other.
    This is the finale fix case (chunk 0 plate before first real scene)."""
    s, label = _chain_xfade(["gap0", "s1"], [3.5, 25.0], 0.6, _design())
    # xfade transitions FROM gap0 TO s1 at output t=3.5 (when plate dismisses)
    assert "[gap0][s1]xfade" in s
    assert "offset=3.500" in s
