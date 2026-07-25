"""Automatic speech-edit planning and transcript remapping."""
from __future__ import annotations

import json
import math
import shutil
import wave
from pathlib import Path

import pytest

from dlstudio.services import speech_edit as speech_edit_mod
from dlstudio.services.speech_edit import (
    SpeechCut,
    SpeechEditPlan,
    SpeechEditStageError,
    execute_speech_edit,
    build_automatic_plan,
    parse_silencedetect,
    remap_words_payload,
    resolve_safe_cuts,
    sha256_file,
)


def _payload(words: list[tuple[str, float, float]], *, duration: float = 3.0) -> dict:
    return {
        "audio": "raw.wav",
        "duration": duration,
        "language": "ru",
        "text": " ".join(word for word, _, _ in words),
        "words": [
            {"word": word, "start": start, "end": end, "prob": 0.99}
            for word, start, end in words
        ],
    }


def _pcm_take(path, *, duration: float, voiced_ranges: list[tuple[float, float]]) -> None:
    frame_count = round(duration * 48_000)
    with wave.open(str(path), "wb") as wav:
        wav.setnchannels(1)
        wav.setsampwidth(2)
        wav.setframerate(48_000)
        samples = bytearray()
        for index in range(frame_count):
            second = index / 48_000
            voiced = any(start <= second < end for start, end in voiced_ranges)
            value = (
                int(8_000 * math.sin(2 * math.pi * 220 * second))
                if voiced else 0
            )
            samples.extend(value.to_bytes(2, byteorder="little", signed=True))
        wav.writeframes(samples)


def test_parse_silencedetect_pairs_ranges_and_closes_trailing_silence():
    stderr = """
    [silencedetect @ 1] silence_start: 0.42
    [silencedetect @ 1] silence_end: 1.31 | silence_duration: 0.89
    [silencedetect @ 1] silence_start: 2.5
    """

    assert parse_silencedetect(stderr, audio_duration=3.0) == [
        (0.42, 1.31),
        (2.5, 3.0),
    ]


def test_automatic_plan_preserves_repetition_without_semantic_evidence():
    payload = _payload([
        ("Мы", 0.00, 0.20),
        ("строим", 0.22, 0.50),
        ("город", 0.52, 0.78),
        ("э", 0.90, 1.02),
        ("строим", 1.20, 1.46),
        ("город", 1.48, 1.75),
        ("быстро", 1.78, 2.05),
    ])

    plan = build_automatic_plan(
        payload,
        source_duration=3.0,
        signal_silences=[(2.10, 2.80)],
        audio_sha256="a" * 64,
        words_sha256="b" * 64,
    )

    reasons = {reason for cut in plan.cuts for reason in cut.reasons}
    assert {"filler", "silence"} <= reasons
    assert "exact_phrase_repeat" not in reasons
    assert plan.input_audio_sha256 == "a" * 64
    assert plan.input_words_sha256 == "b" * 64
    assert plan.output_duration == pytest.approx(
        plan.source_duration - plan.removed_duration
    )
    assert all(cut.t1 > cut.t0 for cut in plan.cuts)
    assert SpeechEditPlan.from_dict(plan.to_dict()) == plan


def test_remap_words_removes_cut_tokens_and_shifts_remaining_timestamps():
    payload = _payload([
        ("первая", 0.00, 0.30),
        ("э", 0.50, 0.62),
        ("вторая", 1.20, 1.55),
    ], duration=2.0)
    cuts = [SpeechCut(t0=0.40, t1=1.00, reasons=("filler",), sources=("agent",))]

    remapped = remap_words_payload(payload, cuts, output_audio="edited.wav")

    assert remapped["audio"] == "edited.wav"
    assert remapped["duration"] == pytest.approx(1.4)
    assert remapped["text"] == "первая вторая"
    assert remapped["words"] == [
        {"word": "первая", "start": 0.0, "end": 0.3, "prob": 0.99},
        {"word": "вторая", "start": 0.6, "end": 0.95, "prob": 0.99},
    ]
    # The result remains ordinary words.json and is JSON serializable.
    json.dumps(remapped, ensure_ascii=False)


