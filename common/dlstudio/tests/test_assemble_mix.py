"""Phase-2 assemble: the full audio mix graph + dip-to-black transitions.

Two layers:

- UNIT (no ffmpeg): the pure filter-graph builders in render.graph and the
  boundary-fade split in render.assemble — adelay placement math, gain
  conversion, the Duck->sidechaincompress mapping, ducking node wiring, span
  trimming. These assert on the rendered filter strings, so they need no media.

- INTEGRATION (real ffmpeg, tiny/fast): 2 beats with sine VO stems + a music
  bed with duck=True (music measurably quieter under VO than in a VO gap), a
  dip-to-black transition (boundary frame near-black), and the two-pass
  loudnorm landing within +/-1.5 LU of target. All at 320x180, ~1s beats, so
  the whole integration set stays well under the runtime budget.
"""
from __future__ import annotations

import importlib
import re
import shutil
import subprocess

import numpy as np
import pytest
from PIL import Image

from dlstudio.ir import (
    BeatPlacement,
    IRBeat,
    IRMix,
    IRMusicSpan,
    IRSfx,
    Timeline,
    WordSpan,
)
from dlstudio.model import Design, Duck, Fonts, Palette, Transition
from dlstudio.render import RenderOpts, assemble, measure_loudness, render_beat
from dlstudio.render.graph import (
    amix_sum_node,
    asplit_node,
    db_to_linear,
    delay_ms,
    duck_params,
    music_span_chain,
    sfx_chain,
    sidechain_duck_node,
    vo_stem_chain,
)

# Reach the real submodule (not the function shadowing the attribute on the
# render package) for the private boundary-fade helper — see the note in
# test_render_assemble.py for why importlib is required here.
assemble_mod = importlib.import_module("dlstudio.render.assemble")


# ══════════════════════════════════════════════════════════════════════════
# UNIT — pure filter-graph construction (no ffmpeg)
# ══════════════════════════════════════════════════════════════════════════

def test_db_to_linear_conversion():
    assert db_to_linear(0.0) == pytest.approx(1.0)
    assert db_to_linear(-6.0) == pytest.approx(0.5012, abs=1e-3)
    assert db_to_linear(-20.0) == pytest.approx(0.1, abs=1e-6)
    assert db_to_linear(-30.0) == pytest.approx(0.03162, abs=1e-4)


def test_delay_ms_placement_math():
    assert delay_ms(0.0) == 0
    assert delay_ms(1.0) == 1000
    assert delay_ms(5.25) == 5250
    assert delay_ms(0.0016) == 2         # rounds to nearest ms
    assert delay_ms(-3.0) == 0           # negative clamps to 0


def test_duck_params_maps_threshold_to_linear_and_derives_ratio():
    p = duck_params(Duck(amount_db=-12.0, threshold_db=-30.0,
                         attack_ms=120, release_ms=400))
    # threshold is LINEAR amplitude, not dB
    assert p["threshold"] == pytest.approx(db_to_linear(-30.0), abs=1e-5)
    # ratio derived from amount_db: 1 + |−12|/2 = 7
    assert p["ratio"] == pytest.approx(7.0)
    # attack/release pass straight through as ms
    assert p["attack"] == 120
    assert p["release"] == 400
    # no make-up gain: ducking only ever attenuates
    assert p["makeup"] == 1


def test_duck_params_ratio_clamped():
    assert duck_params(Duck(amount_db=-1.0)).__getitem__("ratio") == pytest.approx(2.0)   # floor
    assert duck_params(Duck(amount_db=-100.0)).__getitem__("ratio") == pytest.approx(20.0)  # ceil


def test_sidechain_duck_node_wires_music_then_key():
    node = sidechain_duck_node("mus1", "vok1", "musd1",
                               Duck(amount_db=-12.0, threshold_db=-30.0,
                                    attack_ms=120, release_ms=400))
    r = node.render()
    # FIRST input compressed (music), SECOND is the sidechain key (VO)
    assert r.startswith("[mus1][vok1]sidechaincompress=")
    assert r.endswith("[musd1]")
    assert "ratio=7.000" in r
    assert "attack=120" in r and "release=400" in r


def test_vo_stem_chain_places_at_absolute_start():
    r = vo_stem_chain("3:a", "vo3", 5.0).render()
    assert r.startswith("[3:a]aformat=sample_rates=48000:channel_layouts=stereo,")
    assert "adelay=delays=5000:all=1" in r
    assert r.endswith("[vo3]")


def test_vo_stem_chain_zero_delay_at_edit_start():
    assert "adelay=delays=0:all=1" in vo_stem_chain("0:a", "vo0", 0.0).render()


