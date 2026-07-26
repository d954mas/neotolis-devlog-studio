"""Deterministic script/VO preflight service tests (no AI runtime)."""
from __future__ import annotations

import math
import struct
import wave
from types import SimpleNamespace

import pytest

from dlstudio.services.script_preflight import (
    ApprovalRecord,
    CreatorProfile,
    approve_script,
    canonical_script_text,
    check_wav_first_3s,
    find_duplicate_sentences,
    lint_script,
    load_creator_profile,
    scan_transcript_proper_names,
    script_sha256,
    verify_script_approval,
)


def test_load_creator_profile_from_toml(tmp_path):
    profile_path = tmp_path / "creator_profile.toml"
    profile_path.write_text(
        """
[voice]
first_person = "singular"
max_sentence_words = 12
forbidden_cliches = ["В современном мире"]
forbidden_terms = ["революционный"]

[brand_spellings]
"Neotolis" = ["неотолис", "Neo Tolis"]
"Not a Trolley Problem" = ["Not A Trolley problem"]

[transcript]
proper_names = ["Not a Trolley Problem", "Neotolis", "Steam"]
""".strip(),
        encoding="utf-8",
    )

    profile = load_creator_profile(profile_path)

    assert profile.first_person == "singular"
    assert profile.max_sentence_words == 12
    assert profile.forbidden_cliches == ("В современном мире",)
    assert profile.forbidden_terms == ("революционный",)
    assert profile.brand_spellings["Neotolis"] == ("неотолис", "Neo Tolis")
    assert profile.proper_names == ("Not a Trolley Problem", "Neotolis", "Steam")


def test_creator_profile_rejects_invalid_first_person(tmp_path):
    path = tmp_path / "creator_profile.toml"
    path.write_text('[voice]\nfirst_person = "plural"\n', encoding="utf-8")

    with pytest.raises(ValueError, match="first_person"):
        load_creator_profile(path)


def test_natural_script_lint_enforces_solo_voice_banned_language_and_brand_spelling():
    profile = CreatorProfile(
        first_person="singular",
        max_sentence_words=20,
        forbidden_cliches=("В современном мире",),
        forbidden_terms=("революционный",),
        brand_spellings={"Neotolis": ("неотолис",)},
    )
    script = (
        "Мы сделали революционный прототип. "
        "В современном мире это звучит привычно. "
        "Подробнее я рассказал в неотолис."
    )

    result = lint_script(script, profile)

    assert not result.ok
    assert {issue.code for issue in result.issues} == {
        "VQ-SCRIPT-VOICE",
        "VQ-SCRIPT-TERM",
        "VQ-SCRIPT-AI",
        "VQ-SCRIPT-BRAND",
    }


def test_brand_alias_is_reported_even_when_canonical_spelling_also_appears():
    profile = CreatorProfile(brand_spellings={"Neotolis": ("неотолис",)})

    result = lint_script("Я открыл Neotolis. В речи неотолис иногда путают.", profile)

    assert [issue.value for issue in result.issues if issue.code == "VQ-SCRIPT-BRAND"] == ["неотолис"]


def test_natural_script_lint_reports_long_sentence_and_duplicate():
    profile = CreatorProfile(max_sentence_words=5)
    script = "Я сделал новый движок полностью с нуля. Я выбрал другой путь! Я выбрал другой путь."

    result = lint_script(script, profile)

    assert [issue.code for issue in result.issues].count("VQ-SCRIPT-LENGTH") == 1
    assert [issue.code for issue in result.issues].count("VQ-SCRIPT-DENSITY") == 1


def test_find_duplicate_sentences_ignores_case_spacing_and_terminal_punctuation():
    duplicates = find_duplicate_sentences(
        "Я выбрал этот путь.  Другой факт. я   выбрал этот путь!"
    )

    assert len(duplicates) == 1
    assert duplicates[0].first_index == 0
    assert duplicates[0].duplicate_index == 2
    assert duplicates[0].sentence == "я выбрал этот путь"


def test_script_approval_hash_is_exact_and_detects_any_edit():
    script = "Я сделал новый движок."
    record = approve_script(
        script,
        script_id="devlog-01-r3",
        approved_by="creator",
        approved_at="2026-07-18T09:00:00Z",
    )

    assert record.script_sha256 == script_sha256(script)
    assert verify_script_approval(script, record, script_id="devlog-01-r3").ok
    changed = verify_script_approval(script + "\n", record, script_id="devlog-01-r3")
    assert not changed.ok
    assert changed.issue is not None
    assert changed.issue.code == "VQ-SCRIPT-APPROVAL"


def test_canonical_script_text_is_stable_and_includes_beat_ids():
    edit = SimpleNamespace(
        order=["b01", "b02"],
        beats={
            "b01": SimpleNamespace(vo="Первая фраза."),
            "b02": SimpleNamespace(vo=None),
        },
    )

    assert canonical_script_text(edit) == "## b01\nПервая фраза.\n\n## b02\n"


