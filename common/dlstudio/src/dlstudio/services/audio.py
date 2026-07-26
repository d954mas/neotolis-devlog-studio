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
import hashlib
import shutil
import subprocess
import tempfile
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from .script_preflight import check_wav_first_3s

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
    marker_status: str = "absent"
    trim_start: float | None = None
    trim_end: float | None = None
    verdict: dict[str, Any] | None = None


@dataclass(frozen=True)
class VoiceTakeMarkers:
    """Validated timing markers written by Studio's recording state machine."""

    path: Path
    countdown_seconds: float
    room_tone_seconds: float
    speech_start_seconds: float
    stop_requested_seconds: float
    post_roll_end_seconds: float
    post_roll_target_seconds: float
    post_roll_completed: bool
    completed_lead_in: bool


class VoiceTakeQualityError(RuntimeError):
    """The take cannot be processed without risking a retained artifact."""

    def __init__(self, message: str, verdict: dict[str, Any]) -> None:
        super().__init__(message)
        self.verdict = verdict


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


def recording_metadata_path(recording: Path) -> Path:
    """Return the sidecar path used by Studio's take-upload endpoint."""

    recording = Path(recording)
    return recording.with_suffix(recording.suffix + ".recording.json")


def load_voice_take_markers(recording: Path) -> VoiceTakeMarkers | None:
    """Load and validate Studio v1 recording markers, if a sidecar exists."""

    sidecar = recording_metadata_path(recording)
    if not sidecar.exists():
        return None
    try:
        payload = json.loads(sidecar.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"invalid voice-take marker sidecar {sidecar}: {exc}") from exc
    if not isinstance(payload, dict):
        raise ValueError(f"voice-take marker sidecar must contain an object: {sidecar}")
    if payload.get("schema") != "devlog.voice_take" or payload.get("version") != 1:
        raise ValueError(f"unsupported voice-take marker schema: {sidecar}")

    numeric_names = (
        "countdown_seconds",
        "room_tone_seconds",
        "speech_start_seconds",
        "stop_requested_seconds",
        "post_roll_end_seconds",
        "post_roll_target_seconds",
    )
    values: dict[str, float] = {}
    for name in numeric_names:
        raw = payload.get(name)
        if isinstance(raw, bool) or not isinstance(raw, (int, float)):
            raise ValueError(f"voice-take marker {name!r} must be numeric: {sidecar}")
        value = float(raw)
        if value < 0 or value != value or value in (float("inf"), float("-inf")):
            raise ValueError(
                f"voice-take marker {name!r} must be finite and non-negative: {sidecar}"
            )
        values[name] = value

    for name in ("post_roll_completed", "completed_lead_in"):
        if not isinstance(payload.get(name), bool):
            raise ValueError(f"voice-take marker {name!r} must be boolean: {sidecar}")
    expected_start = values["countdown_seconds"] + values["room_tone_seconds"]
    if abs(values["speech_start_seconds"] - expected_start) > 0.01:
        raise ValueError(f"voice-take speech marker does not match lead-in: {sidecar}")
    if values["stop_requested_seconds"] < values["speech_start_seconds"]:
        raise ValueError(f"voice-take stop marker precedes speech start: {sidecar}")
    if values["post_roll_end_seconds"] < values["stop_requested_seconds"]:
        raise ValueError(f"voice-take post-roll marker precedes stop: {sidecar}")
    actual_post_roll = (
        values["post_roll_end_seconds"] - values["stop_requested_seconds"]
    )
    if payload["post_roll_completed"] and (
        actual_post_roll < values["post_roll_target_seconds"] - 0.10
    ):
        raise ValueError(
            f"voice-take completed post-roll is shorter than its target: {sidecar}"
        )

    return VoiceTakeMarkers(
        path=sidecar,
        **values,
        post_roll_completed=payload["post_roll_completed"],
        completed_lead_in=payload["completed_lead_in"],
    )