def test_music_span_chain_trims_and_fades():
    r = music_span_chain("2:a", "mus1", span_len=8.0, gain_db=-18.0,
                         fade_in=1.0, fade_out=1.5, delay_t=5.0).render()
    # trimmed to exactly the placed span length
    assert "atrim=duration=8.000" in r
    # gain in dB
    assert "volume=-18.0dB" in r
    # fade in at 0, fade out at span_len - fade_out = 6.5
    assert "afade=t=in:st=0.000:d=1.000" in r
    assert "afade=t=out:st=6.500:d=1.500" in r
    # placed at absolute t0
    assert "adelay=delays=5000:all=1" in r


def test_music_span_chain_skips_zero_fades():
    r = music_span_chain("2:a", "m", span_len=4.0, gain_db=-10.0,
                         fade_in=0.0, fade_out=0.0, delay_t=0.0).render()
    assert "afade" not in r


def test_sfx_chain_gain_and_delay():
    r = sfx_chain("4:a", "sfx1", gain_db=-3.0, delay_t=6.2).render()
    assert "volume=-3.0dB" in r
    assert "adelay=delays=6200:all=1" in r
    assert r.endswith("[sfx1]")


def test_amix_sum_node_is_a_sum_not_average():
    r = amix_sum_node(["a", "b", "c"], "mix").render()
    assert r == "[a][b][c]amix=inputs=3:normalize=0:duration=longest[mix]"


def test_asplit_node_fans_out():
    r = asplit_node("vosum", ["vofin", "vok1", "vok2"]).render()
    assert r == "[vosum]asplit=3[vofin][vok1][vok2]"


# ─── boundary-fade split (dip-to-black transition model) ────────────────────

def _ir_beat(bid, dur, transition_out=None):
    return IRBeat(id=bid, duration=dur, audio=f"{bid}.wav", words_path="w.json",
                  words=[], segments=[], overlays=[], transition_out=transition_out)


def test_boundary_fades_split_transition_in_half():
    beats = [
        _ir_beat("b1", 5.0, Transition(kind="dip_black", dur=0.4)),
        _ir_beat("b2", 3.0, Transition(kind="fade", dur=0.6)),
        _ir_beat("b3", 4.0),
    ]
    fades = assemble_mod._boundary_fades(beats)
    # b1: no head fade (first beat), tail = 0.4/2
    assert fades[0] == pytest.approx((0.0, 0.2))
    # b2: head = b1's 0.4/2, tail = 0.6/2
    assert fades[1] == pytest.approx((0.2, 0.3))
    # b3: head = b2's 0.6/2, no tail (no transition_out)
    assert fades[2] == pytest.approx((0.3, 0.0))


def test_boundary_fades_cut_and_zero_dur_are_no_fades():
    beats = [
        _ir_beat("b1", 5.0, Transition(kind="cut", dur=0.5)),      # cut -> no fade
        _ir_beat("b2", 3.0, Transition(kind="fade", dur=0.0)),     # 0 dur -> no fade
        _ir_beat("b3", 4.0),
    ]
    fades = assemble_mod._boundary_fades(beats)
    assert fades == [(0.0, 0.0), (0.0, 0.0), (0.0, 0.0)]


# ══════════════════════════════════════════════════════════════════════════
# INTEGRATION — real ffmpeg, tiny/fast
# ══════════════════════════════════════════════════════════════════════════

pytestmark_integration = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH")


def _design(bg="#101418"):
    return Design(
        resolution=(320, 180), fps=24,
        palette=Palette(tokens={"bg": bg, "text": "#ffffff"}),
        fonts=Fonts(main="none.ttf"),
    )


def _sine(path, freq, dur):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"sine=frequency={freq}:duration={dur}", "-ac", "1", "-ar", "48000",
         str(path)], check=True, capture_output=True)


def _silence(path, dur):
    subprocess.run(
        ["ffmpeg", "-y", "-f", "lavfi", "-i",
         f"anullsrc=r=48000:cl=mono:d={dur}", "-ac", "1", "-ar", "48000",
         str(path)], check=True, capture_output=True)


def _probe_dur(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip())


def _has_audio(path):
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-select_streams", "a", "-show_entries",
         "stream=codec_type", "-of", "csv=p=0", str(path)],
        capture_output=True, text=True)
    return "audio" in r.stdout


def _band_mean_db(path, ss, dur, freq):
    """mean_volume (dB) of a segment after bandpass around `freq` — isolates
    one tone's energy so ducked music can be measured without VO bleed."""
    r = subprocess.run(
        ["ffmpeg", "-ss", str(ss), "-t", str(dur), "-i", str(path),
         "-af", f"bandpass=f={freq}:width_type=h:w=80,volumedetect",
         "-f", "null", "-"], capture_output=True, text=True)
    m = re.search(r"mean_volume:\s*(-?\d+(?:\.\d+)?)\s*dB", r.stderr)
    assert m, f"no mean_volume in ffmpeg output: {r.stderr[-400:]}"
    return float(m.group(1))


