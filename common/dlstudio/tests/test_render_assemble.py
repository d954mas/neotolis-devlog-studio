"""Integration test for Phase-1 assemble: concat + duration postcondition.

Renders two tiny solid-bg beats (which guarantees identical codec params) and
concatenates them under stream copy. Fast: 320x180, 1s beats, draft.
"""
from __future__ import annotations

import shutil
import subprocess

import pytest

from dlstudio.ir import BeatPlacement, IRBeat, IRMix, Timeline, WordSpan
from dlstudio.model import Design, Fonts, Palette, Transition
from dlstudio.render import RenderOpts, assemble, render_beat

pytestmark = pytest.mark.skipif(shutil.which("ffmpeg") is None,
                                reason="ffmpeg not on PATH")


def _design():
    return Design(
        resolution=(320, 180), fps=24,
        palette=Palette(tokens={"bg": "#101418", "text": "#ffffff"}),
        fonts=Fonts(main="none.ttf"),
    )


def _wav(path, dur):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"sine=frequency=200:duration={dur}", "-ac", "1", str(path)],
        check=True, capture_output=True,
    )


def _beat(bid, audio, dur, transition_out=None):
    return IRBeat(
        id=bid, duration=dur, audio=str(audio),
        words_path="w.json", words=[WordSpan(t0=0.0, t1=dur, text="x")],
        segments=[], overlays=[], transition_out=transition_out,
    )


def _probe(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
    )
    return float(r.stdout.strip())


def test_assemble_concats_two_beats(tmp_path, capsys):
    design = _design()
    a1 = tmp_path / "a1.wav"
    a2 = tmp_path / "a2.wav"
    _wav(a1, 1.0)
    _wav(a2, 1.0)

    # second beat carries a transition_out -> Phase 1 hard-cuts + notes it
    b1 = _beat("b1", a1, 1.0, transition_out=Transition(kind="fade", dur=0.3))
    b2 = _beat("b2", a2, 1.0)

    opts = RenderOpts(quality="draft", workdir=tmp_path / "fin")
    f1 = render_beat(b1, design, None, opts)
    f2 = render_beat(b2, design, None, opts)

    timeline = Timeline(
        edit_name="e", design=design, beats=[b1, b2],
        placements=[BeatPlacement(beat_id="b1", t0=0.0),
                    BeatPlacement(beat_id="b2", t0=1.0)],
        mix=IRMix(), assets={}, output=str(tmp_path / "final.mp4"),
    )
    assert abs(timeline.duration - 2.0) < 1e-6

    out = assemble(timeline, {"b1": f1, "b2": f2}, opts)
    assert out.exists()
    assert abs(_probe(out) - 2.0) < 0.5

    # Phase-1 deferral note emitted for the fade transition_out
    assert "Phase 2" in capsys.readouterr().out
