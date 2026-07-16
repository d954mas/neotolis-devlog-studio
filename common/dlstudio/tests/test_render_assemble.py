"""Integration test for Phase-1 assemble: concat + duration postcondition.

Renders two tiny solid-bg beats (which guarantees identical codec params) and
concatenates them under stream copy. Fast: 320x180, 1s beats, draft.
"""
from __future__ import annotations

import importlib
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from dlstudio.ir import BeatPlacement, IRBeat, IRMix, Timeline, WordSpan
from dlstudio.model import Design, Fonts, Palette, Transition
from dlstudio.render import RenderOpts, assemble, render_beat

# `dlstudio.render.__init__` does `from .assemble import assemble`, which
# rebinds the `assemble` ATTRIBUTE on the `dlstudio.render` package to the
# function -- so a plain `import dlstudio.render.assemble as assemble_mod`
# resolves that same shadowed attribute (a well-known submodule-vs-attribute
# import gotcha) and hands back the function, not the module. Go through
# importlib.import_module, which reads sys.modules directly and is immune
# to the shadowing, to reach the actual submodule for `_scaled_tolerance`.
assemble_mod = importlib.import_module("dlstudio.render.assemble")

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
    """Fast path: no music, no SFX, no transitions -> stream-copy concat of the
    beat MP4s (video + their own VO audio), no re-encode, no mix graph."""
    design = _design()
    a1 = tmp_path / "a1.wav"
    a2 = tmp_path / "a2.wav"
    _wav(a1, 1.0)
    _wav(a2, 1.0)

    b1 = _beat("b1", a1, 1.0)   # no transition -> fast path
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

    # Fast path taken: no mix-graph work announced.
    assert "mix path" not in capsys.readouterr().out


# ─── M1: VQ-SYNC tolerance scales with beat count ──────────────────────────
#
# check.verify_output is fully implemented (not a NotImplementedError stub),
# so assemble's old `except NotImplementedError: _verify_duration(...)`
# fallback was dead code and the *effective* tolerance was always
# verify_output's fixed 0.25s default -- too tight for a long edit, where
# concat accumulates ~0.02-0.05s of AAC priming/rounding per beat. assemble
# now calls verify_output directly with a tolerance that scales with beat
# count: max(MIN_VERIFY_TOL, PER_BEAT_VERIFY_TOL * n_beats).

def test_scaled_tolerance_formula_pinned():
    assert assemble_mod._scaled_tolerance(1) == pytest.approx(0.5)
    assert assemble_mod._scaled_tolerance(10) == pytest.approx(0.5)   # floor
    assert assemble_mod._scaled_tolerance(20) == pytest.approx(1.0)   # 0.05*20
    assert assemble_mod._scaled_tolerance(100) == pytest.approx(5.0)  # 0.05*100


# ─── mixed copy + re-encode concat: one interior transition ────────────────
#
# assemble stream-copies non-boundary beats but RE-ENCODES the beats adjacent
# to a dip-to-black transition. A re-encode invents a fresh timebase, so a
# copied beat and a re-encoded beat could carry different timescales in the
# same concat and trip the concat demuxer. render_beat and _reencode_fade_segment
# now pin the SAME video timescale, so copy+re-encode concat is provably clean.


def _frame_luma(path, ss):
    """Mean luma (0..255) of the frame at seek time `ss`."""
    tmp = str(path) + f".{ss}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(ss), "-i", str(path), "-frames:v", "1",
         "-update", "1", tmp], check=True, capture_output=True)
    return float(np.asarray(Image.open(tmp).convert("L")).mean())


def _decode(path):
    """Fully decode the file at error log level; return (returncode, stderr).
    A timebase-mismatched concat surfaces here as non-monotonic DTS / invalid
    timestamp demuxer errors."""
    r = subprocess.run(
        ["ffmpeg", "-v", "error", "-i", str(path), "-f", "null", "-"],
        capture_output=True, text=True)
    return r.returncode, r.stderr


def test_mixed_copy_reencode_concat_one_interior_transition(tmp_path):
    """4 beats, ONE interior transition (only b2.transition_out). The b0-b1
    seam is a hard cut of two STREAM-COPIED beats; the b2-b3 boundary is
    RE-ENCODED to dip through black. Asserts: assemble verifies, no demuxer
    errors on a full decode, exact duration, the untouched b0-b1 seam is
    non-black on both sides, and the b2-b3 boundary dips black."""
    design = Design(
        resolution=(320, 180), fps=24,
        palette=Palette(tokens={"bg": "#ffffff", "text": "#000000"}),
        fonts=Fonts(main="none.ttf"),
    )
    opts = RenderOpts(quality="standard", workdir=tmp_path / "fin")

    t_out = [None, None, Transition(kind="dip_black", dur=0.4), None]
    beats, files = [], {}
    for i, freq in enumerate((300, 350, 400, 450)):
        a = tmp_path / f"a{i}.wav"
        subprocess.run(
            ["ffmpeg", "-y", "-f", "lavfi", "-i",
             f"sine=frequency={freq}:duration=1.0", "-ac", "1", "-ar", "48000",
             str(a)], check=True, capture_output=True)
        b = _beat(f"b{i}", a, 1.0, transition_out=t_out[i])
        beats.append(b)
        files[f"b{i}"] = render_beat(b, design, None, opts)

    out = tmp_path / "final.mp4"
    timeline = Timeline(
        edit_name="e", design=design, beats=beats,
        placements=[BeatPlacement(beat_id=f"b{i}", t0=float(i)) for i in range(4)],
        mix=IRMix(), assets={}, output=str(out),
    )

    assemble(timeline, files, opts)

    assert out.exists()
    assert abs(_probe(out) - 4.0) < 0.5

    rc, err = _decode(out)
    assert rc == 0, f"decode failed rc={rc}: {err[-400:]}"
    low = err.lower()
    for marker in ("monoton", "invalid", "corrupt", "error while decoding"):
        assert marker not in low, f"demuxer error ({marker!r}): {err[-400:]}"

    # Untouched (stream-copied) b0-b1 seam at t=1.0: bright white on both sides.
    assert _frame_luma(out, 0.9) > 180
    assert _frame_luma(out, 1.1) > 180
    # Re-encoded b2-b3 boundary at t=3.0: dipped to black.
    assert _frame_luma(out, 3.0) < 80


def test_assemble_calls_verify_output_with_scaled_tolerance(tmp_path, monkeypatch):
    design = _design()
    a1 = tmp_path / "a1.wav"
    a2 = tmp_path / "a2.wav"
    _wav(a1, 1.0)
    _wav(a2, 1.0)
    b1 = _beat("b1", a1, 1.0)
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

    # Patch AFTER rendering the two beats (which also call verify_output via
    # beat.py's own postcondition) so only assemble's own call is captured.
    import dlstudio.check as dl_check
    calls = []

    def fake_verify(path, expected, *, tolerance):
        calls.append((path, expected, tolerance))

    monkeypatch.setattr(dl_check, "verify_output", fake_verify)

    assemble(timeline, {"b1": f1, "b2": f2}, opts)

    assert len(calls) == 1
    _, expected, tolerance = calls[0]
    assert expected == pytest.approx(2.0)
    # 2 beats: 0.05*2=0.1 < the 0.5 floor -> floor wins.
    assert tolerance == pytest.approx(0.5)
    assert tolerance == pytest.approx(assemble_mod._scaled_tolerance(2))
