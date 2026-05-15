"""Tests for _scene_input_args — covers the bugs:
- Short video sources (5s anim used as 6s scene) need tpad freeze
- Offset past EOF (trailer offset=22 for 20s file) → silent fail without clamp
- Image scenes always need -loop 1 + -t

Uses unittest.mock to avoid real ffprobe calls.
"""
from unittest.mock import patch
from devlog.types import Scene
from devlog.render.compose_ffmpeg import _scene_input_args


def _mock_probe(durations: dict[str, float]):
    """Return a fake _probe_duration that looks up by src path."""
    def fake(src: str) -> float:
        return durations.get(src, 0.0)
    return fake


def test_image_scene_loops_for_eff_dur():
    """Image scenes always use -loop 1 -t {eff_dur} -i {src}."""
    scene = Scene(kind="image", src="img.png")
    args, pad = _scene_input_args(scene, eff_dur=5.0)
    assert args == ["-loop", "1", "-t", "5.000", "-i", "img.png"]
    assert pad == 0.0


def test_video_scene_long_enough_no_pad():
    """Video source longer than eff_dur: read whole eff_dur, no padding."""
    scene = Scene(kind="video", src="bg.mp4", offset=0.0)
    with patch("devlog.render.compose_ffmpeg._probe_duration",
               _mock_probe({"bg.mp4": 30.0})):
        args, pad = _scene_input_args(scene, eff_dur=10.0)
    assert "-t" in args
    assert "10.000" in args
    assert pad == 0.0


def test_video_scene_too_short_triggers_pad():
    """Video source shorter than eff_dur: read whole tail, pad remainder
    via tpad in normalize filter. This is the hype_curve_anim 5s/6s bug."""
    scene = Scene(kind="video", src="anim.mp4", offset=0.0)
    with patch("devlog.render.compose_ffmpeg._probe_duration",
               _mock_probe({"anim.mp4": 5.0})):
        args, pad = _scene_input_args(scene, eff_dur=6.0)
    # When source is short, no -t (read whole tail), pad_needed = 1.0
    assert "-t" not in args                                         # no trim
    assert pad == 1.0


def test_video_offset_past_eof_clamps_with_warning(capsys):
    """Offset >= source duration: clamp to 0 to avoid silent video-stream-empty.
    This is the trailer_final offset=22 on 20s file bug."""
    scene = Scene(kind="video", src="trailer.mp4", offset=22.0)
    with patch("devlog.render.compose_ffmpeg._probe_duration",
               _mock_probe({"trailer.mp4": 20.0})):
        args, pad = _scene_input_args(scene, eff_dur=4.0)
    captured = capsys.readouterr()
    # WARNING printed
    assert "WARNING" in captured.out
    assert "trailer.mp4" in captured.out
    # Offset clamped to 0
    assert "-ss" in args
    idx = args.index("-ss")
    assert args[idx + 1] == "0.000"
    # Now requires full pad since available = 20-0 = 20, eff_dur=4, no pad needed
    # (clamped scene reads full source, plenty long for 4s eff_dur)
    assert pad == 0.0


def test_video_offset_near_eof_no_clamp():
    """Offset within source duration: no clamping."""
    scene = Scene(kind="video", src="bg.mp4", offset=15.0)
    with patch("devlog.render.compose_ffmpeg._probe_duration",
               _mock_probe({"bg.mp4": 20.0})):
        args, pad = _scene_input_args(scene, eff_dur=4.0)
    # Available = 20 - 15 = 5s; eff_dur = 4s → no pad
    assert pad == 0.0
    # -ss preserves 15.0
    assert "15.000" in args


def test_video_loop_flag_uses_stream_loop():
    """scene.loop=True uses -stream_loop -1 (infinite loop until -t cuts).
    Useful for short ambient loops vs one-shot animations."""
    scene = Scene(kind="video", src="loop.mp4", offset=0.0, loop=True)
    with patch("devlog.render.compose_ffmpeg._probe_duration",
               _mock_probe({"loop.mp4": 3.0})):
        args, pad = _scene_input_args(scene, eff_dur=10.0)
    assert "-stream_loop" in args
    idx = args.index("-stream_loop")
    assert args[idx + 1] == "-1"
    assert pad == 0.0
