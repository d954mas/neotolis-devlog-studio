from pathlib import Path

from devlog.script_import import parse_script_beats, render_beats_py


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
    beats = parse_script_beats("# Intro\nHello world.")
    content = render_beats_py(beats)
    path = tmp_path / "beats.py"
    path.write_text(content, encoding="utf-8")

    namespace: dict[str, object] = {}
    exec(compile(content, str(path), "exec"), namespace)

    assert namespace["CONCAT_ORDER"] == ["intro"]
    assert namespace["OUTPUT"] == "data/finalize/iter01.mp4"
    assert namespace["BEATS"]["intro"].chunks[0].words == (0, 1)
