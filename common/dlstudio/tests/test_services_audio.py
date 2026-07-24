"""services.audio: VO take processing (ffmpeg cleanup -> loudnorm chain).

Unit tests exercise the loudnorm-measure JSON parser directly against
crafted ffmpeg-shaped stderr text (no subprocess). The integration test runs
the real 3-stage chain against a synthesized sine take and checks it against
a fresh loudnorm measure pass on the output -- the same pattern
test_assemble_mix.py uses for its final-mix loudness assertion.
"""
from __future__ import annotations

import json
import math
import shutil
import subprocess
import wave
from array import array

import pytest

from dlstudio.services import ProcessResult, process_take
from dlstudio.services import audio as audio_mod

pytestmark_ffmpeg = pytest.mark.skipif(
    shutil.which("ffmpeg") is None or shutil.which("ffprobe") is None,
    reason="ffmpeg/ffprobe not on PATH",
)


# ─── loudnorm JSON parsing: unit tests (no subprocess) ─────────────────────

_SINGLE_LINE = (
    '[Parsed_loudnorm_0] {"input_i" : "-27.77", "input_tp" : "-24.06", '
    '"input_lra" : "0.00", "input_thresh" : "-37.77", "output_i" : "-14.00", '
    '"output_tp" : "-13.20", "output_lra" : "0.00", "output_thresh" : "-24.00", '
    '"normalization_type" : "dynamic", "target_offset" : "0.00"}\n'
)

_MULTILINE_NOISY = """\
frame=  120 fps=0.0 q=-1.0 size=N/A time=00:00:02.50 bitrate=N/A speed=48.2x
[Parsed_loudnorm_0 @ 0000023a0680a3c0]
{
\t"input_i" : "-14.07",
\t"input_tp" : "-10.29",
\t"input_lra" : "0.00",
\t"input_thresh" : "-24.07",
\t"output_i" : "-13.97",
\t"output_tp" : "-10.22",
\t"output_lra" : "0.00",
\t"output_thresh" : "-23.97",
\t"normalization_type" : "linear",
\t"target_offset" : "-0.03"
}
[out#0/null @ 0000023a047b3480] video:0KiB audio:675KiB subtitle:0KiB other streams:0KiB global headers:0KiB muxing overhead: unknown
size=N/A time=00:00:01.79 bitrate=N/A speed= 122x elapsed=0:00:00.01
"""


def test_parse_loudnorm_json_single_line():
    measured = audio_mod._parse_loudnorm_json(_SINGLE_LINE, stage="loudnorm measure")
    assert measured["input_i"] == "-27.77"
    assert measured["target_offset"] == "0.00"


def test_parse_loudnorm_json_multiline_noisy_stderr():
    measured = audio_mod._parse_loudnorm_json(_MULTILINE_NOISY, stage="loudnorm measure")
    assert measured["input_i"] == "-14.07"
    assert measured["input_thresh"] == "-24.07"
    assert measured["target_offset"] == "-0.03"


def test_parse_loudnorm_json_picks_last_object_when_several_present():
    noisy = (
        '{"unrelated": "first object, not the measurement"}\n'
        "some ffmpeg progress noise in between\n" + _SINGLE_LINE
    )
    measured = audio_mod._parse_loudnorm_json(noisy, stage="loudnorm measure")
    assert measured["input_i"] == "-27.77"


def test_parse_loudnorm_json_no_object_found():
    with pytest.raises(RuntimeError, match="produced no JSON object"):
        audio_mod._parse_loudnorm_json("just some ffmpeg progress text\n", stage="loudnorm measure")


def test_parse_loudnorm_json_malformed():
    # Balanced braces, but the interior isn't valid JSON (trailing comma).
    malformed = '{"input_i": "-14.0", "input_tp": "-10.0",}'
    with pytest.raises(RuntimeError, match="malformed"):
        audio_mod._parse_loudnorm_json(malformed, stage="loudnorm measure")


def test_parse_loudnorm_json_missing_required_key():
    incomplete = '{"input_i": "-14.0"}'
    with pytest.raises(RuntimeError, match="missing required key"):
        audio_mod._parse_loudnorm_json(incomplete, stage="loudnorm measure")


def test_last_json_object_returns_none_when_unbalanced():
    assert audio_mod._last_json_object('{"input_i": "-14.0"') is None


# ─── AudioStageError ────────────────────────────────────────────────────────

def test_audio_stage_error_message_includes_stage_and_stderr():
    result = subprocess.CompletedProcess(args=["ffmpeg"], returncode=1, stdout="", stderr="boom: no such filter")
    err = audio_mod.AudioStageError("cleanup (silenceremove/highpass/adeclip)", ["ffmpeg", "-y"], result)
    assert "cleanup (silenceremove/highpass/adeclip)" in str(err)
    assert "boom: no such filter" in str(err)
    assert err.stage == "cleanup (silenceremove/highpass/adeclip)"
    assert err.returncode == 1


