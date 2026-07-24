"""Unit tests for the typed filter-graph AST, escaping, the input-args matrix
and the xfade offset math (ports of the legacy v1 test matrices)."""
from __future__ import annotations

import pytest

from dlstudio.render.graph import (
    Chain,
    FilterNode,
    Graph,
    InputList,
    build_xfade_chain,
    color_source,
    format_arg,
    scene_input_args,
    xfade_offsets,
)


# ─── FilterNode / Chain string generation ──────────────────────────────────

def test_filternode_positional_and_named():
    n = FilterNode("scale", args={"force_original_aspect_ratio": "increase"},
                   positional=[1920, 1080])
    assert n.render_filter() == "scale=1920:1080:force_original_aspect_ratio=increase"


def test_filternode_with_pads():
    n = FilterNode("xfade", args={"transition": "fade", "duration": 0.6,
                                  "offset": 5.0},
                   inputs=["s0", "s1"], outputs=["xf1"])
    assert n.render() == "[s0][s1]xfade=transition=fade:duration=0.600:offset=5.000[xf1]"


def test_filternode_bare_no_args():
    assert FilterNode("null").render_filter() == "null"


def test_chain_comma_joins_filters_with_end_pads():
    c = Chain(
        inputs=["1:v"],
        filters=[
            FilterNode("scale", positional=[320, 180],
                       args={"force_original_aspect_ratio": "increase"}),
            FilterNode("crop", positional=[320, 180]),
            FilterNode("format", positional=["yuv420p"]),
        ],
        outputs=["s0"],
    )
    assert c.render() == (
        "[1:v]scale=320:180:force_original_aspect_ratio=increase,"
        "crop=320:180,format=yuv420p[s0]"
    )


def test_bool_and_float_and_int_formatting():
    assert format_arg(True) == "1"
    assert format_arg(False) == "0"
    assert format_arg(0.6) == "0.600"
    assert format_arg(30) == "30"
    assert format_arg(-0.0) == "0.000"


# ─── arg escaping (colons/commas/paths) ────────────────────────────────────

def test_escape_plain_expression_unquoted():
    # no filtergraph-special chars -> left alone
    assert format_arg("iw*1.04") == "iw*1.04"


def test_escape_comma_expression_quoted():
    assert format_arg("between(t,1.500,3.000)") == "'between(t,1.500,3.000)'"


def test_escape_windows_path_with_colon_quoted():
    # C:\ drive colon + backslashes -> single-quoted, backslashes literal
    assert format_arg(r"C:\shots\a.png") == r"'C:\shots\a.png'"


def test_escape_space_quoted():
    assert format_arg("hello world") == "'hello world'"


def test_escape_embedded_single_quote():
    assert format_arg("a'b") == "'a'\\''b'"


# ─── Graph label management ────────────────────────────────────────────────

def test_new_label_unique_and_prefixed():
    g = Graph()
    labels = [g.new_label("s") for _ in range(3)]
    assert labels == ["s1", "s2", "s3"]
    assert len(set(labels)) == 3


def test_new_label_avoids_registered_output():
    g = Graph()
    g.add(FilterNode("null", inputs=["a"], outputs=["s1"]))  # reserves s1
    # counter would produce s1 first; must skip to s2
    assert g.new_label("s") == "s2"


def test_graph_render_joins_with_semicolons():
    g = Graph()
    g.add(FilterNode("null", inputs=["a"], outputs=["b"]))
    g.add(FilterNode("null", inputs=["b"], outputs=["c"]))
    assert g.render() == "[a]null[b];[b]null[c]"


def test_color_source_builder():
    g = Graph()
    lbl = color_source(g, "0x0A0E14", 320, 180, 3.0, 30, "bg1")
    assert lbl == "bg1"
    assert g.render() == (
        "color=c=0x0A0E14:s=320x180:d=3.000:r=30,"
        "settb=expr=AVTB,format=yuv420p[bg1]"
    )


# ─── InputList registry ────────────────────────────────────────────────────

def test_inputlist_indices_and_flat_args():
    il = InputList()
    assert il.add(["-i", "a.wav"]) == 0
    assert il.add(["-loop", "1", "-t", "3.000", "-i", "img.png"]) == 1
    assert len(il) == 2
    assert il.args() == ["-i", "a.wav", "-loop", "1", "-t", "3.000",
                         "-i", "img.png"]


# ─── scene_input_args matrix (port of legacy test_scene_input_args.py) ──────

