"""Deterministic script and voice-over preflight checks.

This module intentionally uses only the standard library.  It provides the
mechanical half of the script-writer/VO contract from
``PLAN_STUDIO_AUTOPILOT_60``: a small creator profile, natural-language
linting, exact approval lineage, proper-name transcript checks, and a cheap
first-three-seconds PCM WAV check.  It does not try to replace a human style
review and never invokes an AI runtime.
"""
from __future__ import annotations

import hashlib
import json
import math
import re
import statistics
import struct
import unicodedata
import wave
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover - package requires Python 3.12+
    tomllib = None  # type: ignore[assignment]


_WORD_RE = re.compile(r"[^\W_]+(?:[-'][^\W_]+)*", re.UNICODE)
_SENTENCE_RE = re.compile(r"[^.!?\u2026]+(?:[.!?\u2026]+|$)", re.UNICODE)
_SOLO_PLURAL_PRONOUNS = (
    "мы",
    "нам",
    "нас",
    "нами",
    "наш",
    "наша",
    "наше",
    "наши",
    "нашего",
    "нашему",
    "we",
    "us",
    "our",
    "ours",
)


@dataclass(frozen=True)
class PreflightIssue:
    """One actionable preflight finding."""

    code: str
    message: str
    severity: str = "error"
    sentence_index: int | None = None
    value: str | None = None


@dataclass(frozen=True)
class DuplicateSentence:
    sentence: str
    first_index: int
    duplicate_index: int


@dataclass(frozen=True)
class CreatorProfile:
    """The non-generative subset of ``creator_profile.toml``.

    ``brand_spellings`` maps a canonical display spelling to known wrong or
    phonetic variants.  Canonical values are also checked for exact casing in
    scripts.  Transcript matching is case-insensitive because speech-to-text
    backends commonly lowercase all tokens.
    """

    first_person: str = "singular"
    max_sentence_words: int = 20
    forbidden_cliches: tuple[str, ...] = ()
    forbidden_terms: tuple[str, ...] = ()
    brand_spellings: Mapping[str, tuple[str, ...]] | None = None
    proper_names: tuple[str, ...] = ()

    def __post_init__(self) -> None:
        first_person = self.first_person.strip().casefold()
        if first_person == "solo":
            first_person = "singular"
        if first_person != "singular":
            raise ValueError("creator profile first_person must be 'singular' (or 'solo')")
        if isinstance(self.max_sentence_words, bool) or self.max_sentence_words < 1:
            raise ValueError("creator profile max_sentence_words must be a positive integer")

        brands: dict[str, tuple[str, ...]] = {}
        for canonical, variants in (self.brand_spellings or {}).items():
            canonical_text = str(canonical).strip()
            if not canonical_text:
                raise ValueError("creator profile brand spelling cannot be empty")
            if isinstance(variants, str):
                normalized_variants = (variants,)
            else:
                normalized_variants = tuple(str(item) for item in variants)
            brands[canonical_text] = tuple(v.strip() for v in normalized_variants if v.strip())

        object.__setattr__(self, "first_person", first_person)
        object.__setattr__(self, "forbidden_cliches", _string_tuple(self.forbidden_cliches))
        object.__setattr__(self, "forbidden_terms", _string_tuple(self.forbidden_terms))
        object.__setattr__(self, "brand_spellings", brands)
        object.__setattr__(self, "proper_names", _string_tuple(self.proper_names))

    @classmethod
    def from_toml(cls, path: str | Path) -> "CreatorProfile":
        return load_creator_profile(path)


def _string_tuple(value: Iterable[Any] | str | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, str):
        value = (value,)
    return tuple(text for item in value if (text := str(item).strip()))


def _table(data: Mapping[str, Any], name: str) -> Mapping[str, Any]:
    value = data.get(name, {})
    if value is None:
        return {}
    if not isinstance(value, Mapping):
        raise ValueError(f"creator profile [{name}] must be a TOML table")
    return value