def _marker_trim(
    markers: VoiceTakeMarkers | None,
    source_duration: float,
    *,
    head_handle_seconds: float = 0.25,
    stop_click_guard_seconds: float = 0.10,
    duration_tolerance: float = 0.35,
) -> tuple[str, float | None, float | None]:
    if markers is None:
        return "absent", None, None
    if not markers.completed_lead_in or not markers.post_roll_completed:
        return "incomplete", None, None
    if (
        markers.stop_requested_seconds > source_duration + duration_tolerance
        or markers.post_roll_end_seconds > source_duration + duration_tolerance
    ):
        raise ValueError(
            "voice-take markers exceed the recorded media duration "
            f"({markers.post_roll_end_seconds:.3f}s > {source_duration:.3f}s)"
        )
    start = max(0.0, markers.speech_start_seconds - head_handle_seconds)
    end = min(
        source_duration,
        markers.stop_requested_seconds - stop_click_guard_seconds,
    )
    if end - start < 0.20:
        raise ValueError(
            f"voice-take marker selection is too short ({end - start:.3f}s)"
        )
    return "applied", start, end


def write_voice_take_verdict(verdict: dict[str, Any], path: Path) -> Path:
    """Atomically persist a machine-readable take-quality verdict."""

    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        suffix=".json",
        prefix=f".{path.stem}.tmp-",
        dir=path.parent,
        delete=False,
    ) as stream:
        json.dump(verdict, stream, ensure_ascii=False, indent=2)
        stream.write("\n")
        staged = Path(stream.name)
    staged.replace(path)
    return path


def _sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _base_verdict(
    recording: Path,
    markers: VoiceTakeMarkers | None,
    marker_status: str,
    source_duration: float,
) -> dict[str, Any]:
    return {
        "schema": "dlstudio.voice-take-verdict",
        "version": 1,
        "artifact_path": str(recording.resolve()),
        "artifact_sha256": _sha256_file(recording),
        "timestamp": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "marker_sidecar": str(markers.path.resolve()) if markers else None,
        "marker_status": marker_status,
        "source_duration_seconds": source_duration,
    }


def _qc_payload(qc, *, location: str) -> dict[str, Any]:
    issues = []
    for issue in qc.issues:
        payload = asdict(issue)
        if location == "tail":
            payload["code"] = payload["code"].replace("-START-", "-END-")
            payload["message"] = payload["message"].replace("First ", "Final ")
        issues.append(payload)
    return {
        "location": location,
        "ok": qc.ok,
        "analyzed_seconds": qc.analyzed_seconds,
        "peak": qc.peak,
        "rms": qc.rms,
        "clipping": qc.clipping,
        "impulse": qc.impulse,
        "noise_jump": qc.noise_jump,
        "issues": issues,
    }


def _reverse_wav(source: Path, destination: Path) -> None:
    _run([
        "ffmpeg", "-y", "-i", str(source),
        "-af", "areverse",
        "-c:a", "pcm_s16le", str(destination),
    ], stage="tail QC preparation")


def _boundary_qc(source: Path, reversed_path: Path) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    start = check_wav_first_3s(source)
    _reverse_wav(source, reversed_path)
    tail = check_wav_first_3s(reversed_path)
    payload = {
        "start": _qc_payload(start, location="start"),
        "tail": _qc_payload(tail, location="tail"),
    }
    blocking = [
        issue
        for boundary in payload.values()
        for issue in boundary["issues"]
        if issue["severity"] == "error"
    ]
    return payload, blocking