def test_remap_rejects_overlapping_or_out_of_bounds_cuts():
    payload = _payload([("слово", 0.2, 0.5)], duration=1.0)

    with pytest.raises(ValueError, match="overlap"):
        remap_words_payload(payload, [
            SpeechCut(t0=0.1, t1=0.4, reasons=("a",), sources=("agent",)),
            SpeechCut(t0=0.3, t1=0.6, reasons=("b",), sources=("agent",)),
        ])

    with pytest.raises(ValueError, match="duration"):
        remap_words_payload(payload, [
            SpeechCut(t0=0.8, t1=1.1, reasons=("a",), sources=("agent",)),
        ])

    with pytest.raises(ValueError, match="splits word"):
        remap_words_payload(payload, [
            SpeechCut(t0=0.4, t1=0.8, reasons=("a",), sources=("agent",)),
        ])


def test_resolve_safe_cuts_snaps_to_quiet_word_gaps_and_skips_unsafe_edits(tmp_path):
    payload = _payload([
        ("оставить", 0.10, 0.30),
        ("удалить", 0.55, 0.75),
        ("оставить", 1.00, 1.25),
    ], duration=1.5)
    safe_audio = tmp_path / "safe.wav"
    _pcm_take(
        safe_audio,
        duration=1.5,
        voiced_ranges=[(0.08, 0.32), (0.53, 0.77), (0.98, 1.27)],
    )
    requested = SpeechCut(
        t0=0.55, t1=0.75, reasons=("false_start",), sources=("agent",),
    )

    resolved = resolve_safe_cuts(safe_audio, payload, [requested])

    assert len(resolved.applied) == 1
    assert resolved.skipped == ()
    assert 0.34 <= resolved.applied[0].t0 <= 0.55
    assert 0.75 <= resolved.applied[0].t1 <= 0.96
    assert all(boundary.rms_dbfs <= -30.0 for boundary in resolved.boundaries)

    loud_audio = tmp_path / "loud.wav"
    _pcm_take(loud_audio, duration=1.5, voiced_ranges=[(0.0, 1.5)])
    unsafe = resolve_safe_cuts(loud_audio, payload, [requested])
    assert unsafe.applied == ()
    assert unsafe.skipped[0].reason == "no_quiet_boundary"

    split_word = resolve_safe_cuts(loud_audio, payload, [SpeechCut(
        t0=0.20, t1=0.40, reasons=("semantic",), sources=("agent",),
    )])
    assert split_word.applied == ()
    assert split_word.skipped[0].reason == "splits_word"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_execute_speech_edit_materializes_wav_words_and_audit_artifact(tmp_path):
    source_audio = tmp_path / "source.wav"
    _pcm_take(
        source_audio,
        duration=2.0,
        voiced_ranges=[(0.05, 0.37), (0.58, 0.82), (1.20, 1.60)],
    )

    source_words = tmp_path / "source_words.json"
    source_words.write_text(json.dumps(_payload([
        ("первая", 0.10, 0.35),
        ("лишняя", 0.60, 0.80),
        ("вторая", 1.25, 1.55),
    ], duration=2.0), ensure_ascii=False), encoding="utf-8")
    plan = SpeechEditPlan(
        source_duration=2.0,
        cuts=(SpeechCut(
            t0=0.50, t1=1.10, reasons=("semantic",), sources=("agent",),
        ),),
        input_audio_sha256=sha256_file(source_audio),
        input_words_sha256=sha256_file(source_words),
    )
    out_audio = tmp_path / "edited.wav"
    out_words = tmp_path / "edited_words.json"
    artifact = tmp_path / "speech_edit.json"

    result = execute_speech_edit(
        source_audio, source_words, out_audio, out_words, artifact, plan=plan,
        output_audio_ref="data/audio/edited.wav",
        output_words_ref="data/audio/edited_words.json",
    )

    assert result.duration == pytest.approx(1.388, abs=1 / 48_000)
    with wave.open(str(out_audio), "rb") as wav:
        assert wav.getframerate() == 48_000
        assert wav.getnchannels() == 1
        assert wav.getnframes() == pytest.approx(66_624, abs=1)
    remapped = json.loads(out_words.read_text(encoding="utf-8"))
    assert remapped["audio"] == "data/audio/edited.wav"
    assert [word["word"] for word in remapped["words"]] == ["первая", "вторая"]
    assert remapped["words"][1]["start"] == pytest.approx(0.638)
    audit = json.loads(artifact.read_text(encoding="utf-8"))
    assert audit["schema"] == "dlstudio.speech-edit/v1"
    assert audit["maps"]["old_to_new"] == [0, None, 1]
    assert audit["resolution"]["skipped_cuts"] == []
    assert audit["joins"][0]["crossfade_samples"] == 576
    assert audit["joins"][0]["max_step_dbfs"] <= -30.0
    assert audit["output"]["audio_sha256"] == sha256_file(out_audio)
    assert audit["output"]["words_sha256"] == sha256_file(out_words)
    assert audit["output"]["words_path"] == "data/audio/edited_words.json"
    assert Path(audit["input"]["audio_path"]).is_file()
    assert Path(audit["input"]["words_path"]).is_file()