def load_creator_profile(path: str | Path) -> CreatorProfile:
    """Load and validate a small creator profile from TOML.

    The documented table form is preferred, while top-level keys are
    accepted too so profiles can stay genuinely short::

        [voice]
        first_person = "singular"
        max_sentence_words = 18
        forbidden_cliches = ["В современном мире"]

        [brand_spellings]
        Neotolis = ["неотолис"]

        [transcript]
        proper_names = ["Neotolis", "Steam"]
    """
    profile_path = Path(path)
    with profile_path.open("rb") as stream:
        data = tomllib.load(stream)
    if not isinstance(data, Mapping):  # defensive; tomllib always returns dict
        raise ValueError("creator profile TOML root must be a table")

    voice = _table(data, "voice")
    transcript = _table(data, "transcript")
    raw_brands = data.get("brand_spellings", data.get("brands", {}))
    if isinstance(raw_brands, Sequence) and not isinstance(raw_brands, (str, bytes)):
        brands: dict[str, tuple[str, ...]] = {str(name): () for name in raw_brands}
    elif isinstance(raw_brands, Mapping):
        brands = {}
        for canonical, variants in raw_brands.items():
            if isinstance(variants, Mapping):
                aliases = variants.get("aliases", variants.get("variants", ()))
            else:
                aliases = variants
            brands[str(canonical)] = _string_tuple(aliases)
    else:
        raise ValueError("creator profile brand_spellings must be a TOML table or array")

    def setting(name: str, default: Any) -> Any:
        return voice.get(name, data.get(name, default))

    proper_names = transcript.get("proper_names", data.get("proper_names", ()))
    return CreatorProfile(
        first_person=str(setting("first_person", "singular")),
        max_sentence_words=int(setting("max_sentence_words", 20)),
        forbidden_cliches=_string_tuple(setting("forbidden_cliches", ())),
        forbidden_terms=_string_tuple(setting("forbidden_terms", ())),
        brand_spellings=brands,
        proper_names=_string_tuple(proper_names),
    )


@dataclass(frozen=True)
class ScriptLintResult:
    issues: tuple[PreflightIssue, ...]
    sentence_count: int
    word_count: int

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


def _sentences(text: str) -> list[str]:
    normalized = unicodedata.normalize("NFC", text)
    return [match.group(0).strip() for match in _SENTENCE_RE.finditer(normalized) if match.group(0).strip()]


def _normalized_sentence(sentence: str) -> str:
    words = _WORD_RE.findall(unicodedata.normalize("NFKC", sentence).casefold())
    return " ".join(words)


def find_duplicate_sentences(text: str) -> tuple[DuplicateSentence, ...]:
    """Find repeated sentence formulations after harmless normalization."""
    first_seen: dict[str, int] = {}
    duplicates: list[DuplicateSentence] = []
    for index, sentence in enumerate(_sentences(text)):
        normalized = _normalized_sentence(sentence)
        if not normalized:
            continue
        if normalized in first_seen:
            duplicates.append(DuplicateSentence(normalized, first_seen[normalized], index))
        else:
            first_seen[normalized] = index
    return tuple(duplicates)


def _phrase_pattern(phrase: str) -> re.Pattern[str]:
    # Bound only word-like phrase edges.  This catches a term without also
    # flagging it as a substring of an unrelated longer word.
    escaped = re.escape(phrase.strip()).replace(r"\ ", r"\s+")
    prefix = r"(?<!\w)" if phrase and phrase[0].isalnum() else ""
    suffix = r"(?!\w)" if phrase and phrase[-1].isalnum() else ""
    return re.compile(prefix + escaped + suffix, re.IGNORECASE | re.UNICODE)


