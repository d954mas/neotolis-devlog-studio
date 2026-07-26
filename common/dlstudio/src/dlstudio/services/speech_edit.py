"""Deterministic speech-edit planning and words.json remapping.

The Studio does not host an LLM.  An external production agent may author or
amend a plan, while the functions in this module provide a conservative
automatic baseline and a deterministic executor contract.  Render/compile
continue to consume an ordinary WAV plus the v1-compatible words.json shape.
"""
from __future__ import annotations

import math
import hashlib
import json
import re
import shutil
import subprocess
import wave
from array import array
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Mapping, Sequence


_SILENCE_START_RE = re.compile(r"silence_start:\s*(-?\d+(?:\.\d+)?)")
_SILENCE_END_RE = re.compile(r"silence_end:\s*(-?\d+(?:\.\d+)?)")
_WORD_EDGE_RE = re.compile(r"(^[^\w]+|[^\w]+$)", re.UNICODE)
_FILLERS = frozenset({
    "э", "ээ", "эээ", "эм", "мм", "м-м", "а-а", "ну", "типа",
    "uh", "uhh", "um", "umm", "erm", "hmm",
})


@dataclass(frozen=True)
class SpeechCut:
    """One half-open source interval to remove from the take."""

    t0: float
    t1: float
    reasons: tuple[str, ...]
    sources: tuple[str, ...]
    confidence: float = 1.0

    @property
    def duration(self) -> float:
        return self.t1 - self.t0

    def to_dict(self) -> dict:
        return {
            "t0": self.t0,
            "t1": self.t1,
            "reasons": list(self.reasons),
            "sources": list(self.sources),
            "confidence": self.confidence,
        }


@dataclass(frozen=True)
class SpeechEditPlan:
    """Hash-bound automatic plan which can be persisted as speech_edit.json."""

    source_duration: float
    cuts: tuple[SpeechCut, ...]
    input_audio_sha256: str
    input_words_sha256: str
    schema: str = "dlstudio.speech-edit/v1"

    @property
    def removed_duration(self) -> float:
        return sum(cut.duration for cut in self.cuts)

    @property
    def output_duration(self) -> float:
        return self.source_duration - self.removed_duration

    def to_dict(self) -> dict:
        return {
            "schema": self.schema,
            "input": {
                "audio_sha256": self.input_audio_sha256,
                "words_sha256": self.input_words_sha256,
                "duration": self.source_duration,
            },
            "cuts": [cut.to_dict() for cut in self.cuts],
            "summary": {
                "cut_count": len(self.cuts),
                "removed_duration": self.removed_duration,
                "output_duration": self.output_duration,
            },
        }

    @classmethod
    def from_dict(cls, payload: Mapping[str, object]) -> "SpeechEditPlan":
        """Load the persisted v1 plan shape and reject ambiguous input."""

        if payload.get("schema") != "dlstudio.speech-edit/v1":
            raise ValueError("unsupported speech edit plan schema")
        raw_input = payload.get("input")
        raw_cuts = payload.get("cuts")
        if not isinstance(raw_input, Mapping) or not isinstance(raw_cuts, list):
            raise ValueError("speech edit plan requires input and cuts")
        try:
            source_duration = float(raw_input["duration"])
            audio_hash = str(raw_input["audio_sha256"])
            words_hash = str(raw_input["words_sha256"])
        except (KeyError, TypeError, ValueError) as exc:
            raise ValueError("speech edit plan input is incomplete") from exc
        if not re.fullmatch(r"[0-9a-f]{64}", audio_hash):
            raise ValueError("speech edit plan audio_sha256 is invalid")
        if not re.fullmatch(r"[0-9a-f]{64}", words_hash):
            raise ValueError("speech edit plan words_sha256 is invalid")
        cuts: list[SpeechCut] = []
        for index, raw_cut in enumerate(raw_cuts):
            if not isinstance(raw_cut, Mapping):
                raise ValueError(f"speech edit cut {index} must be an object")
            try:
                reasons = tuple(str(value) for value in raw_cut["reasons"])
                sources = tuple(str(value) for value in raw_cut["sources"])
                cut = SpeechCut(
                    t0=float(raw_cut["t0"]),
                    t1=float(raw_cut["t1"]),
                    reasons=reasons,
                    sources=sources,
                    confidence=float(raw_cut.get("confidence", 1.0)),
                )
            except (KeyError, TypeError, ValueError) as exc:
                raise ValueError(f"speech edit cut {index} is invalid") from exc
            if not cut.reasons or not cut.sources:
                raise ValueError(f"speech edit cut {index} requires reasons and sources")
            cuts.append(cut)
        _validate_cuts(cuts, duration=source_duration)
        return cls(
            source_duration=source_duration,
            cuts=tuple(cuts),
            input_audio_sha256=audio_hash,
            input_words_sha256=words_hash,
        )


