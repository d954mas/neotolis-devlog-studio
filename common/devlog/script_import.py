"""Convert a draft script into a starter beats.py file."""
from __future__ import annotations

import re
from dataclasses import dataclass


@dataclass(frozen=True)
class ScriptBeat:
    beat_id: str
    title: str
    vo: str


@dataclass(frozen=True)
class ScriptChunk:
    text: str
    start_word: int
    end_word: int


def _slug(value: str, fallback: str) -> str:
    slug = re.sub(r"[^A-Za-z0-9]+", "_", value.strip().lower()).strip("_")
    if not slug or not re.match(r"[A-Za-z_]", slug):
        slug = fallback
    return slug[:40]


def _title_from_text(text: str, index: int) -> str:
    first = next((line.strip() for line in text.splitlines() if line.strip()), "")
    first = re.split(r"[.!?]", first, maxsplit=1)[0].strip()
    return first[:60] or f"Beat {index}"


def parse_script_beats(text: str, *, prefix: str = "b") -> list[ScriptBeat]:
    """Split script text into beats.

    Markdown headings create explicit beats. Without headings, blank-line
    paragraphs become beats, which matches the fastest rough-outline workflow.
    """
    lines = text.replace("\r\n", "\n").replace("\r", "\n").split("\n")
    has_headings = any(re.match(r"^#{1,3}\s+\S", line) for line in lines)
    beats: list[tuple[str | None, str]] = []

    if has_headings:
        title: str | None = None
        body: list[str] = []
        for line in lines:
            match = re.match(r"^#{1,3}\s+(.+?)\s*$", line)
            if match:
                if body:
                    beats.append((title, "\n".join(body).strip()))
                    body = []
                title = match.group(1).strip()
            else:
                body.append(line)
        if body:
            beats.append((title, "\n".join(body).strip()))
    else:
        parts = [p.strip() for p in re.split(r"\n\s*\n", text) if p.strip()]
        beats = [(None, part) for part in parts]

    out: list[ScriptBeat] = []
    used_ids: set[str] = set()
    for idx, (maybe_title, body) in enumerate(beats, start=1):
        if not body:
            continue
        fallback = f"{prefix}{idx:02d}"
        title = maybe_title or _title_from_text(body, idx)
        beat_id = _slug(title, fallback)
        if beat_id in used_ids:
            beat_id = fallback
        used_ids.add(beat_id)
        out.append(ScriptBeat(beat_id=beat_id, title=title, vo=body))
    return out


def _py_string(value: str) -> str:
    return repr(value)


def _word_count(value: str) -> int:
    return len(re.findall(r"\S+", value))


def _split_sentences(value: str) -> list[str]:
    compact = re.sub(r"\s+", " ", value).strip()
    if not compact:
        return []
    parts = re.split(r"(?<=[.!?])\s+", compact)
    return [p.strip() for p in parts if p.strip()]


def _split_words(value: str) -> list[str]:
    return re.findall(r"\S+", value)


def chunk_script_text(value: str, *, max_words: int = 18) -> list[ScriptChunk]:
    """Build starter chunk ranges from sentences and long phrase splits."""
    if max_words < 4:
        raise ValueError("max_words must be >= 4")

    chunks: list[ScriptChunk] = []
    word_cursor = 0
    sentences = _split_sentences(value)
    if not sentences:
        return []

    for sentence in sentences:
        words = _split_words(sentence)
        if not words:
            continue
        for start in range(0, len(words), max_words):
            group = words[start:start + max_words]
            chunk_start = word_cursor + start
            chunk_end = chunk_start + len(group) - 1
            chunks.append(ScriptChunk(
                text=" ".join(group),
                start_word=chunk_start,
                end_word=chunk_end,
            ))
        word_cursor += len(words)
    return chunks


def render_beats_py(
    beats: list[ScriptBeat],
    *,
    output: str = "data/finalize/iter01.mp4",
    max_chunk_words: int = 18,
) -> str:
    if not beats:
        raise ValueError("script produced no beats")

    lines = [
        '"""Beat plan generated from a draft script."""',
        "from devlog.types import Beat, Chunk",
        "",
        "",
        "BEATS: dict[str, Beat] = {",
    ]
    for beat in beats:
        chunks = chunk_script_text(beat.vo, max_words=max_chunk_words)
        if not chunks:
            chunks = [ScriptChunk(text=beat.title, start_word=0, end_word=max(0, _word_count(beat.vo) - 1))]
        lines.extend([
            f"    {_py_string(beat.beat_id)}: Beat(",
            f"        title={_py_string(beat.title)},",
            f"        vo={_py_string(beat.vo)},",
            "        stage=\"Record this take in the studio, run dl audio, then review chunk word ranges.\",",
            f"        audio=\"data/finalize/{beat.beat_id}_audio_final.wav\",",
            f"        words=\"data/finalize/{beat.beat_id}_words.json\",",
            "        chunks=[",
        ])
        for idx, chunk in enumerate(chunks):
            if idx == 0:
                kind_args = "size=170, red_underline=True"
            else:
                kind_args = "size=120"
            lines.append(
                f"            Chunk(words=({chunk.start_word}, {chunk.end_word}), "
                f"kind=\"plate\", text={_py_string(chunk.text.upper())}, {kind_args}),"
            )
        lines.extend([
            "        ],",
            "        face=\"none\",",
            "    ),",
        ])
    order = [beat.beat_id for beat in beats]
    lines.extend([
        "}",
        "",
        f"CONCAT_ORDER: list[str] = {order!r}",
        f"OUTPUT = {_py_string(output)}",
        "",
    ])
    return "\n".join(lines)
