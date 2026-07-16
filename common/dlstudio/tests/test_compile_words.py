"""Words JSON parsing (v1 schema)."""
from __future__ import annotations

import pytest

from _builders import WORDS_BASIC
from dlstudio.compile.words import load_words, parse_words


def test_load_words_from_fixture():
    ws = load_words(str(WORDS_BASIC))
    assert len(ws) == 6
    assert ws[0].text == "hello"
    assert ws[0].t0 == 0.0
    assert ws[0].t1 == 0.4
    assert ws[3].text == "world"
    assert ws[3].t0 == 2.0
    assert ws[-1].t1 == 3.4


def test_parse_words_minimal():
    ws = parse_words('{"words":[{"word":"hi","start":1.0,"end":1.5}]}')
    assert len(ws) == 1
    assert (ws[0].text, ws[0].t0, ws[0].t1) == ("hi", 1.0, 1.5)


def test_parse_words_ignores_extra_fields():
    # v1 words carry a "prob" and the doc carries audio/duration/text — ignored.
    raw = ('{"audio":"a.wav","duration":9.9,"language":"ru","text":"hi",'
           '"words":[{"word":"hi","start":0.0,"end":0.4,"prob":0.7}]}')
    ws = parse_words(raw)
    assert len(ws) == 1 and ws[0].text == "hi"


def test_parse_words_missing_words_key():
    with pytest.raises(ValueError, match="missing top-level 'words'"):
        parse_words('{"audio":"a.wav"}')


def test_parse_words_not_json():
    with pytest.raises(ValueError, match="not valid JSON"):
        parse_words("not json at all")


def test_parse_words_malformed_word_entry():
    with pytest.raises(ValueError, match="word #0 malformed"):
        parse_words('{"words":[{"word":"hi","start":0.0}]}')