def _frame_luma(path, ss):
    """Mean luma (0..255) of the frame at output-seek time `ss`."""
    tmp = str(path) + f".{ss}.png"
    subprocess.run(
        ["ffmpeg", "-y", "-ss", str(ss), "-i", str(path), "-frames:v", "1",
         "-update", "1", tmp], check=True, capture_output=True)
    return float(np.asarray(Image.open(tmp).convert("L")).mean())


def _render_two_beats(tmp_path, design, a1, a2, *, t1_out=None):
    """Render two 1s beats -> (beats, beat_files). VO stems land next to the
    MP4s (render_beat drops them), which is what the mix reads."""
    b1 = IRBeat(id="b1", duration=1.0, audio=str(a1), words_path="w.json",
                words=[WordSpan(t0=0.0, t1=1.0, text="x")], segments=[],
                overlays=[], transition_out=t1_out)
    b2 = IRBeat(id="b2", duration=1.0, audio=str(a2), words_path="w.json",
                words=[WordSpan(t0=0.0, t1=1.0, text="y")], segments=[],
                overlays=[])
    opts = RenderOpts(quality="standard", workdir=tmp_path / "fin")
    f1 = render_beat(b1, design, None, opts)
    f2 = render_beat(b2, design, None, opts)
    return [b1, b2], {"b1": f1, "b2": f2}


def _timeline(beats, mix, out, *, design):
    return Timeline(
        edit_name="e", design=design, beats=beats,
        placements=[BeatPlacement(beat_id="b1", t0=0.0),
                    BeatPlacement(beat_id="b2", t0=1.0)],
        mix=mix, assets={}, output=str(out))


@pytestmark_integration
def test_music_ducks_under_vo(tmp_path):
    """Music (800Hz) measurably quieter during VO ([0,1], 300Hz) than in the
    VO gap ([1,2], silence). duck=True -> sidechaincompress keyed by VO."""
    design = _design()
    a1, a2 = tmp_path / "vo1.wav", tmp_path / "vo2.wav"
    _sine(a1, 300, 1.0)
    _silence(a2, 1.0)                       # beat 2 VO is silent -> a real gap
    music = tmp_path / "music.wav"
    _sine(music, 800, 2.0)

    beats, beat_files = _render_two_beats(tmp_path, design, a1, a2)
    mix = IRMix(
        music=[IRMusicSpan(src=str(music), t0=0.0, t1=2.0, offset=0.0,
                           gain_db=-6.0, fade_in=0.05, fade_out=0.05, duck=True)],
        duck=Duck(amount_db=-12.0, threshold_db=-30.0, attack_ms=80, release_ms=200),
    )
    out = tmp_path / "final.mp4"
    tl = _timeline(beats, mix, out, design=design)

    assemble(tl, beat_files, RenderOpts(quality="standard", workdir=tmp_path / "fin"))

    assert out.exists() and _has_audio(out)
    assert abs(_probe_dur(out) - 2.0) < 0.5

    during_vo = _band_mean_db(out, 0.2, 0.6, 800)   # music ducked here
    vo_gap = _band_mean_db(out, 1.2, 0.6, 800)      # music at full level here
    # ducked region is clearly quieter (experimentally ~5 dB; require >=2 dB)
    assert during_vo < vo_gap - 2.0, f"during_vo={during_vo} vo_gap={vo_gap}"


@pytestmark_integration
def test_dip_black_transition_boundary_is_near_black(tmp_path):
    """dip_black transition on a WHITE-bg edit: the boundary frame is
    near-black while mid-beat frames stay bright."""
    design = _design(bg="#ffffff")
    a1, a2 = tmp_path / "v1.wav", tmp_path / "v2.wav"
    _sine(a1, 300, 1.0)
    _sine(a2, 400, 1.0)

    beats, beat_files = _render_two_beats(
        tmp_path, design, a1, a2, t1_out=Transition(kind="dip_black", dur=0.4))
    out = tmp_path / "final.mp4"
    tl = _timeline(beats, IRMix(), out, design=design)

    assemble(tl, beat_files, RenderOpts(quality="standard", workdir=tmp_path / "fin"))

    assert out.exists() and abs(_probe_dur(out) - 2.0) < 0.5
    boundary = _frame_luma(out, 1.0)     # start of b2, fully faded from black
    mid_b1 = _frame_luma(out, 0.4)       # well before the fade -> white
    mid_b2 = _frame_luma(out, 1.6)       # well after the fade-in -> white
    assert boundary < 80, f"boundary luma {boundary} not near-black"
    assert mid_b1 > 180 and mid_b2 > 180, f"mid luma {mid_b1}/{mid_b2} not bright"