def test_image_scene_loops_for_eff_dur():
    args, pad = scene_input_args(kind="image", src="img.png", offset=0.0,
                                 eff_dur=5.0)
    assert args == ["-loop", "1", "-t", "5.000", "-i", "img.png"]
    assert pad == 0.0


def test_video_scene_long_enough_no_pad():
    args, pad = scene_input_args(kind="video", src="bg.mp4", offset=0.0,
                                 eff_dur=10.0, source_duration=30.0)
    assert "-t" in args and "10.000" in args
    assert pad == 0.0


def test_video_scene_too_short_triggers_pad():
    # 5s source, 6s slot -> read whole tail (no -t), pad 1.0 (the 5s/6s bug)
    args, pad = scene_input_args(kind="video", src="anim.mp4", offset=0.0,
                                 eff_dur=6.0, source_duration=5.0)
    assert "-t" not in args
    assert pad == pytest.approx(1.0)


def test_video_offset_past_eof_clamps_with_warning(capsys):
    args, pad = scene_input_args(kind="video", src="trailer.mp4", offset=22.0,
                                 eff_dur=4.0, source_duration=20.0)
    out = capsys.readouterr().out
    assert "WARNING" in out and "trailer.mp4" in out
    assert "-ss" in args and args[args.index("-ss") + 1] == "0.000"
    assert pad == 0.0


def test_video_offset_near_eof_no_clamp():
    args, pad = scene_input_args(kind="video", src="bg.mp4", offset=15.0,
                                 eff_dur=4.0, source_duration=20.0)
    assert pad == 0.0
    assert "15.000" in args


def test_video_loop_flag_uses_stream_loop():
    args, pad = scene_input_args(kind="video", src="loop.mp4", offset=0.0,
                                 eff_dur=10.0, loop=True, source_duration=3.0)
    assert "-stream_loop" in args
    assert args[args.index("-stream_loop") + 1] == "-1"
    assert pad == 0.0


def test_unknown_kind_raises():
    with pytest.raises(ValueError):
        scene_input_args(kind="audio", src="x", offset=0.0, eff_dur=1.0)


# ─── xfade offset math (port of legacy test_xfade_chain.py) ─────────────────

def test_single_scene_no_xfade():
    g = Graph()
    label = build_xfade_chain(g, ["s0"], [10.0], 0.6)
    assert label == "s0"
    assert g.render() == ""


def test_two_scenes_one_xfade():
    g = Graph()
    label = build_xfade_chain(g, ["s0", "s1"], [5.0, 4.0], 0.6)
    s = g.render()
    assert "xfade=transition=fade:duration=0.600:offset=5.000" in s
    assert "[s0][s1]" in s
    assert label == "xf1"


def test_three_scenes_two_xfades_cumulative_offsets():
    g = Graph()
    label = build_xfade_chain(g, ["s0", "s1", "s2"], [5.0, 4.0, 6.0], 0.6)
    s = g.render()
    assert "offset=5.000" in s          # 5
    assert "offset=9.000" in s          # 5+4
    assert "[s0][s1]" in s
    assert "[xf1][s2]" in s
    assert label == "xf2"


def test_nine_scenes_eight_xfades_offsets_monotonic():
    durs = [3.0, 4.0, 5.0, 3.5, 2.5, 4.0, 3.0, 4.5, 2.0]
    g = Graph()
    label = build_xfade_chain(g, [f"s{i}" for i in range(9)], durs, 0.6)
    s = g.render()
    assert label == "xf8"
    for off in [3.0, 7.0, 12.0, 15.5, 18.0, 22.0, 25.0, 29.5]:
        assert f"offset={off:.3f}" in s, f"missing offset={off}"


def test_zero_crossfade_dur_uses_concat_hard_cut():
    g = Graph()
    label = build_xfade_chain(g, ["s0", "s1"], [5.0, 4.0], 0.0)
    assert g.render() == "[s0][s1]concat=n=2:v=1:a=0[xf1]"
    assert label == "xf1"


def test_xfade_offsets_pure():
    assert xfade_offsets([5.0, 4.0, 6.0]) == [5.0, 9.0]
    assert xfade_offsets([10.0]) == []


def test_per_boundary_durations_and_transitions():
    g = Graph()
    build_xfade_chain(g, ["s0", "s1", "s2"], [5.0, 4.0, 6.0],
                      [0.3, 0.0], transitions=["fade", "fadeblack"])
    s = g.render()
    assert "transition=fade:duration=0.300:offset=5.000" in s
    assert "[xf1][s2]concat=n=2:v=1:a=0[xf2]" in s
    assert "duration=0.000" not in s