@dataclass(frozen=True)
class SpeechEditResult:
    """Materialized speech-edit bundle."""

    audio: Path
    words: Path
    artifact: Path
    source_duration: float
    duration: float
    removed_duration: float
    cut_count: int
    skipped_cut_count: int


@dataclass(frozen=True)
class SpeechEditExecution:
    """Exact FFmpeg timeline effects needed for transcript remapping."""

    filtergraph: str
    cut_crossfades: tuple[float, ...]
    join_ranges_samples: tuple[tuple[int, int], ...]
    crossfade_samples: tuple[int, ...]


@dataclass(frozen=True)
class SpeechJoinEvidence:
    """Post-render waveform continuity evidence for one join."""

    crossfade_samples: int
    max_step_dbfs: float

    def to_dict(self) -> dict:
        return {
            "crossfade_samples": self.crossfade_samples,
            "max_step_dbfs": self.max_step_dbfs,
        }


@dataclass(frozen=True)
class SpeechBoundaryEvidence:
    """Signal evidence for one resolved cut boundary."""

    requested_time: float
    resolved_time: float
    rms_dbfs: float

    def to_dict(self) -> dict:
        return {
            "requested_time": self.requested_time,
            "resolved_time": self.resolved_time,
            "rms_dbfs": self.rms_dbfs,
        }


@dataclass(frozen=True)
class SkippedSpeechCut:
    """A requested edit intentionally retained because it was not safe."""

    cut: SpeechCut
    reason: str

    def to_dict(self) -> dict:
        return {"cut": self.cut.to_dict(), "reason": self.reason}


@dataclass(frozen=True)
class ResolvedSpeechCuts:
    """Applied and retained decisions after word/signal safety resolution."""

    applied: tuple[SpeechCut, ...]
    skipped: tuple[SkippedSpeechCut, ...]
    boundaries: tuple[SpeechBoundaryEvidence, ...]


class SpeechEditStageError(RuntimeError):
    """Raised when deterministic FFmpeg materialization fails."""


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _pcm_wav_info(path: Path) -> tuple[int, int, float]:
    try:
        with wave.open(str(path), "rb") as wav:
            sample_rate = wav.getframerate()
            frames = wav.getnframes()
            channels = wav.getnchannels()
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"speech edit requires a PCM WAV source: {path}") from exc
    if sample_rate <= 0 or frames <= 0:
        raise ValueError(f"speech edit source is empty or invalid: {path}")
    return sample_rate, channels, frames / sample_rate


def _read_pcm16_mono(path: Path) -> tuple[int, array]:
    try:
        with wave.open(str(path), "rb") as wav:
            if wav.getnchannels() != 1 or wav.getsampwidth() != 2:
                raise ValueError("speech boundary analysis requires mono PCM s16 WAV")
            sample_rate = wav.getframerate()
            samples = array("h")
            samples.frombytes(wav.readframes(wav.getnframes()))
    except (wave.Error, EOFError) as exc:
        raise ValueError(f"speech boundary analysis cannot read WAV: {path}") from exc
    return sample_rate, samples


def _quietest_boundary(
    samples: array,
    *,
    sample_rate: int,
    requested: float,
    lower: float,
    upper: float,
    rms_window_seconds: float,
) -> SpeechBoundaryEvidence | None:
    lower_sample = max(0, math.ceil(lower * sample_rate))
    upper_sample = min(len(samples), math.floor(upper * sample_rate))
    if upper_sample < lower_sample:
        return None
    half_window = max(1, round(rms_window_seconds * sample_rate / 2))
    square_prefix = [0]
    total = 0
    region_start = max(0, lower_sample - half_window)
    region_end = min(len(samples), upper_sample + half_window + 1)
    for value in samples[region_start:region_end]:
        total += int(value) * int(value)
        square_prefix.append(total)

    requested_sample = round(requested * sample_rate)
    best: tuple[int, int, int, int] | None = None
    for position in range(lower_sample, upper_sample + 1):
        window_start = max(region_start, position - half_window)
        window_end = min(region_end, position + half_window)
        count = max(1, window_end - window_start)
        energy = (
            square_prefix[window_end - region_start]
            - square_prefix[window_start - region_start]
        )
        candidate = (energy, abs(position - requested_sample), position, count)
        if best is None or candidate[:3] < best[:3]:
            best = candidate
    if best is None:
        return None
    energy, _distance, position, count = best
    rms = math.sqrt(energy / count) / 32768.0
    rms_dbfs = -120.0 if rms <= 1e-9 else 20.0 * math.log10(rms)
    return SpeechBoundaryEvidence(
        requested_time=requested,
        resolved_time=position / sample_rate,
        rms_dbfs=rms_dbfs,
    )