# ─── real-ffmpeg integration ────────────────────────────────────────────────

def _sine_take(path, *, silence_ms=500, tone_dur=2.0, freq=440):
    """A synthetic 'raw recording': `silence_ms` of true silence, then a
    quiet sine tone for `tone_dur` seconds. `adelay` prepends the silence in
    a single ffmpeg call so no separate concat step is needed."""
    subprocess.run([
        "ffmpeg", "-y", "-f", "lavfi", "-i",
        f"sine=frequency={freq}:duration={tone_dur}:sample_rate=48000",
        "-af", f"adelay={silence_ms}|{silence_ms},volume=-6dB",
        "-ar", "48000", "-ac", "1", str(path),
    ], check=True, capture_output=True)


def _probe_dur(path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)], capture_output=True, text=True)
    return float(r.stdout.strip())


def _write_marker_sidecar(
    recording,
    *,
    speech_start=5.0,
    stop_requested=7.0,
    post_roll_end=8.0,
    completed_lead_in=True,
    post_roll_completed=True,
):
    sidecar = audio_mod.recording_metadata_path(recording)
    sidecar.write_text(json.dumps({
        "schema": "devlog.voice_take",
        "version": 1,
        "countdown_seconds": 3.0,
        "room_tone_seconds": 2.0,
        "speech_start_seconds": speech_start,
        "stop_requested_seconds": stop_requested,
        "post_roll_end_seconds": post_roll_end,
        "post_roll_target_seconds": 1.0,
        "post_roll_completed": post_roll_completed,
        "completed_lead_in": completed_lead_in,
    }), encoding="utf-8")
    return sidecar


def _marker_take(path, *, impulse_at=None):
    sample_rate = 48000
    samples = array("h", [0]) * (sample_rate * 8)
    tone_start = int((5.3 if impulse_at == 5.1 else 5.0) * sample_rate)
    tone_end = int(6.7 * sample_rate)
    for index in range(tone_start, tone_end):
        phase = 2 * math.pi * 440 * (index - tone_start) / sample_rate
        samples[index] = int(0.15 * 32767 * math.sin(phase))
    if impulse_at is not None:
        samples[int(impulse_at * sample_rate)] = 32767
    with wave.open(str(path), "wb") as stream:
        stream.setnchannels(1)
        stream.setsampwidth(2)
        stream.setframerate(sample_rate)
        stream.writeframes(samples.tobytes())


def _measure_lufs(path) -> float:
    r = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af",
         "loudnorm=I=-14.0:TP=-1.0:LRA=11.0:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    measured = audio_mod._parse_loudnorm_json(r.stderr, stage="test remeasure")
    return float(measured["input_i"])


@pytestmark_ffmpeg
def test_process_take_real_ffmpeg_chain(tmp_path):
    raw = tmp_path / "raw_take.wav"
    out = tmp_path / "processed.wav"
    _sine_take(raw, silence_ms=500, tone_dur=2.0)
    raw_dur = _probe_dur(raw)
    assert raw_dur == pytest.approx(2.5, abs=0.05)

    result = process_take(raw, out)

    assert isinstance(result, ProcessResult)
    assert result.out == out
    assert out.exists()

    # Stage 1 (silenceremove) should have stripped essentially all of the
    # leading 500ms of true silence -- output duration is well under the
    # raw 2.5s and not far off the 2.0s tone.
    assert result.duration < raw_dur - 0.2
    assert result.duration == pytest.approx(2.0, abs=0.3)

    # Stage 2 measurement is populated and in a sane range for a quiet tone
    # (well below the -14 LUFS target before normalization).
    assert result.input_i < -14.0

    # Re-measuring the FINAL output with an independent loudnorm pass lands
    # within +/-1.5 LU of the -14 LUFS target (the acceptance band this
    # service is expected to hit, matching test_assemble_mix.py's final-mix
    # assertion).
    remeasured = _measure_lufs(out)
    assert abs(remeasured - (-14.0)) <= 1.5, f"integrated LUFS {remeasured}"


@pytestmark_ffmpeg
def test_process_take_custom_target(tmp_path):
    raw = tmp_path / "raw_take2.wav"
    out = tmp_path / "processed2.wav"
    _sine_take(raw, silence_ms=300, tone_dur=1.5, freq=300)

    result = process_take(raw, out, target_lufs=-16.0, true_peak_db=-1.5, lra=7.0)
    remeasured_r = subprocess.run(
        ["ffmpeg", "-i", str(out), "-af",
         "loudnorm=I=-16.0:TP=-1.5:LRA=7.0:print_format=json", "-f", "null", "-"],
        capture_output=True, text=True,
    )
    measured = audio_mod._parse_loudnorm_json(remeasured_r.stderr, stage="test remeasure")
    assert abs(float(measured["input_i"]) - (-16.0)) <= 1.5
    assert result.duration > 0


