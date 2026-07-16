"""Edit-level resolution: beat placements, MusicRegion spans across beats,
SfxEvent word anchors."""
from __future__ import annotations

import json

import pytest

from _builders import mk_design, plate_chunk, probe
from dlstudio.compile import build_timeline
from dlstudio.model import Beat, Edit, Mix, MusicRegion, SfxEvent


def _write_words(tmp_path, name, triples):
    p = tmp_path / f"{name}.json"
    p.write_text(json.dumps({
        "words": [{"word": t, "start": a, "end": b} for (a, b, t) in triples]
    }), encoding="utf-8")
    return str(p)


def _edit(tmp_path, *, music=None, sfx=None):
    # three beats, durations 5 / 3 / 4 -> placements 0 / 5 / 8, total 12
    wa = _write_words(tmp_path, "wa", [(0.0, 0.5, "a"), (1.0, 1.5, "b")])
    wb = _write_words(tmp_path, "wb", [(0.0, 0.5, "c"), (1.2, 1.8, "d")])
    wc = _write_words(tmp_path, "wc", [(0.0, 0.5, "e")])
    beats = {
        "b1": Beat(audio="a1.wav", words=wa, chunks=[plate_chunk(0, 1)]),
        "b2": Beat(audio="a2.wav", words=wb, chunks=[plate_chunk(0, 1)],
                   sfx=sfx or []),
        "b3": Beat(audio="a3.wav", words=wc, chunks=[plate_chunk(0, 0)]),
    }
    edit = Edit(name="e", design=mk_design(), beats=beats,
                order=["b1", "b2", "b3"], output="out.mp4",
                mix=Mix(music=music or []))
    probes = {
        "a1.wav": probe("a1.wav", "audio", duration=5.0),
        "a2.wav": probe("a2.wav", "audio", duration=3.0),
        "a3.wav": probe("a3.wav", "audio", duration=4.0),
        "/fonts/main.ttf": probe("/fonts/main.ttf", "font"),
        "/fonts/bold.ttf": probe("/fonts/bold.ttf", "font"),
    }
    if music:
        for m in music:
            probes.setdefault(m.src, probe(m.src, "audio", duration=300.0))
    if sfx:
        for s in sfx:
            probes.setdefault(s.src, probe(s.src, "audio", duration=1.0))
    return edit, probes


def test_placements_sum_durations_in_order(tmp_path):
    edit, probes = _edit(tmp_path)
    tl = build_timeline(edit, probe=False, probes=probes)
    assert [(p.beat_id, p.t0) for p in tl.placements] == [
        ("b1", 0.0), ("b2", 5.0), ("b3", 8.0)]
    assert tl.duration == 12.0


def test_music_whole_edit_when_both_none(tmp_path):
    edit, probes = _edit(tmp_path, music=[MusicRegion(src="m.mp3")])
    tl = build_timeline(edit, probe=False, probes=probes)
    assert len(tl.mix.music) == 1
    span = tl.mix.music[0]
    assert (span.t0, span.t1) == (0.0, 12.0)


def test_music_region_single_beat_inclusive(tmp_path):
    edit, probes = _edit(tmp_path, music=[
        MusicRegion(src="m.mp3", from_beat="b2", to_beat="b2")])
    tl = build_timeline(edit, probe=False, probes=probes)
    span = tl.mix.music[0]
    # start of b2 = 5.0, end of b2 = 5.0 + 3.0 = 8.0 (inclusive to_beat)
    assert (span.t0, span.t1) == (5.0, 8.0)


def test_music_region_spanning_multiple_beats(tmp_path):
    edit, probes = _edit(tmp_path, music=[
        MusicRegion(src="m.mp3", from_beat="b1", to_beat="b3")])
    tl = build_timeline(edit, probe=False, probes=probes)
    span = tl.mix.music[0]
    assert (span.t0, span.t1) == (0.0, 12.0)


def test_music_region_open_start_and_open_end(tmp_path):
    edit, probes = _edit(tmp_path, music=[
        MusicRegion(src="m.mp3", from_beat=None, to_beat="b2"),
        MusicRegion(src="n.mp3", from_beat="b2", to_beat=None),
    ])
    tl = build_timeline(edit, probe=False, probes=probes)
    assert (tl.mix.music[0].t0, tl.mix.music[0].t1) == (0.0, 8.0)
    assert (tl.mix.music[1].t0, tl.mix.music[1].t1) == (5.0, 12.0)


def test_music_region_carries_mix_params(tmp_path):
    edit, probes = _edit(tmp_path, music=[
        MusicRegion(src="m.mp3", gain_db=-20.0, fade_in=2.0, fade_out=3.0,
                    offset=4.0, duck=False)])
    tl = build_timeline(edit, probe=False, probes=probes)
    span = tl.mix.music[0]
    assert span.gain_db == -20.0 and span.fade_in == 2.0
    assert span.fade_out == 3.0 and span.offset == 4.0 and span.duck is False


def test_music_region_unknown_beat_raises(tmp_path):
    edit, probes = _edit(tmp_path, music=[
        MusicRegion(src="m.mp3", from_beat="nope")])
    with pytest.raises(ValueError, match="from_beat 'nope'"):
        build_timeline(edit, probe=False, probes=probes)


def test_mix_globals_carried_over(tmp_path):
    edit, probes = _edit(tmp_path)
    tl = build_timeline(edit, probe=False, probes=probes)
    assert tl.mix.target_lufs == -14.0
    assert tl.mix.true_peak_db == -1.0


def test_sfx_anchor_resolves_to_word_start(tmp_path):
    edit, probes = _edit(tmp_path, sfx=[SfxEvent(src="ding.wav", word=1, gain_db=-3.0)])
    tl = build_timeline(edit, probe=False, probes=probes)
    b2 = next(b for b in tl.beats if b.id == "b2")
    assert len(b2.sfx) == 1
    # b2 words: word 1 starts at 1.2 (beat-relative)
    assert b2.sfx[0].t == 1.2
    assert b2.sfx[0].gain_db == -3.0
    assert b2.sfx[0].src == "ding.wav"


def test_sfx_out_of_range_anchor_defaults_to_zero(tmp_path):
    edit, probes = _edit(tmp_path, sfx=[SfxEvent(src="ding.wav", word=99)])
    tl = build_timeline(edit, probe=False, probes=probes)
    b2 = next(b for b in tl.beats if b.id == "b2")
    assert b2.sfx[0].t == 0.0