def test_approval_record_dict_round_trip_and_script_id_lineage():
    record = ApprovalRecord(
        script_id="reel-07",
        script_sha256="a" * 64,
        approved_by="creator",
        approved_at="2026-07-18T09:00:00Z",
    )

    restored = ApprovalRecord.from_dict(record.to_dict())

    assert restored == record
    assert not verify_script_approval("text", restored, script_id="other-reel").ok


def test_transcript_proper_name_scan_accepts_contiguous_tokens_case_insensitively():
    transcript = {
        "words": [
            {"word": "not", "start": 0.0, "end": 0.1},
            {"word": "a", "start": 0.1, "end": 0.2},
            {"word": "trolley", "start": 0.2, "end": 0.3},
            {"word": "problem,", "start": 0.3, "end": 0.4},
            {"word": "Neotolis", "start": 0.4, "end": 0.5},
            {"word": "Steam.", "start": 0.5, "end": 0.6},
        ]
    }

    result = scan_transcript_proper_names(
        transcript, ("Not a Trolley Problem", "Neotolis", "Steam")
    )

    assert result.ok
    assert result.missing == ()


def test_transcript_proper_name_scan_flags_garbled_or_missing_name():
    transcript = [{"word": "Not"}, {"word": "a"}, {"word": "train"}, {"word": "problem"}]

    result = scan_transcript_proper_names(
        transcript, ("Not a Trolley Problem", "Neotolis")
    )

    assert not result.ok
    assert result.missing == ("Not a Trolley Problem", "Neotolis")
    assert all(issue.code == "VQ-TRANSCRIPT-PROPER" for issue in result.issues)


def _write_wav(path, samples, *, sample_rate=8_000):
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(sample_rate)
        wav.writeframes(struct.pack(f"<{len(samples)}h", *samples))


def _sine_samples(*, seconds=3.0, sample_rate=8_000, amplitude=2_000, frequency=220.0):
    return [
        int(amplitude * math.sin(2.0 * math.pi * frequency * i / sample_rate))
        for i in range(int(seconds * sample_rate))
    ]


def test_wav_first_three_seconds_clean_signal_passes(tmp_path):
    wav_path = tmp_path / "clean.wav"
    _write_wav(wav_path, _sine_samples())

    result = check_wav_first_3s(wav_path)

    assert result.ok
    assert not result.clipping
    assert not result.impulse
    assert not result.noise_jump
    assert result.analyzed_seconds == pytest.approx(3.0)


def test_wav_first_three_seconds_detects_clipping_as_blocker(tmp_path):
    wav_path = tmp_path / "clipped.wav"
    samples = _sine_samples(amplitude=2_000)
    samples[500:510] = [32_767] * 10
    _write_wav(wav_path, samples)

    result = check_wav_first_3s(wav_path)

    assert result.clipping
    assert not result.ok
    assert any(i.code == "VQ-AUDIO-START-CLIPPING" and i.severity == "error" for i in result.issues)


def test_wav_first_three_seconds_detects_single_sample_impulse_as_blocker(tmp_path):
    wav_path = tmp_path / "click.wav"
    samples = [0] * (3 * 8_000)
    samples[4_000] = 28_000
    _write_wav(wav_path, samples)

    result = check_wav_first_3s(wav_path)

    assert result.impulse
    assert not result.ok
    assert any(i.code == "VQ-AUDIO-START-IMPULSE" and i.severity == "error" for i in result.issues)


def test_wav_first_three_seconds_detects_broad_sub_full_scale_click(tmp_path):
    wav_path = tmp_path / "broad_click.wav"
    samples = [0] * (3 * 8_000)
    samples[4_000:4_050] = [12_000] * 50
    _write_wav(wav_path, samples)

    result = check_wav_first_3s(wav_path)

    assert result.impulse
    assert not result.ok
    assert any(i.code == "VQ-AUDIO-START-IMPULSE" for i in result.issues)


def test_wav_first_three_seconds_reports_noise_jump_as_warning(tmp_path):
    wav_path = tmp_path / "noise_jump.wav"
    quiet = _sine_samples(seconds=1.0, amplitude=200, frequency=997.0)
    loud = _sine_samples(seconds=2.0, amplitude=2_000, frequency=997.0)
    _write_wav(wav_path, quiet + loud)

    result = check_wav_first_3s(wav_path)

    assert result.noise_jump
    assert result.ok  # a noise-floor jump warns; impulse/clipping are blockers
    assert any(i.code == "VQ-AUDIO-START-NOISE" and i.severity == "warning" for i in result.issues)


def test_wav_first_three_seconds_rejects_non_pcm_compression(tmp_path):
    path = tmp_path / "not-a-wave.wav"
    path.write_bytes(b"not a wave")

    with pytest.raises((wave.Error, EOFError)):
        check_wav_first_3s(path)