@pytestmark_integration
def test_final_loudness_within_tolerance(tmp_path):
    """Two-pass loudnorm (standard quality) lands the final mix within
    +/-1.5 LU of the target integrated loudness."""
    design = _design()
    a1, a2 = tmp_path / "l1.wav", tmp_path / "l2.wav"
    _sine(a1, 300, 1.0)
    _sine(a2, 440, 1.0)
    music = tmp_path / "m.wav"
    _sine(music, 800, 2.0)

    beats, beat_files = _render_two_beats(tmp_path, design, a1, a2)
    mix = IRMix(
        music=[IRMusicSpan(src=str(music), t0=0.0, t1=2.0, gain_db=-8.0, duck=True)],
        target_lufs=-14.0, true_peak_db=-1.0,
    )
    out = tmp_path / "final.mp4"
    tl = _timeline(beats, mix, out, design=design)

    assemble(tl, beat_files, RenderOpts(quality="standard", workdir=tmp_path / "fin"))

    measured = measure_loudness(out, target_lufs=-14.0, true_peak=-1.0)
    integrated = float(measured["input_i"])
    assert abs(integrated - (-14.0)) <= 1.5, f"integrated LUFS {integrated}"


@pytestmark_integration
def test_missing_vo_stem_falls_back_to_beat_audio(tmp_path, capsys):
    """When a beat's VO stem is absent (e.g. MP4 restored from cache), the mix
    extracts audio from the beat MP4 with a warning and still mixes."""
    design = _design()
    a1, a2 = tmp_path / "s1.wav", tmp_path / "s2.wav"
    _sine(a1, 300, 1.0)
    _sine(a2, 400, 1.0)
    music = tmp_path / "m.wav"
    _sine(music, 800, 2.0)

    beats, beat_files = _render_two_beats(tmp_path, design, a1, a2)
    # Simulate a cache-restored MP4: delete the sibling VO stems.
    for f in beat_files.values():
        f.with_name(f.stem + "_vo_stem.wav").unlink()

    mix = IRMix(music=[IRMusicSpan(src=str(music), t0=0.0, t1=2.0, duck=False)])
    out = tmp_path / "final.mp4"
    tl = _timeline(beats, mix, out, design=design)

    # draft quality -> single-pass loudnorm keeps this fast
    assemble(tl, beat_files, RenderOpts(quality="draft", workdir=tmp_path / "fin"))

    assert out.exists() and _has_audio(out)
    assert abs(_probe_dur(out) - 2.0) < 0.5
    assert "VO stem missing" in capsys.readouterr().out


@pytestmark_integration
def test_sfx_placed_in_mix(tmp_path):
    """An SFX one-shot anchored inside beat 2 lands in the mixed output at its
    absolute time (placement.t0 + sfx.t)."""
    design = _design()
    a1, a2 = tmp_path / "x1.wav", tmp_path / "x2.wav"
    _silence(a1, 1.0)
    _silence(a2, 1.0)                       # silent VO so only SFX shows in-band
    ding = tmp_path / "ding.wav"
    _sine(ding, 1200, 0.2)

    b1 = IRBeat(id="b1", duration=1.0, audio=str(a1), words_path="w.json",
                words=[WordSpan(t0=0.0, t1=1.0, text="x")], segments=[], overlays=[])
    b2 = IRBeat(id="b2", duration=1.0, audio=str(a2), words_path="w.json",
                words=[WordSpan(t0=0.0, t1=1.0, text="y")], segments=[], overlays=[],
                sfx=[IRSfx(src=str(ding), t=0.3, gain_db=0.0)])
    opts = RenderOpts(quality="draft", workdir=tmp_path / "fin")
    f1 = render_beat(b1, design, None, opts)
    f2 = render_beat(b2, design, None, opts)

    out = tmp_path / "final.mp4"
    tl = _timeline([b1, b2], IRMix(), out, design=design)
    assemble(tl, {"b1": f1, "b2": f2}, opts)

    assert out.exists() and _has_audio(out)
    # SFX at absolute t = 1.0 + 0.3 = 1.3s: strong 1200Hz energy around it,
    # near-silence in the first beat where nothing is placed.
    at_sfx = _band_mean_db(out, 1.25, 0.2, 1200)
    before = _band_mean_db(out, 0.2, 0.5, 1200)
    assert at_sfx > before + 6.0, f"sfx={at_sfx} before={before}"