def lint_script(text: str, profile: CreatorProfile) -> ScriptLintResult:
    """Run deterministic natural-script gates against ``text``."""
    if not isinstance(text, str):
        raise TypeError("script text must be str")
    sentences = _sentences(text)
    issues: list[PreflightIssue] = []

    if profile.first_person == "singular":
        for pronoun in _SOLO_PLURAL_PRONOUNS:
            match = _phrase_pattern(pronoun).search(text)
            if match:
                issues.append(PreflightIssue(
                    "VQ-SCRIPT-VOICE",
                    f"Solo creator profile forbids plural first-person term {match.group(0)!r}",
                    value=match.group(0),
                ))
                break

    for sentence_index, sentence in enumerate(sentences):
        count = len(_WORD_RE.findall(sentence))
        if count > profile.max_sentence_words:
            issues.append(PreflightIssue(
                "VQ-SCRIPT-LENGTH",
                f"Sentence has {count} words; profile maximum is {profile.max_sentence_words}",
                sentence_index=sentence_index,
                value=sentence,
            ))

    for phrase in profile.forbidden_cliches:
        if _phrase_pattern(phrase).search(text):
            issues.append(PreflightIssue(
                "VQ-SCRIPT-AI",
                f"Forbidden scripted cliché: {phrase!r}",
                value=phrase,
            ))
    for term in profile.forbidden_terms:
        if _phrase_pattern(term).search(text):
            issues.append(PreflightIssue(
                "VQ-SCRIPT-TERM",
                f"Forbidden creator-profile term: {term!r}",
                value=term,
            ))

    for canonical, variants in (profile.brand_spellings or {}).items():
        canonical_pattern = _phrase_pattern(canonical)
        for match in canonical_pattern.finditer(text):
            if match.group(0) != canonical:
                issues.append(PreflightIssue(
                    "VQ-SCRIPT-BRAND",
                    f"Use canonical brand spelling {canonical!r}, not {match.group(0)!r}",
                    value=match.group(0),
                ))
                break
        else:
            for variant in variants:
                match = _phrase_pattern(variant).search(text)
                if match and variant.casefold() != canonical.casefold():
                    issues.append(PreflightIssue(
                        "VQ-SCRIPT-BRAND",
                        f"Use canonical brand spelling {canonical!r}, not {match.group(0)!r}",
                        value=match.group(0),
                    ))
                    break

    for duplicate in find_duplicate_sentences(text):
        issues.append(PreflightIssue(
            "VQ-SCRIPT-DENSITY",
            f"Sentence {duplicate.duplicate_index + 1} repeats sentence {duplicate.first_index + 1}",
            sentence_index=duplicate.duplicate_index,
            value=duplicate.sentence,
        ))

    return ScriptLintResult(
        issues=tuple(issues),
        sentence_count=len(sentences),
        word_count=len(_WORD_RE.findall(text)),
    )


# An explicit descriptive alias for callers that use the plan's terminology.
lint_natural_script = lint_script


def script_sha256(script: str) -> str:
    """Hash the exact UTF-8 script bytes; whitespace edits intentionally matter."""
    if not isinstance(script, str):
        raise TypeError("script must be str")
    return hashlib.sha256(script.encode("utf-8")).hexdigest()


def canonical_script_text(edit: Any) -> str:
    """Return the one hashable script snapshot shared by Studio and gates.

    Beat ids are deliberately part of the snapshot: moving an otherwise
    unchanged sentence to a different beat changes recording timing and must
    invalidate approval just like a wording edit does.
    """
    order = getattr(edit, "order", None)
    beats = getattr(edit, "beats", None)
    if not isinstance(order, Sequence) or isinstance(order, (str, bytes)):
        raise TypeError("edit.order must be a beat id sequence")
    if not isinstance(beats, Mapping):
        raise TypeError("edit.beats must be a mapping")
    sections: list[str] = []
    for beat_id in order:
        if beat_id not in beats:
            raise ValueError(f"edit.order references missing beat {beat_id!r}")
        vo = getattr(beats[beat_id], "vo", None) or ""
        sections.append(f"## {beat_id}\n{vo}")
    return "\n\n".join(sections).strip() + "\n"