def test_execute_speech_edit_rejects_stale_hash_before_writing(tmp_path):
    source_audio = tmp_path / "source.wav"
    source_audio.write_bytes(b"changed")
    source_words = tmp_path / "source_words.json"
    source_words.write_text(json.dumps(_payload([], duration=1.0)), encoding="utf-8")
    plan = SpeechEditPlan(
        source_duration=1.0,
        cuts=(),
        input_audio_sha256="0" * 64,
        input_words_sha256=sha256_file(source_words),
    )

    with pytest.raises(ValueError, match="audio hash"):
        execute_speech_edit(
            source_audio, source_words,
            tmp_path / "edited.wav", tmp_path / "edited_words.json",
            tmp_path / "speech_edit.json", plan=plan,
        )
    assert not (tmp_path / "edited.wav").exists()


def test_execute_speech_edit_retains_unsafe_cut_instead_of_guessing(tmp_path):
    source_audio = tmp_path / "continuous_speech.wav"
    _pcm_take(source_audio, duration=1.5, voiced_ranges=[(0.0, 1.5)])
    payload = _payload([
        ("до", 0.10, 0.30),
        ("сомнительно", 0.55, 0.75),
        ("после", 1.00, 1.25),
    ], duration=1.5)
    source_words = tmp_path / "source_words.json"
    source_words.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    plan = SpeechEditPlan(
        source_duration=1.5,
        cuts=(SpeechCut(
            t0=0.55, t1=0.75, reasons=("semantic",), sources=("agent",),
        ),),
        input_audio_sha256=sha256_file(source_audio),
        input_words_sha256=sha256_file(source_words),
    )
    out_audio = tmp_path / "edited.wav"
    out_words = tmp_path / "edited_words.json"
    artifact = tmp_path / "speech_edit.json"

    result = execute_speech_edit(
        source_audio, source_words, out_audio, out_words, artifact, plan=plan,
    )

    assert result.cut_count == 0
    assert result.skipped_cut_count == 1
    assert sha256_file(out_audio) == sha256_file(source_audio)
    remapped = json.loads(out_words.read_text(encoding="utf-8"))
    assert [word["word"] for word in remapped["words"]] == [
        "до", "сомнительно", "после",
    ]
    audit = json.loads(artifact.read_text(encoding="utf-8"))
    assert audit["resolution"]["skipped_cuts"][0]["reason"] == "no_quiet_boundary"


@pytest.mark.skipif(shutil.which("ffmpeg") is None, reason="ffmpeg not on PATH")
def test_failed_join_continuity_never_publishes_partial_bundle(tmp_path, monkeypatch):
    source_audio = tmp_path / "source.wav"
    _pcm_take(
        source_audio,
        duration=1.5,
        voiced_ranges=[(0.05, 0.32), (0.55, 0.77), (1.0, 1.28)],
    )
    source_words = tmp_path / "source_words.json"
    source_words.write_text(json.dumps(_payload([
        ("до", 0.10, 0.30),
        ("удалить", 0.57, 0.75),
        ("после", 1.02, 1.25),
    ], duration=1.5), ensure_ascii=False), encoding="utf-8")
    plan = SpeechEditPlan(
        source_duration=1.5,
        cuts=(SpeechCut(
            t0=0.50, t1=0.82, reasons=("repeat",), sources=("agent",),
        ),),
        input_audio_sha256=sha256_file(source_audio),
        input_words_sha256=sha256_file(source_words),
    )
    out_audio = tmp_path / "edited.wav"
    out_words = tmp_path / "edited_words.json"
    artifact = tmp_path / "speech_edit.json"

    def reject_join(*_args, **_kwargs):
        raise SpeechEditStageError("simulated audible join")

    monkeypatch.setattr(speech_edit_mod, "inspect_join_continuity", reject_join)
    with pytest.raises(SpeechEditStageError, match="audible join"):
        execute_speech_edit(
            source_audio, source_words, out_audio, out_words, artifact, plan=plan,
        )

    assert not out_audio.exists()
    assert not out_words.exists()
    assert not artifact.exists()
