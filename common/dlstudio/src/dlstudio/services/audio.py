"""VO take processing: raw recording -> loudness-normalized wav.

Ports the audio-normalization side of legacy common/devlog/audio/process.py's
four-stage chain (stage 4, transcription, is services/transcribe.py instead —
kept as a separate service so callers can process audio and transcribe words
independently, or swap either one out):

  1. cleanup   silenceremove (leading silence) + highpass (rumble) + adeclip
               (declick/decrackle), forced mono/48kHz/s16.
  2. measure   loudnorm pass 1 (`print_format=json`, written to ffmpeg's
               stderr) -- analyzes the cleaned audio's loudness profile.
  3. apply     loudnorm pass 2, fed the pass-1 measured_* values plus
               `linear=true` -- the legacy two-pass pattern is materially
               more accurate than a single dynamic loudnorm pass.

Target -14 LUFS / -1 dBTP matches YouTube's spoken-word loudness
recommendation (same defaults as legacy).

All ffmpeg invocations are list-arg subprocess calls -- no shell=True, no
string-interpolated command lines.

Improvement over legacy (this is the Phase-4 services rebuild, see
docs/ARCHITECTURE_V2.md): every stage raises a clear `AudioStageError` with a
stderr excerpt and the stage name on failure, instead of legacy's
`raise SystemExit(f"...: {r.stderr}")` (SystemExit bypasses normal exception
handling and callers only ever saw a bare, unlabeled stderr dump). The
loudnorm-measure JSON parse also no longer relies on a regex match against a
single located `{...}` span -- see `_last_json_object` below, which scans
brace-depth across the whole output and always returns the LAST balanced
top-level object, robust to noisy/multi-line ffmpeg output regardless of
where in the stream the object starts.
"""
from __future__ import annotations

import json
import shutil
import subprocess
import tempfile
from dataclasses import dataclass
from pathlib import Path

_REQUIRED_MEASURE_KEYS = ("input_i", "input_tp", "input_lra", "input_thresh", "target_offset")


@dataclass(frozen=True)
class ProcessResult:
    """Outcome of `process_take()`.

    `input_i`/`input_tp`/`input_lra`/`input_thresh` are the pass-1 loudnorm
    measurement of the *cleaned* (stage 1) audio, in the filter's own units
    (LUFS, dBTP, LU, LUFS respectively) -- exposed so callers/tests can
    confirm the measured input was in a sane range and so the apply stage's
    inputs are inspectable without re-parsing ffmpeg output. `duration` is
    the final output's ffprobe duration in seconds.
    """

    out: Path
    input_i: float
    input_tp: float
    input_lra: float
    input_thresh: float
    duration: float


class AudioStageError(RuntimeError):
    """One ffmpeg stage of `process_take` exited non-zero. Carries the stage
    label, the failing command, and a trimmed stderr excerpt so the error
    message alone is actionable (which stage, what ffmpeg said)."""

    def __init__(self, stage: str, cmd: list[str], result: subprocess.CompletedProcess) -> None:
        excerpt = (result.stderr or result.stdout or "")[-1500:]
        super().__init__(
            f"process_take: ffmpeg stage {stage!r} failed (rc={result.returncode}).\n"
            f"cmd: {' '.join(cmd)}\n"
            f"stderr (tail):\n{excerpt}"
        )
        self.stage = stage
        self.cmd = cmd
        self.returncode = result.returncode
        self.stderr = result.stderr


def _run(cmd: list[str], *, stage: str) -> subprocess.CompletedProcess:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace")
    except FileNotFoundError as e:
        raise RuntimeError(
            f"process_take: {cmd[0]!r} not found on PATH (stage {stage!r})"
        ) from e
    if r.returncode != 0:
        raise AudioStageError(stage, cmd, r)
    return r


def _last_json_object(text: str) -> str | None:
    """Return the LAST top-level brace-balanced `{...}` substring in `text`,
    or None if no balanced object exists.

    A brace-depth scan rather than a regex: ffmpeg's loudnorm filter
    pretty-prints its measurement JSON across multiple lines, interleaved
    with normal per-frame progress noise before it and nothing after it, so
    scanning for balanced braces (instead of matching within a single line)
    tolerates the real multi-line output. Depth-0 objects are recorded as we
    go; the last one found wins, which is always the loudnorm block since
    ffmpeg writes nothing to stderr after it in `-f null` measure mode.
    """
    depth = 0
    start: int | None = None
    last: str | None = None
    for i, ch in enumerate(text):
        if ch == "{":
            if depth == 0:
                start = i
            depth += 1
        elif ch == "}":
            if depth > 0:
                depth -= 1
                if depth == 0 and start is not None:
                    last = text[start : i + 1]
                    start = None
    return last