@dataclass(frozen=True)
class ApprovalRecord:
    script_id: str
    script_sha256: str
    approved_by: str | None = None
    approved_at: str | None = None

    def __post_init__(self) -> None:
        digest = self.script_sha256.casefold()
        if not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise ValueError("approval script_sha256 must be a 64-character hexadecimal SHA-256")
        if not self.script_id.strip():
            raise ValueError("approval script_id cannot be empty")
        object.__setattr__(self, "script_sha256", digest)

    def to_dict(self) -> dict[str, str | None]:
        return {
            "script_id": self.script_id,
            "script_sha256": self.script_sha256,
            "approved_by": self.approved_by,
            "approved_at": self.approved_at,
        }

    @classmethod
    def from_dict(cls, value: Mapping[str, Any]) -> "ApprovalRecord":
        digest = value.get("script_sha256", value.get("sha256"))
        if digest is None:
            raise ValueError("approval record is missing script_sha256")
        return cls(
            script_id=str(value.get("script_id", "")),
            script_sha256=str(digest),
            approved_by=None if value.get("approved_by") is None else str(value["approved_by"]),
            approved_at=None if value.get("approved_at") is None else str(value["approved_at"]),
        )

    def verify(self, script: str, *, script_id: str | None = None) -> bool:
        return verify_script_approval(script, self, script_id=script_id).ok


def approve_script(
    script: str,
    *,
    script_id: str,
    approved_by: str | None = None,
    approved_at: str | None = None,
) -> ApprovalRecord:
    """Create an approval snapshot.  The caller supplies any audit timestamp."""
    return ApprovalRecord(
        script_id=script_id,
        script_sha256=script_sha256(script),
        approved_by=approved_by,
        approved_at=approved_at,
    )


@dataclass(frozen=True)
class ApprovalVerification:
    ok: bool
    expected_sha256: str
    actual_sha256: str
    issue: PreflightIssue | None = None


def _coerce_approval(record: ApprovalRecord | Mapping[str, Any] | str | Path) -> ApprovalRecord:
    if isinstance(record, ApprovalRecord):
        return record
    if isinstance(record, (str, Path)):
        with Path(record).open("r", encoding="utf-8") as stream:
            data = json.load(stream)
        if not isinstance(data, Mapping):
            raise ValueError("approval JSON must contain an object")
        return ApprovalRecord.from_dict(data)
    if isinstance(record, Mapping):
        return ApprovalRecord.from_dict(record)
    raise TypeError("approval record must be ApprovalRecord, mapping, or JSON path")


def verify_script_approval(
    script: str,
    record: ApprovalRecord | Mapping[str, Any] | str | Path,
    *,
    script_id: str | None = None,
) -> ApprovalVerification:
    """Verify exact script bytes and, when supplied, the script id lineage."""
    approval = _coerce_approval(record)
    actual = script_sha256(script)
    id_matches = script_id is None or script_id == approval.script_id
    ok = actual == approval.script_sha256 and id_matches
    issue = None
    if not ok:
        reasons: list[str] = []
        if actual != approval.script_sha256:
            reasons.append("script SHA-256 differs from the approved snapshot")
        if not id_matches:
            reasons.append(f"script id {script_id!r} does not match approved id {approval.script_id!r}")
        issue = PreflightIssue("VQ-SCRIPT-APPROVAL", "; ".join(reasons))
    return ApprovalVerification(ok, approval.script_sha256, actual, issue)


def verify_approval_record(
    script: str,
    record: ApprovalRecord | Mapping[str, Any] | str | Path,
    *,
    script_id: str | None = None,
) -> bool:
    """Boolean convenience wrapper around :func:`verify_script_approval`."""
    return verify_script_approval(script, record, script_id=script_id).ok


@dataclass(frozen=True)
class TranscriptScanResult:
    missing: tuple[str, ...]
    issues: tuple[PreflightIssue, ...]
    token_count: int

    @property
    def ok(self) -> bool:
        return not self.issues


def _transcript_tokens(transcript: Any) -> list[str]:
    if isinstance(transcript, (str, Path)):
        candidate = Path(transcript)
        if candidate.exists():
            with candidate.open("r", encoding="utf-8") as stream:
                transcript = json.load(stream)
        elif isinstance(transcript, str):
            return _WORD_RE.findall(transcript)
    if isinstance(transcript, Mapping):
        if "words" in transcript:
            transcript = transcript["words"]
        elif "segments" in transcript:
            transcript = [
                word
                for segment in transcript["segments"]
                for word in (segment.get("words", ()) if isinstance(segment, Mapping) else ())
            ]
        else:
            transcript = ()
    if not isinstance(transcript, Sequence) or isinstance(transcript, (str, bytes)):
        raise TypeError("transcript must be words JSON, a token sequence, text, or JSON path")

    tokens: list[str] = []
    for item in transcript:
        if isinstance(item, Mapping):
            raw = item.get("word", item.get("text", ""))
        else:
            raw = item
        tokens.extend(_WORD_RE.findall(str(raw)))
    return tokens


