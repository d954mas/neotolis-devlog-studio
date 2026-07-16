"""Full build_timeline integration: overlays (z-order + anim resolution),
warning propagation, asset registry, duration sourcing."""
from __future__ import annotations

import json

import pytest

from _builders import mk_design, probe
from dlstudio.compile import build_timeline
from dlstudio.model import Beat, Chunk, Edit, Scene
from dlstudio.model.content import Anim, ImageShot, Overlay, Plate, Transition


def _words(tmp_path, triples):
    p = tmp_path / "w.json"
    p.write_text(json.dumps({
        "words": [{"word": t, "start": a, "end": b} for (a, b, t) in triples]
    }), encoding="utf-8")
    return str(p)


def _base_probes(**extra):
    p = {
        "vo.wav": probe("vo.wav", "audio", duration=4.0, has_audio=True),
        "/fonts/main.ttf": probe("/fonts/main.ttf", "font"),
        "/fonts/bold.ttf": probe("/fonts/bold.ttf", "font"),
    }
    p.update(extra)
    return p


def _edit(beat, probes):
    return Edit(name="e", design=mk_design(), beats={"b1": beat},
                order=["b1"], output="out.mp4"), probes


def test_beat_duration_from_audio_probe(tmp_path):
    w = _words(tmp_path, [(0.0, 0.4, "a")])
    beat = Beat(audio="vo.wav", words=w, chunks=[Chunk(words=(0, 0), content=Plate(text="A"))])
    edit, probes = _edit(beat, _base_probes())
    tl = build_timeline(edit, probe=False, probes=probes)
    assert tl.beats[0].duration == 4.0
    assert tl.beats[0].words_path == w
    assert len(tl.beats[0].words) == 1


def test_only_plate_overlay_become_overlays_with_list_order_z(tmp_path):
    w = _words(tmp_path, [(0.0, 0.4, "a"), (1.0, 1.4, "b"),
                          (2.0, 2.4, "c"), (3.0, 3.4, "d")])
    beat = Beat(audio="vo.wav", words=w, scene=Scene(kind="video", src="bg.mp4"),
                chunks=[
                    Chunk(words=(0, 0), content=Plate(text="P")),         # overlay z0
                    Chunk(words=(1, 1), content=ImageShot(src="img.png")),  # segment, no overlay
                    Chunk(words=(2, 2), content=Overlay(text="O")),       # overlay z1
                    Chunk(words=(3, 3), content=Plate(text="P2")),        # overlay z2
                ])
    edit, probes = _edit(beat, _base_probes(
        **{"bg.mp4": probe("bg.mp4", "video", duration=30.0, width=1080, height=1920),
           "img.png": probe("img.png", "image", width=1080, height=1920)}))
    tl = build_timeline(edit, probe=False, probes=probes)
    ov = tl.beats[0].overlays
    assert [(o.chunk_index, o.z) for o in ov] == [(0, 0), (2, 1), (3, 2)]


def test_anim_normalized_t_resolved_to_beat_relative_seconds(tmp_path):
    w = _words(tmp_path, [(0.0, 0.4, "a"), (2.0, 2.4, "b")])
    beat = Beat(audio="vo.wav", words=w, chunks=[
        Chunk(words=(0, 0), content=Plate(text="A"),
              anims=[Anim(prop="scale", start=1.04, end=1.0, ease="out", t=(0.0, 0.5))]),
        Chunk(words=(1, 1), content=Plate(text="B")),
    ])
    edit, probes = _edit(beat, _base_probes())
    tl = build_timeline(edit, probe=False, probes=probes)
    # chunk0 window = [0.0, 2.0] (first->0, tiled to next chunk start 2.0)
    a = tl.beats[0].overlays[0].anims[0]
    assert a.prop == "scale" and a.start == 1.04 and a.end == 1.0
    assert a.t0 == 0.0            # 0.0 + 0.0 * 2.0
    assert a.t1 == 1.0           # 0.0 + 0.5 * 2.0


def test_chunk_transition_recorded_on_overlay(tmp_path):
    w = _words(tmp_path, [(0.0, 0.4, "a")])
    beat = Beat(audio="vo.wav", words=w, chunks=[
        Chunk(words=(0, 0), content=Plate(text="A"),
              transition=Transition(kind="slide_left", dur=0.4))])
    edit, probes = _edit(beat, _base_probes())
    tl = build_timeline(edit, probe=False, probes=probes)
    tin = tl.beats[0].overlays[0].transition_in
    assert tin is not None and tin.kind == "slide_left" and tin.dur == 0.4