def process_take(
    recording: Path,
    out_wav: Path,
    *,
    target_lufs: float = -14.0,
    true_peak_db: float = -1.0,
    lra: float = 11.0,
    sample_rate: int = 48000,
    verdict_path: Path | None = None,
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
        selected = tmp_dir / "selected.wav"
        cleaned = tmp_dir / "cleaned.wav"
        reversed_qc = tmp_dir / "reversed_qc.wav"

        markers = load_voice_take_markers(recording)
        source_duration: float | None = None
        if markers is None:
            marker_status, trim_start, trim_end = "absent", None, None
        else:
            source_duration = _probe_duration(recording)
            if not markers.completed_lead_in or not markers.post_roll_completed:
                marker_status = "incomplete"
                verdict = _base_verdict(
                    recording,
                    markers,
                    marker_status,
                    source_duration,
                )
                verdict.update({
                    "selection": {"applied": False},
                    "boundary_qc": None,
                    "issues": [{
                        "code": "VQ-AUDIO-MARKERS-INCOMPLETE",
                        "severity": "error",
                        "message": (
                            "Recording did not complete its lead-in and post-roll; "
                            "the take must be recorded again"
                        ),
                    }],
                    "verdict": "block",
                    "recommended_action": "re_record",
                })
                if verdict_path is not None:
                    write_voice_take_verdict(verdict, verdict_path)
                raise VoiceTakeQualityError(
                    "process_take: incomplete recording markers require re-record",
                    verdict,
                )
            marker_status, trim_start, trim_end = _marker_trim(
                markers,
                source_duration,
            )

        select_filter: list[str] = []
        if trim_start is not None and trim_end is not None:
            select_filter.extend([
                "-af",
                f"atrim=start={trim_start:.6f}:end={trim_end:.6f},asetpts=PTS-STARTPTS",
            ])
        _run([
            "ffmpeg", "-y", "-i", str(recording),
            "-vn", "-ac", "1", "-ar", str(sample_rate),
            *select_filter,
            "-c:a", "pcm_s16le", str(selected),
        ], stage="marker selection")
        if source_duration is None:
            source_duration = _probe_duration(selected)

        verdict = _base_verdict(
            recording,
            markers,
            marker_status,
            source_duration,
        )
        verdict["selection"] = {
            "applied": marker_status == "applied",
            "start_seconds": trim_start,
            "end_seconds": trim_end,
            "head_handle_seconds": (
                markers.speech_start_seconds - trim_start
                if markers is not None and trim_start is not None
                else None
            ),
            "stop_click_guard_seconds": (
                markers.stop_requested_seconds - trim_end
                if markers is not None and trim_end is not None
                else None
            ),
        }

        boundary_qc: dict[str, Any] | None = None
        blocking_issues: list[dict[str, Any]] = []
        if marker_status == "applied":
            boundary_qc, blocking_issues = _boundary_qc(selected, reversed_qc)

        # ── Stage 1: leading-silence trim + rumble highpass + de-click ──
        _run([
            "ffmpeg", "-y", "-i", str(selected),
            "-vn", "-ac", "1", "-ar", str(sample_rate),
            "-af", (
                "silenceremove=start_periods=1:start_duration=0.2:start_threshold=-40dB,"
                "highpass=f=60:poles=2,adeclip"
            ),
            "-c:a", "pcm_s16le", str(cleaned),
        ], stage="cleanup (silenceremove/highpass/adeclip)")

        if marker_status == "absent":
            boundary_qc, blocking_issues = _boundary_qc(cleaned, reversed_qc)

        verdict["boundary_qc"] = boundary_qc
        verdict["issues"] = [
            issue
            for boundary in (boundary_qc or {}).values()
            for issue in boundary["issues"]
        ]
        verdict["verdict"] = (
            "block"
            if blocking_issues
            else "pass"
            if marker_status == "applied"
            else "unverified"
        )
        verdict["recommended_action"] = (
            "re_record"
            if blocking_issues
            else "none"
            if marker_status == "applied"
            else "review_legacy"
        )
        if blocking_issues:
            if verdict_path is not None:
                write_voice_take_verdict(verdict, verdict_path)
            codes = ", ".join(issue["code"] for issue in blocking_issues)
            raise VoiceTakeQualityError(
                f"process_take: take rejected by boundary QC ({codes})",
                verdict,
            )

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
        if verdict_path is not None:
            write_voice_take_verdict(verdict, verdict_path)
        return ProcessResult(
            out=out_wav,
            input_i=float(measured["input_i"]),
            input_tp=float(measured["input_tp"]),
            input_lra=float(measured["input_lra"]),
            input_thresh=float(measured["input_thresh"]),
            duration=duration,
            marker_status=marker_status,
            trim_start=trim_start,
            trim_end=trim_end,
            verdict=verdict,
        )
    finally:
        shutil.rmtree(tmp_dir, ignore_errors=True)