def scan_transcript_proper_names(
    transcript: Any,
    proper_names: Iterable[str] | CreatorProfile,
) -> TranscriptScanResult:
    """Require every expected proper name as contiguous transcript tokens.

    Matching is case-insensitive and ignores punctuation, but otherwise exact:
    ``trolley`` cannot silently become ``train``.  A :class:`CreatorProfile`
    uses ``proper_names`` when present, otherwise its canonical brand names.
    """
    tokens = [token.casefold() for token in _transcript_tokens(transcript)]
    if isinstance(proper_names, CreatorProfile):
        expected = proper_names.proper_names or tuple((proper_names.brand_spellings or {}).keys())
    else:
        expected = _string_tuple(proper_names)

    missing: list[str] = []
    for name in expected:
        wanted = [word.casefold() for word in _WORD_RE.findall(name)]
        found = bool(wanted) and any(
            tokens[start : start + len(wanted)] == wanted
            for start in range(0, len(tokens) - len(wanted) + 1)
        )
        if not found:
            missing.append(name)

    issues = tuple(
        PreflightIssue(
            "VQ-TRANSCRIPT-PROPER",
            f"Transcript is missing or garbled at expected proper name {name!r}",
            value=name,
        )
        for name in missing
    )
    return TranscriptScanResult(tuple(missing), issues, len(tokens))


# Short alias useful at call sites that already say "token scan".
scan_transcript_tokens = scan_transcript_proper_names


@dataclass(frozen=True)
class WavFirst3sResult:
    path: Path
    sample_rate: int
    channels: int
    analyzed_seconds: float
    peak: float
    rms: float
    clipping: bool
    impulse: bool
    noise_jump: bool
    issues: tuple[PreflightIssue, ...]

    @property
    def ok(self) -> bool:
        return not any(issue.severity == "error" for issue in self.issues)


def _decode_pcm(raw: bytes, sample_width: int) -> list[int]:
    if sample_width == 1:
        return [value - 128 for value in raw]
    if sample_width == 2:
        usable = len(raw) - len(raw) % 2
        return list(struct.unpack(f"<{usable // 2}h", raw[:usable]))
    if sample_width == 3:
        values: list[int] = []
        for offset in range(0, len(raw) - 2, 3):
            value = int.from_bytes(raw[offset : offset + 3], "little", signed=False)
            if value & 0x800000:
                value -= 1 << 24
            values.append(value)
        return values
    if sample_width == 4:
        usable = len(raw) - len(raw) % 4
        return list(struct.unpack(f"<{usable // 4}i", raw[:usable]))
    raise ValueError(f"unsupported PCM WAV sample width: {sample_width} bytes")


def _channel_samples(samples: Sequence[float], channels: int) -> list[list[float]]:
    return [list(samples[channel::channels]) for channel in range(channels)]


def _has_impulse(channels: Sequence[Sequence[float]], threshold: float) -> bool:
    for samples in channels:
        for index in range(1, len(samples) - 1):
            value = samples[index]
            if (
                abs(value) >= threshold
                and abs(value - samples[index - 1]) >= threshold
                and abs(value - samples[index + 1]) >= threshold
            ):
                return True
    return False


