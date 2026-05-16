from pathlib import Path

from devlog.script_import import chunk_script_text, parse_script_beats, render_beats_py


def test_parse_script_beats_uses_markdown_headings():
    beats = parse_script_beats("# Intro\nHello world.\n\n## Proof\nSecond part.")

    assert [b.beat_id for b in beats] == ["intro", "proof"]
    assert beats[0].title == "Intro"
    assert beats[1].vo == "Second part."


def test_parse_script_beats_splits_paragraphs_without_headings():
    beats = parse_script_beats("First idea.\n\nSecond idea.", prefix="beat")

    assert [b.beat_id for b in beats] == ["first_idea", "second_idea"]
    assert beats[0].title == "First idea"


def test_render_beats_py_is_importable(tmp_path: Path):
    beats = parse_script_beats("# Intro\nHello world. Second sentence here.")
    content = render_beats_py(beats, max_chunk_words=4)
    path = tmp_path / "beats.py"
    path.write_text(content, encoding="utf-8")

    namespace: dict[str, object] = {}
    exec(compile(content, str(path), "exec"), namespace)

    assert namespace["CONCAT_ORDER"] == ["intro"]
    assert namespace["OUTPUT"] == "data/finalize/iter01.mp4"
    assert namespace["BEATS"]["intro"].chunks[0].words == (0, 1)
    assert namespace["BEATS"]["intro"].chunks[1].words == (2, 4)


def test_chunk_script_text_splits_long_sentences_by_word_limit():
    chunks = chunk_script_text("one two three four five six", max_words=4)

    assert [c.text for c in chunks] == ["one two three four", "five six"]
    assert chunks[0].start_word == 0
    assert chunks[0].end_word == 3
    assert chunks[1].start_word == 4
    assert chunks[1].end_word == 5