def parse_silencedetect(stderr: str, *, audio_duration: float) -> list[tuple[float, float]]:
    """Parse ffmpeg silencedetect stderr into bounded source ranges."""

    if not math.isfinite(audio_duration) or audio_duration < 0:
        raise ValueError("audio_duration must be a finite non-negative number")
    ranges: list[tuple[float, float]] = []
    pending_start: float | None = None
    for line in stderr.splitlines():
        start_match = _SILENCE_START_RE.search(line)
        if start_match:
            pending_start = max(0.0, min(float(start_match.group(1)), audio_duration))
        end_match = _SILENCE_END_RE.search(line)
        if end_match and pending_start is not None:
            end = max(0.0, min(float(end_match.group(1)), audio_duration))
            if end > pending_start:
                ranges.append((pending_start, end))
            pending_start = None
    if pending_start is not None and audio_duration > pending_start:
        ranges.append((pending_start, audio_duration))
    return ranges


def _token(value: object) -> str:
    return _WORD_EDGE_RE.sub("", str(value).strip().casefold())


def _word_bounds(word: Mapping[str, object]) -> tuple[float, float]:
    try:
        start = float(word["start"])
        end = float(word["end"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(f"invalid word timing: {word!r}") from exc
    if not (math.isfinite(start) and math.isfinite(end) and 0 <= start <= end):
        raise ValueError(f"invalid word timing: {word!r}")
    return start, end


def _merge_cuts(
    cuts: Iterable[SpeechCut],
    *,
    source_duration: float,
    max_gap: float = 0.0,
) -> tuple[SpeechCut, ...]:
    ordered = sorted(cuts, key=lambda cut: (cut.t0, cut.t1))
    merged: list[SpeechCut] = []
    for cut in ordered:
        if not (math.isfinite(cut.t0) and math.isfinite(cut.t1)):
            raise ValueError("speech cut bounds must be finite")
        t0 = max(0.0, cut.t0)
        t1 = min(source_duration, cut.t1)
        if t1 <= t0:
            continue
        normalized = SpeechCut(
            t0=t0,
            t1=t1,
            reasons=tuple(dict.fromkeys(cut.reasons)),
            sources=tuple(dict.fromkeys(cut.sources)),
            confidence=cut.confidence,
        )
        previous = merged[-1] if merged else None
        if previous is None or normalized.t0 > previous.t1 + max_gap:
            merged.append(normalized)
            continue
        merged[-1] = SpeechCut(
            t0=previous.t0,
            t1=max(previous.t1, normalized.t1),
            reasons=tuple(dict.fromkeys((*previous.reasons, *normalized.reasons))),
            sources=tuple(dict.fromkeys((*previous.sources, *normalized.sources))),
            confidence=min(previous.confidence, normalized.confidence),
        )
    return tuple(merged)


def _repeat_cuts(words: Sequence[Mapping[str, object]]) -> list[SpeechCut]:
    """Find exact adjacent phrase restarts, ignoring filler tokens between them."""

    meaningful = [
        (index, _token(word.get("word", "")))
        for index, word in enumerate(words)
        if _token(word.get("word", "")) not in _FILLERS
    ]
    meaningful = [(index, token) for index, token in meaningful if token]
    tokens = [token for _, token in meaningful]
    cuts: list[SpeechCut] = []
    claimed: set[int] = set()
    max_phrase = min(6, len(tokens) // 2)
    for length in range(max_phrase, 1, -1):
        pos = 0
        while pos + 2 * length <= len(tokens):
            left = meaningful[pos : pos + length]
            right = meaningful[pos + length : pos + 2 * length]
            if (
                [token for _, token in left] == [token for _, token in right]
                and not any(index in claimed for index, _ in (*left, *right))
            ):
                first_start, _ = _word_bounds(words[left[0][0]])
                _, first_end = _word_bounds(words[left[-1][0]])
                cuts.append(SpeechCut(
                    t0=first_start,
                    t1=first_end,
                    reasons=("exact_phrase_repeat",),
                    sources=("automatic_transcript",),
                    confidence=1.0,
                ))
                claimed.update(index for index, _ in left)
                pos += 2 * length
            else:
                pos += 1
    return cuts


def build_automatic_plan(
    words_payload: Mapping[str, object],
    *,
    source_duration: float,
    signal_silences: Sequence[tuple[float, float]],
    audio_sha256: str,
    words_sha256: str,
    minimum_silence: float = 0.45,
    silence_handle: float = 0.10,
) -> SpeechEditPlan:
    """Build a conservative baseline plan from signal and transcript facts.

    This baseline removes only measured long silence and explicit filler
    tokens. Exact repetition is surfaced in the transcript but is not
    automatically deleted: it may be intentional rhetoric, so restart cuts
    belong in an agent-authored semantic plan.
    """

    if not math.isfinite(source_duration) or source_duration <= 0:
        raise ValueError("source_duration must be a finite positive number")
    raw_words = words_payload.get("words", [])
    if not isinstance(raw_words, list):
        raise ValueError("words payload must contain a words list")
    words: list[Mapping[str, object]] = []
    for word in raw_words:
        if not isinstance(word, Mapping):
            raise ValueError(f"invalid word entry: {word!r}")
        _word_bounds(word)
        words.append(word)

    candidates: list[SpeechCut] = []
    for word in words:
        if _token(word.get("word", "")) in _FILLERS:
            start, end = _word_bounds(word)
            candidates.append(SpeechCut(
                t0=start,
                t1=end,
                reasons=("filler",),
                sources=("automatic_transcript",),
                confidence=0.98,
            ))
    for raw_start, raw_end in signal_silences:
        start = max(0.0, float(raw_start))
        end = min(source_duration, float(raw_end))
        if end - start < minimum_silence:
            continue
        if start <= 0.001:
            cut_start, cut_end = 0.0, max(0.0, end - silence_handle)
        elif end >= source_duration - 0.001:
            cut_start, cut_end = min(source_duration, start + silence_handle), source_duration
        else:
            cut_start, cut_end = start + silence_handle, end - silence_handle
        if cut_end > cut_start:
            candidates.append(SpeechCut(
                t0=cut_start,
                t1=cut_end,
                reasons=("silence",),
                sources=("signal",),
                confidence=1.0,
            ))

    return SpeechEditPlan(
        source_duration=source_duration,
        cuts=_merge_cuts(candidates, source_duration=source_duration),
        input_audio_sha256=audio_sha256,
        input_words_sha256=words_sha256,
    )


def resolve_safe_cuts(
    source_audio: Path,
    words_payload: Mapping[str, object],
    cuts: Sequence[SpeechCut],
    *,
    word_guard_seconds: float = 0.035,
    boundary_search_seconds: float = 0.08,
    rms_window_seconds: float = 0.004,
    max_boundary_rms_dbfs: float = -30.0,
) -> ResolvedSpeechCuts:
    """Snap edits into quiet word gaps and retain every unsafe decision.

    Safety is deliberately asymmetric: a false negative leaves an extra pause
    or filler in the take, while a false positive permanently damages speech.
    Therefore any partial-word overlap, missing guard interval, or loud
    boundary skips that individual cut instead of guessing.
    """

    source_audio = Path(source_audio)
    sample_rate, samples = _read_pcm16_mono(source_audio)
    duration = len(samples) / sample_rate
    _validate_cuts(cuts, duration=duration + 1 / sample_rate)
    raw_words = words_payload.get("words", [])
    if not isinstance(raw_words, list):
        raise ValueError("words payload must contain a words list")
    words: list[tuple[float, float]] = []
    for raw_word in raw_words:
        if not isinstance(raw_word, Mapping):
            raise ValueError(f"invalid word entry: {raw_word!r}")
        words.append(_word_bounds(raw_word))

    applied: list[SpeechCut] = []
    skipped: list[SkippedSpeechCut] = []
    boundaries: list[SpeechBoundaryEvidence] = []
    for cut in cuts:
        overlapping = [
            index for index, (start, end) in enumerate(words)
            if cut.t0 < end and cut.t1 > start
        ]
        fully_dropped = [
            index for index in overlapping
            if cut.t0 <= words[index][0] and cut.t1 >= words[index][1]
        ]
        if len(overlapping) != len(fully_dropped):
            skipped.append(SkippedSpeechCut(cut=cut, reason="splits_word"))
            continue

        if fully_dropped:
            first = fully_dropped[0]
            last = fully_dropped[-1]
            previous_end = words[first - 1][1] if first > 0 else 0.0
            next_start = words[last + 1][0] if last + 1 < len(words) else duration
            start_safe = (previous_end + word_guard_seconds, words[first][0])
            end_safe = (words[last][1], next_start - word_guard_seconds)
        else:
            previous_at_start = max(
                (end for start, end in words if end <= cut.t0), default=0.0,
            )
            next_at_start = min(
                (start for start, end in words if start >= cut.t0), default=duration,
            )
            previous_at_end = max(
                (end for start, end in words if end <= cut.t1), default=0.0,
            )
            next_at_end = min(
                (start for start, end in words if start >= cut.t1), default=duration,
            )
            start_safe = (
                previous_at_start + word_guard_seconds,
                next_at_start - word_guard_seconds,
            )
            end_safe = (
                previous_at_end + word_guard_seconds,
                next_at_end - word_guard_seconds,
            )

        start_evidence: SpeechBoundaryEvidence | None
        end_evidence: SpeechBoundaryEvidence | None
        if cut.t0 <= 1 / sample_rate:
            start_evidence = SpeechBoundaryEvidence(cut.t0, 0.0, -120.0)
        else:
            start_evidence = _quietest_boundary(
                samples,
                sample_rate=sample_rate,
                requested=cut.t0,
                lower=max(start_safe[0], cut.t0 - boundary_search_seconds),
                upper=min(start_safe[1], cut.t0 + boundary_search_seconds),
                rms_window_seconds=rms_window_seconds,
            )
        if cut.t1 >= duration - 1 / sample_rate:
            end_evidence = SpeechBoundaryEvidence(cut.t1, duration, -120.0)
        else:
            end_evidence = _quietest_boundary(
                samples,
                sample_rate=sample_rate,
                requested=cut.t1,
                lower=max(end_safe[0], cut.t1 - boundary_search_seconds),
                upper=min(end_safe[1], cut.t1 + boundary_search_seconds),
                rms_window_seconds=rms_window_seconds,
            )
        if (
            start_evidence is None
            or end_evidence is None
            or start_evidence.rms_dbfs > max_boundary_rms_dbfs
            or end_evidence.rms_dbfs > max_boundary_rms_dbfs
        ):
            skipped.append(SkippedSpeechCut(cut=cut, reason="no_quiet_boundary"))
            continue
        if end_evidence.resolved_time <= start_evidence.resolved_time:
            skipped.append(SkippedSpeechCut(cut=cut, reason="empty_after_resolution"))
            continue
        applied.append(SpeechCut(
            t0=start_evidence.resolved_time,
            t1=end_evidence.resolved_time,
            reasons=cut.reasons,
            sources=cut.sources,
            confidence=cut.confidence,
        ))
        boundaries.extend((start_evidence, end_evidence))

    return ResolvedSpeechCuts(
        applied=_merge_cuts(applied, source_duration=duration),
        skipped=tuple(skipped),
        boundaries=tuple(boundaries),
    )


def _validate_cuts(cuts: Sequence[SpeechCut], *, duration: float) -> None:
    previous_end = 0.0
    for index, cut in enumerate(cuts):
        if not (math.isfinite(cut.t0) and math.isfinite(cut.t1) and cut.t1 > cut.t0):
            raise ValueError(f"invalid speech cut at index {index}")
        if cut.t0 < 0 or cut.t1 > duration:
            raise ValueError(
                f"speech cut at index {index} exceeds source duration {duration}"
            )
        if index and cut.t0 < previous_end:
            raise ValueError(f"speech cuts overlap at index {index}")
        previous_end = cut.t1


def _map_time(
    value: float,
    cuts: Sequence[SpeechCut],
    cut_crossfades: Sequence[float],
) -> float:
    removed = 0.0
    for cut, crossfade in zip(cuts, cut_crossfades, strict=True):
        if value >= cut.t1:
            removed += cut.duration + crossfade
        elif value > cut.t0:
            return cut.t0 - removed
        else:
            break
    return value - removed


def remap_words_payload(
    words_payload: Mapping[str, object],
    cuts: Sequence[SpeechCut],
    *,
    output_audio: str | None = None,
    cut_crossfades: Sequence[float] | None = None,
) -> dict:
    """Remove cut tokens and shift retained word timings onto edited audio."""

    try:
        duration = float(words_payload["duration"])
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("words payload must contain a numeric duration") from exc
    _validate_cuts(cuts, duration=duration)
    crossfades = tuple(cut_crossfades or (0.0 for _cut in cuts))
    if len(crossfades) != len(cuts):
        raise ValueError("cut_crossfades must align one-to-one with cuts")
    if any(value < 0 for value in crossfades):
        raise ValueError("cut_crossfades cannot be negative")
    raw_words = words_payload.get("words", [])
    if not isinstance(raw_words, list):
        raise ValueError("words payload must contain a words list")

    remapped_words: list[dict] = []
    for raw_word in raw_words:
        if not isinstance(raw_word, Mapping):
            raise ValueError(f"invalid word entry: {raw_word!r}")
        start, end = _word_bounds(raw_word)
        overlaps = [cut for cut in cuts if cut.t0 < end and cut.t1 > start]
        containing = [cut for cut in overlaps if cut.t0 <= start and cut.t1 >= end]
        if overlaps and not containing:
            raise ValueError(
                f"speech cut splits word {raw_word.get('word', '')!r} "
                f"at {start:.3f}-{end:.3f}"
            )
        if containing:
            continue
        mapped = dict(raw_word)
        mapped["start"] = round(_map_time(start, cuts, crossfades), 6)
        mapped["end"] = round(_map_time(end, cuts, crossfades), 6)
        remapped_words.append(mapped)

    result = dict(words_payload)
    result["audio"] = output_audio if output_audio is not None else words_payload.get("audio", "")
    result["duration"] = (
        duration - sum(cut.duration for cut in cuts) - sum(crossfades)
    )
    result["words"] = remapped_words
    result["text"] = " ".join(str(word.get("word", "")).strip() for word in remapped_words).strip()
    return result


def detect_silences(
    audio: Path,
    *,
    audio_duration: float,
    threshold_db: float = -38.0,
    minimum_duration: float = 0.35,
) -> list[tuple[float, float]]:
    """Run FFmpeg's signal-level silence detector and parse its evidence."""

    cmd = [
        "ffmpeg", "-hide_banner", "-nostats", "-i", str(audio),
        "-af", f"silencedetect=n={threshold_db}dB:d={minimum_duration}",
        "-f", "null", "-",
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError("speech edit: ffmpeg not found on PATH") from exc
    if result.returncode != 0:
        raise SpeechEditStageError(
            "speech edit: ffmpeg silencedetect failed\n"
            f"stderr (tail):\n{(result.stderr or result.stdout)[-1500:]}"
        )
    return parse_silencedetect(result.stderr or result.stdout, audio_duration=audio_duration)


def build_automatic_plan_from_files(audio: Path, words: Path) -> SpeechEditPlan:
    """Build the conservative baseline directly from a normalized take."""

    audio = Path(audio)
    words = Path(words)
    _, _, duration = _pcm_wav_info(audio)
    payload = json.loads(words.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("words JSON must contain an object")
    silences = detect_silences(audio, audio_duration=duration)
    return build_automatic_plan(
        payload,
        source_duration=duration,
        signal_silences=silences,
        audio_sha256=sha256_file(audio),
        words_sha256=sha256_file(words),
    )


def _keep_sample_spans(
    cuts: Sequence[SpeechCut], *, sample_rate: int, frame_count: int,
) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    cursor = 0
    for cut in cuts:
        cut_start = max(0, min(frame_count, round(cut.t0 * sample_rate)))
        cut_end = max(0, min(frame_count, round(cut.t1 * sample_rate)))
        if cut_start > cursor:
            spans.append((cursor, cut_start))
        cursor = max(cursor, cut_end)
    if cursor < frame_count:
        spans.append((cursor, frame_count))
    if not spans:
        raise ValueError("speech edit plan removes the entire take")
    return spans


def apply_speech_edit(
    source_audio: Path,
    output_audio: Path,
    cuts: Sequence[SpeechCut],
    *,
    crossfade_seconds: float = 0.012,
) -> SpeechEditExecution:
    """Materialize cuts into a mono 48 kHz PCM WAV.

    Each retained span is sample-addressed. Internal joins use a short linear
    overlap-crossfade; unlike independent fades to zero, this preserves room
    tone and avoids both a click and an audible micro-dropout.
    """

    source_audio = Path(source_audio)
    output_audio = Path(output_audio)
    sample_rate, channels, duration = _pcm_wav_info(source_audio)
    if sample_rate != 48_000 or channels != 1:
        raise ValueError(
            "speech edit source must be normalized mono 48000 Hz PCM WAV "
            f"(got {channels} channel(s), {sample_rate} Hz)"
        )
    _validate_cuts(cuts, duration=duration + 1 / sample_rate)
    output_audio.parent.mkdir(parents=True, exist_ok=True)
    if not cuts:
        shutil.copyfile(source_audio, output_audio)
        return SpeechEditExecution(
            filtergraph="copy",
            cut_crossfades=tuple(0.0 for _cut in cuts),
            join_ranges_samples=(),
            crossfade_samples=(),
        )

    with wave.open(str(source_audio), "rb") as wav:
        frame_count = wav.getnframes()
    spans = _keep_sample_spans(cuts, sample_rate=sample_rate, frame_count=frame_count)
    filters: list[str] = []
    for index, (start, end) in enumerate(spans):
        filters.append(
            f"[0:a]atrim=start_sample={start}:end_sample={end},"
            f"asetpts=PTS-STARTPTS[s{index}]"
        )

    requested_crossfade = max(1, round(crossfade_seconds * sample_rate))
    join_crossfades: list[int] = []
    for left, right in zip(spans, spans[1:]):
        left_length = left[1] - left[0]
        right_length = right[1] - right[0]
        join_crossfades.append(min(
            requested_crossfade,
            max(1, left_length // 4),
            max(1, right_length // 4),
        ))
    if len(spans) == 1:
        filtergraph = filters[0][:-4] + "[out]"
    else:
        previous = "s0"
        for index, crossfade in enumerate(join_crossfades):
            output_label = "out" if index == len(join_crossfades) - 1 else f"x{index}"
            filters.append(
                f"[{previous}][s{index + 1}]"
                f"acrossfade=ns={crossfade}:c1=tri:c2=tri[{output_label}]"
            )
            previous = output_label
        filtergraph = ";".join(filters)

    cmd = [
        "ffmpeg", "-y", "-hide_banner", "-i", str(source_audio),
        "-filter_complex", filtergraph, "-map", "[out]",
        "-ac", "1", "-ar", str(sample_rate), "-c:a", "pcm_s16le",
        str(output_audio),
    ]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True,
            encoding="utf-8", errors="replace",
        )
    except FileNotFoundError as exc:
        raise RuntimeError("speech edit: ffmpeg not found on PATH") from exc
    if result.returncode != 0:
        output_audio.unlink(missing_ok=True)
        raise SpeechEditStageError(
            "speech edit: ffmpeg apply failed\n"
            f"filtergraph: {filtergraph}\n"
            f"stderr (tail):\n{(result.stderr or result.stdout)[-1500:]}"
        )
    cut_crossfades: list[float] = []
    internal_join = 0
    for cut in cuts:
        if cut.t0 > 1 / sample_rate and cut.t1 < duration - 1 / sample_rate:
            crossfade = join_crossfades[internal_join]
            cut_crossfades.append(crossfade / sample_rate)
            internal_join += 1
        else:
            cut_crossfades.append(0.0)

    join_ranges: list[tuple[int, int]] = []
    cumulative = spans[0][1] - spans[0][0]
    for index, crossfade in enumerate(join_crossfades):
        join_ranges.append((cumulative - crossfade, cumulative))
        next_length = spans[index + 1][1] - spans[index + 1][0]
        cumulative += next_length - crossfade
    return SpeechEditExecution(
        filtergraph=filtergraph,
        cut_crossfades=tuple(cut_crossfades),
        join_ranges_samples=tuple(join_ranges),
        crossfade_samples=tuple(join_crossfades),
    )


def inspect_join_continuity(
    output_audio: Path,
    execution: SpeechEditExecution,
    *,
    max_step_dbfs: float = -24.0,
) -> tuple[SpeechJoinEvidence, ...]:
    """Reject rendered joins with a click-like sample discontinuity."""

    _sample_rate, samples = _read_pcm16_mono(Path(output_audio))
    evidence: list[SpeechJoinEvidence] = []
    for crossfade, (start, end) in zip(
        execution.crossfade_samples,
        execution.join_ranges_samples,
        strict=True,
    ):
        inspect_start = max(1, start - 1)
        inspect_end = min(len(samples), end + 1)
        largest_step = max(
            (abs(int(samples[index]) - int(samples[index - 1]))
             for index in range(inspect_start, inspect_end)),
            default=0,
        )
        normalized = largest_step / 32768.0
        measured_dbfs = (
            -120.0 if normalized <= 1e-9 else 20.0 * math.log10(normalized)
        )
        join = SpeechJoinEvidence(
            crossfade_samples=crossfade,
            max_step_dbfs=measured_dbfs,
        )
        evidence.append(join)
        if measured_dbfs > max_step_dbfs:
            raise SpeechEditStageError(
                "speech edit: rendered join failed continuity check "
                f"({measured_dbfs:.1f} dBFS step > {max_step_dbfs:.1f} dBFS)"
            )
    return tuple(evidence)


def _index_maps(
    words: Sequence[Mapping[str, object]], cuts: Sequence[SpeechCut],
) -> tuple[list[int | None], list[int]]:
    old_to_new: list[int | None] = []
    new_to_old: list[int] = []
    for old_index, word in enumerate(words):
        start, end = _word_bounds(word)
        if any(cut.t0 <= start and cut.t1 >= end for cut in cuts):
            old_to_new.append(None)
        else:
            old_to_new.append(len(new_to_old))
            new_to_old.append(old_index)
    return old_to_new, new_to_old


def execute_speech_edit(
    source_audio: Path,
    source_words: Path,
    output_audio: Path,
    output_words: Path,
    artifact_path: Path,
    *,
    plan: SpeechEditPlan,
    output_audio_ref: str | None = None,
    output_words_ref: str | None = None,
) -> SpeechEditResult:
    """Verify and execute a hash-bound plan into an auditable output bundle."""

    source_audio = Path(source_audio)
    source_words = Path(source_words)
    output_audio = Path(output_audio)
    output_words = Path(output_words)
    artifact_path = Path(artifact_path)
    actual_audio_hash = sha256_file(source_audio)
    if actual_audio_hash != plan.input_audio_sha256:
        raise ValueError("speech edit plan audio hash is stale")
    actual_words_hash = sha256_file(source_words)
    if actual_words_hash != plan.input_words_sha256:
        raise ValueError("speech edit plan words hash is stale")

    sample_rate, _, source_duration = _pcm_wav_info(source_audio)
    if abs(source_duration - plan.source_duration) > 1 / sample_rate:
        raise ValueError(
            "speech edit plan duration does not match the source audio "
            f"({plan.source_duration} != {source_duration})"
        )
    _validate_cuts(plan.cuts, duration=source_duration + 1 / sample_rate)
    payload = json.loads(source_words.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError("words JSON must contain an object")
    raw_words = payload.get("words", [])
    if not isinstance(raw_words, list):
        raise ValueError("words payload must contain a words list")
    payload["duration"] = source_duration

    resolved = resolve_safe_cuts(source_audio, payload, plan.cuts)
    execution = apply_speech_edit(source_audio, output_audio, resolved.applied)
    try:
        joins = inspect_join_continuity(output_audio, execution)
    except Exception:
        output_audio.unlink(missing_ok=True)
        raise
    _, _, output_duration = _pcm_wav_info(output_audio)
    remapped = remap_words_payload(
        payload,
        resolved.applied,
        output_audio=output_audio_ref if output_audio_ref is not None else str(output_audio),
        cut_crossfades=execution.cut_crossfades,
    )
    remapped["duration"] = output_duration
    output_words.parent.mkdir(parents=True, exist_ok=True)
    output_words.write_text(
        json.dumps(remapped, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    old_to_new, new_to_old = _index_maps(raw_words, resolved.applied)
    audit = plan.to_dict()
    audit["input"].update({
        "audio_path": str(source_audio),
        "words_path": str(source_words),
        "sample_rate": sample_rate,
    })
    audit["resolution"] = {
        "applied_cuts": [cut.to_dict() for cut in resolved.applied],
        "skipped_cuts": [cut.to_dict() for cut in resolved.skipped],
        "boundaries": [boundary.to_dict() for boundary in resolved.boundaries],
    }
    audit["maps"] = {"old_to_new": old_to_new, "new_to_old": new_to_old}
    audit["execution"] = {
        "ffmpeg_filtergraph": execution.filtergraph,
        "cut_crossfades": list(execution.cut_crossfades),
    }
    audit["joins"] = [join.to_dict() for join in joins]
    audit["output"] = {
        "audio_path": output_audio_ref if output_audio_ref is not None else str(output_audio),
        "audio_sha256": sha256_file(output_audio),
        "words_path": output_words_ref if output_words_ref is not None else str(output_words),
        "words_sha256": sha256_file(output_words),
        "duration": output_duration,
    }
    artifact_path.parent.mkdir(parents=True, exist_ok=True)
    artifact_path.write_text(
        json.dumps(audit, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return SpeechEditResult(
        audio=output_audio,
        words=output_words,
        artifact=artifact_path,
        source_duration=source_duration,
        duration=output_duration,
        removed_duration=source_duration - output_duration,
        cut_count=len(resolved.applied),
        skipped_cut_count=len(resolved.skipped),
    )


__all__ = [
    "SpeechCut",
    "SpeechEditPlan",
    "SpeechEditResult",
    "SpeechEditExecution",
    "SpeechEditStageError",
    "SpeechJoinEvidence",
    "SpeechBoundaryEvidence",
    "SkippedSpeechCut",
    "ResolvedSpeechCuts",
    "apply_speech_edit",
    "build_automatic_plan",
    "build_automatic_plan_from_files",
    "detect_silences",
    "execute_speech_edit",
    "inspect_join_continuity",
    "parse_silencedetect",
    "remap_words_payload",
    "resolve_safe_cuts",
    "sha256_file",
]