def _window_rms(samples: Sequence[float], window_frames: int) -> list[float]:
    values: list[float] = []
    for start in range(0, len(samples), window_frames):
        window = samples[start : start + window_frames]
        if len(window) < max(1, window_frames // 2):
            continue
        values.append(math.sqrt(sum(value * value for value in window) / len(window)))
    return values


def check_wav_first_3s(
    path: str | Path,
    *,
    seconds: float = 3.0,
    clipping_threshold: float = 0.985,
    impulse_threshold: float = 0.50,
    noise_jump_ratio: float = 4.0,
    noise_jump_min_delta: float = 0.01,
) -> WavFirst3sResult:
    """Inspect the first ``seconds`` of an uncompressed PCM WAV.

    Clipping is two or more near-full-scale samples.  An impulse is an
    isolated high-amplitude sample with a steep edge on both sides.  Noise
    jump compares 250 ms RMS windows and is deliberately a warning: speech
    beginning after room tone can resemble a noise-floor step, while an
    impulse or clipping is mechanically unsafe and blocks the take.
    """
    wav_path = Path(path)
    if seconds <= 0:
        raise ValueError("seconds must be positive")
    with wave.open(str(wav_path), "rb") as stream:
        if stream.getcomptype() != "NONE":
            raise ValueError(f"only uncompressed PCM WAV is supported, got {stream.getcomptype()!r}")
        channels = stream.getnchannels()
        sample_rate = stream.getframerate()
        sample_width = stream.getsampwidth()
        if channels < 1 or sample_rate < 1:
            raise ValueError("WAV must have positive channel count and sample rate")
        frame_count = min(stream.getnframes(), int(round(seconds * sample_rate)))
        raw = stream.readframes(frame_count)

    integers = _decode_pcm(raw, sample_width)
    if not integers or frame_count == 0:
        raise ValueError("WAV contains no samples in the analysis window")
    scale = float(1 << (sample_width * 8 - 1))
    normalized = [sample / scale for sample in integers]
    per_channel = _channel_samples(normalized, channels)

    peak = max(abs(sample) for sample in normalized)
    rms = math.sqrt(sum(sample * sample for sample in normalized) / len(normalized))
    clipped_samples = sum(abs(sample) >= clipping_threshold for sample in normalized)
    clipping = clipped_samples >= 2
    impulse = _has_impulse(per_channel, impulse_threshold)

    window_frames = max(1, sample_rate // 4)
    windows: list[float] = []
    for channel in per_channel:
        windows.extend(_window_rms(channel, window_frames))
    positive_windows = [value for value in windows if value > 1e-7]
    noise_jump = False
    if len(positive_windows) >= 2:
        low = statistics.median_low(sorted(positive_windows)[: max(1, len(positive_windows) // 3)])
        high = max(positive_windows)
        noise_jump = high - low >= noise_jump_min_delta and high >= low * noise_jump_ratio

    issues: list[PreflightIssue] = []
    if clipping:
        issues.append(PreflightIssue(
            "VQ-AUDIO-START-CLIPPING",
            f"First {seconds:g}s contains {clipped_samples} near-full-scale PCM samples",
        ))
    if impulse:
        issues.append(PreflightIssue(
            "VQ-AUDIO-START-IMPULSE",
            f"First {seconds:g}s contains a click/impulse edge",
        ))
    if noise_jump:
        issues.append(PreflightIssue(
            "VQ-AUDIO-START-NOISE",
            f"First {seconds:g}s contains an anomalous RMS/noise-floor jump",
            severity="warning",
        ))

    return WavFirst3sResult(
        path=wav_path,
        sample_rate=sample_rate,
        channels=channels,
        analyzed_seconds=frame_count / sample_rate,
        peak=peak,
        rms=rms,
        clipping=clipping,
        impulse=impulse,
        noise_jump=noise_jump,
        issues=tuple(issues),
    )


# Less implementation-specific alias for callers.
check_wav_start = check_wav_first_3s


__all__ = [
    "ApprovalRecord",
    "ApprovalVerification",
    "CreatorProfile",
    "DuplicateSentence",
    "PreflightIssue",
    "ScriptLintResult",
    "TranscriptScanResult",
    "WavFirst3sResult",
    "approve_script",
    "canonical_script_text",
    "check_wav_first_3s",
    "check_wav_start",
    "find_duplicate_sentences",
    "lint_natural_script",
    "lint_script",
    "load_creator_profile",
    "scan_transcript_proper_names",
    "scan_transcript_tokens",
    "script_sha256",
    "verify_approval_record",
    "verify_script_approval",
]