def _parse_loudnorm_json(output: str, *, stage: str) -> dict:
    """Extract and validate the loudnorm measure JSON block from ffmpeg's
    stderr (or stdout, if the caller merged the two). Raises a clear
    RuntimeError -- naming the stage, and including an output excerpt -- if
    no balanced object is found, the object isn't valid JSON, or it's
    missing a key the apply stage needs."""
    blob = _last_json_object(output)
    if blob is None:
        raise RuntimeError(
            f"process_take: {stage} produced no JSON object in ffmpeg's output; "
            f"tail:\n{output[-800:]}"
        )
    try:
        data = json.loads(blob)
    except json.JSONDecodeError as e:
        raise RuntimeError(
            f"process_take: {stage} JSON block is malformed ({e}); block:\n{blob}"
        ) from e
    if not isinstance(data, dict):
        raise RuntimeError(
            f"process_take: {stage} JSON block is not an object: {blob!r}"
        )
    missing = [k for k in _REQUIRED_MEASURE_KEYS if k not in data]
    if missing:
        raise RuntimeError(
            f"process_take: {stage} JSON is missing required key(s) "
            f"{missing}: {blob}"
        )
    return data


def _probe_duration(path: Path) -> float:
    r = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True,
        encoding="utf-8", errors="replace",
    )
    try:
        return float(r.stdout.strip())
    except ValueError as e:
        raise RuntimeError(
            f"process_take: ffprobe could not read duration of {path}: "
            f"{(r.stderr or r.stdout)[-500:]}"
        ) from e


def process_take(
    recording: Path,
    out_wav: Path,
    *,
    target_lufs: float = -14.0,
    true_peak_db: float = -1.0,
    lra: float = 11.0,
    sample_rate: int = 48000,
) -> ProcessResult:
    """Process one raw take recording into a loudness-normalized wav.

    Runs the 3-stage ffmpeg chain (cleanup -> loudnorm measure -> loudnorm
    apply) documented at module scope, and writes the result to `out_wav`
    (parent directories created as needed). Intermediate/cleaned audio is
    written to a temp dir that is removed on return, matching the
    render/beat.py `tempfile.mkdtemp` + `shutil.rmtree(..., ignore_errors=True)`
    pattern used elsewhere in this package.

    Raises `AudioStageError` (a `RuntimeError` subclass) naming the failing
    ffmpeg stage, with a stderr excerpt, on any stage failure.
    """
    recording = Path(recording)
    out_wav = Path(out_wav)
    if not recording.exists():
        raise FileNotFoundError(f"process_take: recording not found: {recording}")
    out_wav.parent.mkdir(parents=True, exist_ok=True)

    tmp_dir = Path(tempfile.mkdtemp(prefix="dlstudio_take_"))
    try:
        cleaned = tmp_dir / "cleaned.wav"

        # ── Stage 1: leading-silence trim + rumble highpass + de-click ──
        _run([
            "ffmpeg", "-y", "-i", str(recording),
            "-vn", "-ac", "1", "-ar", str(sample_rate),
            "-af", (
                "silenceremove=start_periods=1:start_duration=0.2:start_threshold=-40dB,"
                "highpass=f=60:poles=2,adeclip"
            ),
            "-c:a", "pcm_s16le", str(cleaned),
        ], stage="cleanup (silenceremove/highpass/adeclip)")

        # ── Stage 2: loudnorm pass 1 — measure ──
        r2 = _run([
            "ffmpeg", "-i", str(cleaned),
            "-af", f"loudnorm=I={target_lufs}:TP={true_peak_db}:LRA={lra}:print_format=json",
            "-f", "null", "-",
        ], stage="loudnorm measure")
        measured = _parse_loudnorm_json(r2.stderr or r2.stdout, stage="loudnorm measure")

        # ── Stage 3: loudnorm pass 2 — apply (measured values + linear) ──
        apply_filter = (
            f"loudnorm=I={target_lufs}:TP={true_peak_db}:LRA={lra}:"
            f"measured_I={measured['input_i']}:measured_TP={measured['input_tp']}:"
            f"measured_LRA={measured['input_lra']}:measured_thresh={measured['input_thresh']}:"
            f"offset={measured['target_offset']}:linear=true"
        )
        _run([
            "ffmpeg", "-y", "-i", str(cleaned),
            "-af", apply_filter,
            "-ar", str(sample_rate), "-c:a", "pcm_s16le", str(out_wav),
        ], stage="loudnorm apply")

        duration = _probe_duration(out_wav)
        return ProcessResult(
            out=out_wav,
            input_i=float(measured["input_i"]),
            input_tp=float(measured["input_tp"]),
            input_lra=float(measured["input_lra"]),
            input_thresh=float(measured["input_thresh"]),
            duration=duration,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