def test_load_voice_take_markers_validates_timing_contract(tmp_path):
    raw = tmp_path / "raw.webm"
    raw.write_bytes(b"raw")
    sidecar = _write_marker_sidecar(raw)

    markers = audio_mod.load_voice_take_markers(raw)

    assert markers is not None
    assert markers.path == sidecar
    assert markers.speech_start_seconds == 5.0
    assert markers.stop_requested_seconds == 7.0


def test_load_voice_take_markers_rejects_unordered_markers(tmp_path):
    raw = tmp_path / "raw.webm"
    raw.write_bytes(b"raw")
    _write_marker_sidecar(raw, stop_requested=4.0, post_roll_end=8.0)

    with pytest.raises(ValueError, match="stop marker precedes speech start"):
        audio_mod.load_voice_take_markers(raw)


@pytestmark_ffmpeg
def test_process_take_applies_marker_trim_and_persists_verdict(tmp_path):
    raw = tmp_path / "marker_take.wav"
    out = tmp_path / "processed.wav"
    verdict_path = tmp_path / "review" / "take.json"
    _marker_take(raw)
    _write_marker_sidecar(raw)

    result = process_take(raw, out, verdict_path=verdict_path)

    assert result.marker_status == "applied"
    assert result.trim_start == pytest.approx(4.75)
    assert result.trim_end == pytest.approx(6.90)
    assert result.duration == pytest.approx(1.70, abs=0.15)
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert verdict["verdict"] == "pass"
    assert verdict["selection"]["applied"] is True
    assert verdict["boundary_qc"]["start"]["clipping"] is False
    assert verdict["boundary_qc"]["start"]["impulse"] is False
    assert verdict["boundary_qc"]["tail"]["impulse"] is False
    assert len(verdict["artifact_sha256"]) == 64


@pytestmark_ffmpeg
def test_process_take_blocks_start_impulse_and_persists_rejection(tmp_path):
    raw = tmp_path / "clicked_take.wav"
    out = tmp_path / "processed.wav"
    verdict_path = tmp_path / "review" / "take.json"
    _marker_take(raw, impulse_at=5.1)
    _write_marker_sidecar(raw)
    out.write_bytes(b"previous-good-take")

    with pytest.raises(audio_mod.VoiceTakeQualityError, match="START-IMPULSE"):
        process_take(raw, out, verdict_path=verdict_path)

    assert out.read_bytes() == b"previous-good-take"
    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert verdict["verdict"] == "block"
    assert verdict["boundary_qc"]["start"]["impulse"] is True
    assert any(
        issue["code"] == "VQ-AUDIO-START-IMPULSE"
        for issue in verdict["issues"]
    )


@pytestmark_ffmpeg
def test_process_take_excludes_click_at_stop_marker(tmp_path):
    raw = tmp_path / "stop_clicked_take.wav"
    out = tmp_path / "processed.wav"
    _marker_take(raw, impulse_at=7.0)
    _write_marker_sidecar(raw)

    result = process_take(raw, out)

    assert result.verdict["verdict"] == "pass"
    assert result.trim_end == pytest.approx(6.90)
    assert result.verdict["boundary_qc"]["tail"]["impulse"] is False


@pytestmark_ffmpeg
def test_process_take_rejects_incomplete_markers(tmp_path):
    raw = tmp_path / "incomplete_take.wav"
    out = tmp_path / "processed.wav"
    verdict_path = tmp_path / "review" / "take.json"
    _marker_take(raw)
    _write_marker_sidecar(raw, post_roll_completed=False)

    with pytest.raises(audio_mod.VoiceTakeQualityError, match="incomplete"):
        process_take(raw, out, verdict_path=verdict_path)

    verdict = json.loads(verdict_path.read_text(encoding="utf-8"))
    assert verdict["verdict"] == "block"
    assert verdict["recommended_action"] == "re_record"
    assert verdict["issues"][0]["code"] == "VQ-AUDIO-MARKERS-INCOMPLETE"


@pytestmark_ffmpeg
def test_process_take_missing_recording_raises(tmp_path):
    with pytest.raises(FileNotFoundError):
        process_take(tmp_path / "does_not_exist.wav", tmp_path / "out.wav")


@pytestmark_ffmpeg
def test_process_take_bad_input_raises_audio_stage_error(tmp_path):
    bogus = tmp_path / "not_audio.wav"
    bogus.write_text("this is not a real wav file", encoding="utf-8")
    with pytest.raises(audio_mod.AudioStageError) as excinfo:
        process_take(bogus, tmp_path / "out.wav")
    assert excinfo.value.stage in {
        "marker selection",
        "cleanup (silenceremove/highpass/adeclip)",
    }
