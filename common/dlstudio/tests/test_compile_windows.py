"""Chunk word-index window resolution: pads, clamps, tiling, overlap detection.

Verifies the v1 windowing semantics preserved in compile.segments.resolve_windows
(see compose_ffmpeg.py L407-416: first-word start, next-chunk-start boundary).
"""
from __future__ import annotations

from _builders import plate_chunk, words
from dlstudio.compile.segments import resolve_windows


# words: 0:[0.0,0.4] 1:[0.5,0.9] 2:[1.0,1.3] 3:[2.0,2.4] 4:[2.5,2.9] 5:[3.0,3.4]
WS = words(
    (0.0, 0.4, "a"), (0.5, 0.9, "b"), (1.0, 1.3, "c"),
    (2.0, 2.4, "d"), (2.5, 2.9, "e"), (3.0, 3.4, "f"),
)
DUR = 4.0


def test_single_chunk_spans_whole_beat():
    chunks = [plate_chunk(0, 5)]
    wins, issues, _diags = resolve_windows(chunks, WS, DUR)
    assert wins == [(0.0, 4.0)]
    assert issues == []


def test_first_chunk_extends_to_zero_last_to_duration():
    # chunk0 first word starts at 0.0 anyway; chunk1 first word at 1.0.
    chunks = [plate_chunk(0, 1), plate_chunk(2, 5)]
    wins, issues, _diags = resolve_windows(chunks, WS, DUR)
    assert wins[0][0] == 0.0            # first extends to beat start
    assert wins[-1][1] == 4.0           # last extends to beat end
    assert issues == []


def test_interior_boundary_is_next_chunk_start_v1_semantics():
    # v1: chunk k ends where chunk k+1 begins (next chunk's first-word start),
    # NOT at chunk k's own last-word end. chunk0 last word (1) ends 0.9, but
    # chunk1 starts at word 3 (2.0) -> chunk0 tiles up to 2.0.
    chunks = [plate_chunk(0, 1), plate_chunk(3, 5)]
    wins, _, _diags = resolve_windows(chunks, WS, DUR)
    assert wins[0] == (0.0, 2.0)        # extended to next chunk start
    assert wins[1] == (2.0, 4.0)
    # tiling: no gaps, no overlaps
    assert wins[0][1] == wins[1][0]


def test_three_chunks_tile_without_gaps():
    chunks = [plate_chunk(0, 1), plate_chunk(2, 2), plate_chunk(3, 5)]
    wins, _, _diags = resolve_windows(chunks, WS, DUR)
    assert wins == [(0.0, 1.0), (1.0, 2.0), (2.0, 4.0)]
    for k in range(len(wins) - 1):
        assert wins[k][1] == wins[k + 1][0]


def test_pad_before_pulls_start_earlier():
    chunks = [plate_chunk(0, 1), plate_chunk(3, 5, pad_before=0.3)]
    wins, _, _diags = resolve_windows(chunks, WS, DUR)
    # chunk1 start = words[3].start(2.0) - 0.3 = 1.7; chunk0 tiles up to 1.7
    assert wins[1][0] == 1.7
    assert wins[0][1] == 1.7


def test_pad_before_clamped_to_zero_floor():
    chunks = [plate_chunk(0, 0), plate_chunk(1, 5, pad_before=99.0)]
    wins, issues, _diags = resolve_windows(chunks, WS, DUR)
    assert wins[1][0] == 0.0            # clamped to >= 0 (absurd pad absorbed)
    # chunk1 pulled to t=0 while chunk0 naturally ends at 0.4 -> an overlap,
    # which the gate surfaces rather than silently swallowing.
    assert wins[0][1] > wins[1][0]
    assert any("VQ-WORDS" in i and "overlap" in i for i in issues)


def test_pad_after_within_gap_absorbed_by_tiling():
    # pad_after that stays below the next chunk start is absorbed (v1 tiles to
    # next start) and produces no overlap.
    chunks = [plate_chunk(0, 1, pad_after=0.2), plate_chunk(3, 5)]
    wins, issues, _diags = resolve_windows(chunks, WS, DUR)
    assert wins[0][1] == 2.0           # still next chunk start (0.9+0.2 < 2.0)
    assert issues == []


def test_pad_after_overflow_flags_overlap():
    # words[1].end 0.9 + pad_after 1.5 = 2.4 > chunk1 start 2.0 -> overlap.
    chunks = [plate_chunk(0, 1, pad_after=1.5), plate_chunk(3, 5)]
    wins, issues, _diags = resolve_windows(chunks, WS, DUR)
    assert wins[0][1] > wins[1][0]
    assert any("overlap" in i and "VQ-WORDS" in i for i in issues)


def test_index_out_of_range_reported_and_clamped():
    chunks = [plate_chunk(0, 0), plate_chunk(4, 99)]
    wins, issues, diags = resolve_windows(chunks, WS, DUR)
    # does not raise; last chunk still resolves and extends to DUR
    assert wins[-1][1] == 4.0
    assert any("out of range" in i for i in issues)
    # structured CheckIssue mirrors the string (compile/check migration):
    # severity=error, code=VQ-WORDS, `where` left blank here -- the caller
    # (_compile_beat) fills it in with the beat id.
    out_of_range = [d for d in diags if d.code == "VQ-WORDS" and "out of range" in d.message]
    assert out_of_range
    assert all(d.severity == "error" and d.where == "" for d in out_of_range)


def test_word_range_reversed_reported():
    chunks = [plate_chunk(3, 1)]
    _, issues, _diags = resolve_windows(chunks, WS, DUR)
    assert any("> end index" in i for i in issues)


def test_word_ranges_overlapping_reported():
    chunks = [plate_chunk(0, 3), plate_chunk(2, 5)]
    _, issues, _diags = resolve_windows(chunks, WS, DUR)
    assert any("overlaps/precedes" in i for i in issues)


def test_empty_chunks():
    wins, issues, _diags = resolve_windows([], WS, DUR)
    assert wins == [] and issues == []