def test_warnings_carry_beat_prefix(tmp_path):
    w = _words(tmp_path, [(0.0, 0.4, "a")])
    beat = Beat(audio="vo.wav", words=w, chunks=[
        Chunk(words=(0, 0), content=Overlay(text="O"),
              scene=Scene(kind="video", src="short.mp4", offset=50.0))])
    edit, probes = _edit(beat, _base_probes(
        **{"short.mp4": probe("short.mp4", "video", duration=6.0, width=1080, height=1920)}))
    tl = build_timeline(edit, probe=False, probes=probes)
    assert any(x.startswith("[b1] VQ-OFFSET:") for x in tl.warnings)


def test_diagnostics_carry_structured_vq_offset_clamp(tmp_path):
    # Same scenario as test_warnings_carry_beat_prefix, but asserting the
    # structured CheckIssue side of the migration: compile appends a
    # CheckIssue to Timeline.diagnostics (where=beat_id) in addition to the
    # human-readable warning string.
    w = _words(tmp_path, [(0.0, 0.4, "a")])
    beat = Beat(audio="vo.wav", words=w, chunks=[
        Chunk(words=(0, 0), content=Overlay(text="O"),
              scene=Scene(kind="video", src="short.mp4", offset=50.0))])
    edit, probes = _edit(beat, _base_probes(
        **{"short.mp4": probe("short.mp4", "video", duration=6.0, width=1080, height=1920)}))
    tl = build_timeline(edit, probe=False, probes=probes)
    offset_diags = [d for d in tl.diagnostics if d.code == "VQ-OFFSET"]
    assert len(offset_diags) == 1
    d = offset_diags[0]
    assert d.severity == "warn"
    assert d.where == "b1"
    assert "short.mp4" in d.message
    assert "VQ-OFFSET" not in d.message   # message is untagged; code carries the tag


def test_diagnostics_carry_structured_vq_words_out_of_range(tmp_path):
    w = _words(tmp_path, [(0.0, 0.4, "a")])
    beat = Beat(audio="vo.wav", words=w, chunks=[Chunk(words=(5, 9), content=Plate(text="P"))])
    edit, probes = _edit(beat, _base_probes())
    tl = build_timeline(edit, probe=False, probes=probes)
    words_diags = [d for d in tl.diagnostics if d.code == "VQ-WORDS"]
    assert words_diags
    assert any("out of range" in d.message and d.where == "b1" and d.severity == "error"
               for d in words_diags)


def test_registry_collects_every_referenced_path(tmp_path):
    w = _words(tmp_path, [(0.0, 0.4, "a")])
    beat = Beat(audio="vo.wav", words=w, scene=Scene(kind="video", src="bg.mp4"),
                chunks=[
                    Chunk(words=(0, 0), content=Plate(text="A", bg_image="plate_bg.png")),
                ])
    edit, probes = _edit(beat, _base_probes(
        **{"bg.mp4": probe("bg.mp4", "video", duration=30.0, width=1080, height=1920),
           "plate_bg.png": probe("plate_bg.png", "image", width=1080, height=1920)}))
    tl = build_timeline(edit, probe=False, probes=probes)
    for path in ("vo.wav", "bg.mp4", "plate_bg.png", "/fonts/main.ttf", w):
        assert path in tl.assets
    assert tl.assets["vo.wav"].kind == "audio"
    assert tl.assets["bg.mp4"].kind == "video"
    assert tl.assets["plate_bg.png"].kind == "image"
    assert tl.assets[w].kind == "other"          # words json


def test_missing_audio_duration_raises(tmp_path):
    w = _words(tmp_path, [(0.0, 0.4, "a")])
    beat = Beat(audio="vo.wav", words=w, chunks=[Chunk(words=(0, 0), content=Plate(text="A"))])
    # audio probe present but no duration
    probes = _base_probes(**{"vo.wav": probe("vo.wav", "audio", duration=None)})
    edit, _ = _edit(beat, probes)
    with pytest.raises(ValueError, match="cannot determine duration"):
        build_timeline(edit, probe=False, probes=probes)


def test_timeline_json_serializable(tmp_path):
    w = _words(tmp_path, [(0.0, 0.4, "a")])
    beat = Beat(audio="vo.wav", words=w, chunks=[Chunk(words=(0, 0), content=Plate(text="A"))])
    edit, probes = _edit(beat, _base_probes())
    tl = build_timeline(edit, probe=False, probes=probes)
    dumped = tl.model_dump_json()
    assert '"edit_name":"e"' in dumped.replace(" ", "")
