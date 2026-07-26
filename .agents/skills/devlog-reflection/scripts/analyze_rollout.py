#!/usr/bin/env python3
"""Summarize Codex rollout tool timing without printing full tool outputs."""

from __future__ import annotations

import argparse
import collections
import datetime as dt
import json
import os
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any


CALL_START_TYPES = {
    "function_call",
    "custom_tool_call",
    "web_search_call",
    "image_generation_call",
    "tool_search_call",
}
CALL_END_TYPES = {
    "function_call_output",
    "custom_tool_call_output",
    "tool_search_output",
}

FEEDBACK_PATTERNS: dict[str, tuple[str, ...]] = {
    "real data / product proof": (
        "реальн",
        "данн",
        "feed",
        "сайт",
        "прод",
        "скрин",
        "превью",
    ),
    "recording / studio UX": (
        "микроф",
        "камер",
        "record",
        "запис",
        "кнопк",
        "караоке",
        "телепромптер",
        "стоп",
    ),
    "script / tone": (
        "нейросет",
        "человеч",
        "ютуб",
        "текст",
        "фраз",
        "суть",
        "скуч",
    ),
    "visual readability": (
        "видно",
        "крупн",
        "визуал",
        "линии",
        "залез",
        "заголов",
        "глитч",
        "резк",
    ),
    "audio / music": (
        "музык",
        "звук",
        "слыш",
        "громк",
        "пауз",
        "склей",
        "переход",
        "голос",
    ),
    "thumbnail / package": (
        "thumbnail",
        "облож",
        "иконк",
        "ноутбук",
        "зелен",
        "маск",
        "youtube",
        "атрибуц",
    ),
    "pipeline / agent process": (
        "агент",
        "критик",
        "пайплайн",
        "рефлекс",
        "скилл",
        "коммит",
        "пуш",
    ),
}


def configure_utf8_stdio() -> None:
    """Keep Markdown reports printable from Windows shells with legacy codepages."""
    for stream in (sys.stdout, sys.stderr):
        reconfigure = getattr(stream, "reconfigure", None)
        if callable(reconfigure):
            reconfigure(encoding="utf-8", errors="replace")


def parse_ts(value: str) -> float:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00")).timestamp()


def short(value: Any, limit: int = 160) -> str:
    text = value if isinstance(value, str) else json.dumps(value, ensure_ascii=False)
    text = " ".join(text.replace("\r", " ").replace("\n", " ").split())
    return text[:limit]


def tool_name(payload: dict[str, Any]) -> str:
    name = payload.get("name") or payload.get("action") or payload.get("type") or "<unknown>"
    return short(name, 120)


def extract_text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, str):
        return value
    if isinstance(value, list):
        return " ".join(extract_text(item) for item in value)
    if isinstance(value, dict):
        parts: list[str] = []
        for key in ("text", "content", "message", "body", "input", "prompt"):
            if key in value:
                parts.append(extract_text(value[key]))
        if not parts:
            for item in value.values():
                parts.append(extract_text(item))
        return " ".join(part for part in parts if part)
    return str(value)


def feedback_categories(text: str) -> list[str]:
    lowered = text.lower()
    result = []
    for name, patterns in FEEDBACK_PATTERNS.items():
        if any(pattern in lowered for pattern in patterns):
            result.append(name)
    return result or ["uncategorized user input"]


def category(row: dict[str, Any]) -> str:
    args = row.get("args", "")
    name = row.get("name", "")
    item_type = row.get("type", "")
    latency = float(row.get("latency") or 0.0)
    wall = row.get("wall")

    if wall is not None and latency > 300 and latency > float(wall) * 4 + 60:
        return "orchestration/session gap"

    if "capture_neotolis" in args or ("real_prod" in args and ("node" in args or "CDP" in args or "ws" in args)):
        return "site capture / preview loading"
    if "hyperframes" in args or "gen-html" in args:
        return "Hyperframes motion assets"
    if name == "wait_agent":
        return "waiting for subagents"
    if "Invoke-WebRequest" in args or "incompetech" in args or "pixabay" in args:
        return "music search/download"
    if "ffmpeg" in args or "ffprobe" in args or "\\dl " in args or ".\\dl" in args or " dl " in args:
        return "render/audio/ffmpeg"
    if name == "image_generation_call" or item_type == "image_generation_call":
        return "image generation"
    if name == "view_image":
        return "image preview"
    if name == "apply_patch":
        return "patch edits"
    if name in {"spawn_agent", "close_agent"}:
        return "subagent orchestration"
    if item_type == "web_search_call" or name.startswith('{"type": "search"') or name.startswith('{"type": "open_page"'):
        return "web search/open"
    if name == "shell_command":
        return "other shell"
    return name


def read_rollout(
    path: Path,
) -> tuple[list[dict[str, Any]], collections.Counter[str], collections.Counter[str], list[float], list[dict[str, Any]]]:
    calls: dict[str, dict[str, Any]] = {}
    event_counts: collections.Counter[str] = collections.Counter()
    item_counts: collections.Counter[str] = collections.Counter()
    aborts: list[float] = []
    user_messages: list[dict[str, Any]] = []

    with path.open("r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle):
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            timestamp = parse_ts(obj["timestamp"])
            payload = obj.get("payload") or {}

            if obj.get("type") == "event_msg":
                event_type = payload.get("type") or "<unknown>"
                event_counts[event_type] += 1
                if event_type == "turn_aborted":
                    aborts.append(timestamp)
                if event_type == "user_message":
                    text = short(extract_text(payload), 220)
                    if text:
                        user_messages.append(
                            {
                                "timestamp": timestamp,
                                "line": index,
                                "text": text,
                                "categories": feedback_categories(text),
                            }
                        )
                continue

            if obj.get("type") != "response_item":
                continue

            item_type = payload.get("type") or "<unknown>"
            item_counts[item_type] += 1

            if item_type in CALL_START_TYPES:
                call_id = payload.get("call_id") or payload.get("id") or f"{item_type}:{index}"
                calls[call_id] = {
                    "line": index,
                    "type": item_type,
                    "name": tool_name(payload),
                    "args": short(payload.get("arguments") or payload.get("input") or "", 220),
                    "start": timestamp,
                }
            elif item_type in CALL_END_TYPES:
                call_id = payload.get("call_id") or payload.get("id")
                if call_id in calls:
                    output = str(payload.get("output") or payload.get("result") or "")
                    calls[call_id]["end"] = timestamp
                    calls[call_id]["output_chars"] = len(output)
                    calls[call_id]["output_lines"] = output.count("\n") + (1 if output else 0)
                    match = re.search(r"Wall time:\s*([0-9.]+) seconds", output)
                    if match:
                        calls[call_id]["wall"] = float(match.group(1))

    rows = []
    for call in calls.values():
        end = call.get("end", call["start"])
        row = dict(call)
        row["latency"] = max(0.0, end - call["start"])
        row["wall"] = call.get("wall")
        row["category"] = category(row)
        rows.append(row)
    return rows, event_counts, item_counts, aborts, user_messages


def codex_home() -> Path:
    return Path(os.environ.get("CODEX_HOME") or Path.home() / ".codex")


def sqlite_files(home: Path) -> list[Path]:
    return sorted(home.glob("state_*.sqlite"), key=lambda p: p.stat().st_mtime, reverse=True)


def normalize_path(value: str) -> Path:
    return Path(value.replace("\\\\?\\", ""))


def rollout_for_thread(thread_id: str, home: Path) -> Path | None:
    for db in sqlite_files(home):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            row = con.execute("select rollout_path from threads where id=?", (thread_id,)).fetchone()
            con.close()
        except sqlite3.Error:
            continue
        if row and row[0]:
            path = normalize_path(row[0])
            if path.exists():
                return path
    return None


def latest_rollout_for_cwd(cwd: str | None, home: Path) -> tuple[str | None, Path | None]:
    if not cwd:
        candidates = sorted((home / "sessions").glob("**/rollout-*.jsonl"), key=lambda p: p.stat().st_mtime, reverse=True)
        return None, candidates[0] if candidates else None

    cwd_norm = str(Path(cwd).resolve()).lower()
    for db in sqlite_files(home):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            rows = con.execute(
                """
                select t.id, t.rollout_path, t.cwd
                from threads t
                where not exists (
                    select 1
                    from thread_spawn_edges e
                    where e.child_thread_id = t.id
                )
                order by t.updated_at desc
                limit 200
                """
            ).fetchall()
            con.close()
        except sqlite3.Error:
            continue
        for thread_id, rollout, thread_cwd in rows:
            if cwd_norm in str(thread_cwd).replace("\\\\?\\", "").lower() and rollout:
                path = normalize_path(rollout)
                if path.exists():
                    return thread_id, path
    return None, None


def child_threads(thread_id: str | None, home: Path) -> list[tuple[str, str, str, Path | None]]:
    if not thread_id:
        return []
    result: list[tuple[str, str, str, Path | None]] = []
    for db in sqlite_files(home):
        try:
            con = sqlite3.connect(f"file:{db}?mode=ro", uri=True)
            rows = con.execute(
                """
                select e.child_thread_id, e.status, coalesce(t.agent_nickname,''), t.rollout_path
                from thread_spawn_edges e
                left join threads t on t.id = e.child_thread_id
                where e.parent_thread_id=?
                """,
                (thread_id,),
            ).fetchall()
            con.close()
        except sqlite3.Error:
            continue
        for child_id, status, nickname, rollout in rows:
            path = normalize_path(rollout) if rollout else None
            result.append((child_id, status, nickname, path if path and path.exists() else None))
        if result:
            break
    return result


def format_seconds(value: float | None) -> str:
    if value is None:
        return "-"
    if value >= 60:
        return f"{value / 60:.1f}m"
    return f"{value:.1f}s"


def print_report(
    path: Path,
    rows: list[dict[str, Any]],
    event_counts: collections.Counter[str],
    item_counts: collections.Counter[str],
    aborts: list[float],
    user_messages: list[dict[str, Any]],
    top: int,
) -> None:
    print("## Tool Timing Audit")
    print()
    print(f"**Rollout:** `{path}`")
    print()
    print("### Counts")
    print()
    print("| Item/Event | Count |")
    print("|---|---:|")
    for key, count in item_counts.most_common():
        print(f"| response_item:{key} | {count} |")
    for key in ["user_message", "agent_message", "task_started", "task_complete", "context_compacted", "turn_aborted"]:
        if event_counts.get(key):
            print(f"| event:{key} | {event_counts[key]} |")
    print()

    grouped: dict[str, dict[str, float | int]] = collections.defaultdict(
        lambda: {
            "calls": 0,
            "wall": 0.0,
            "latency": 0.0,
            "max": 0.0,
            "output_chars": 0,
            "output_lines": 0,
        }
    )
    for row in rows:
        bucket = grouped[row["category"]]
        bucket["calls"] += 1
        bucket["latency"] += float(row["latency"])
        bucket["max"] = max(float(bucket["max"]), float(row["latency"]))
        bucket["output_chars"] += int(row.get("output_chars") or 0)
        bucket["output_lines"] += int(row.get("output_lines") or 0)
        if row.get("wall") is not None:
            bucket["wall"] += float(row["wall"])

    print("### Categories")
    print()
    print("| Category | Calls | Shell Wall | Response Latency | Max Latency | Output chars / lines |")
    print("|---|---:|---:|---:|---:|---:|")
    for name, data in sorted(grouped.items(), key=lambda item: float(item[1]["latency"]), reverse=True):
        print(
            f"| {name} | {int(data['calls'])} | {format_seconds(float(data['wall']))} | "
            f"{format_seconds(float(data['latency']))} | {format_seconds(float(data['max']))} | "
            f"{int(data['output_chars']):,} / {int(data['output_lines']):,} |"
        )
    print()

    print("### Slowest Calls")
    print()
    print("| Latency | Wall | Category | Tool | Args |")
    print("|---:|---:|---|---|---|")
    productive_rows = [row for row in rows if row["category"] != "orchestration/session gap"]
    for row in sorted(productive_rows, key=lambda r: float(r["latency"]), reverse=True)[:top]:
        print(
            f"| {format_seconds(float(row['latency']))} | {format_seconds(row.get('wall'))} | "
            f"{row['category']} | `{row['name']}` | `{row['args']}` |"
        )

    noisy_rows = [row for row in rows if int(row.get("output_chars") or 0) > 0]
    if noisy_rows:
        print()
        print("### Noisiest Calls")
        print()
        print("| Chars | Lines | Category | Tool | Args |")
        print("|---:|---:|---|---|---|")
        for row in sorted(noisy_rows, key=lambda r: int(r.get("output_chars") or 0), reverse=True)[:top]:
            print(
                f"| {int(row.get('output_chars') or 0):,} | {int(row.get('output_lines') or 0):,} | "
                f"{row['category']} | `{row['name']}` | `{row['args']}` |"
            )
    gap_rows = [row for row in rows if row["category"] == "orchestration/session gap"]
    if gap_rows:
        print()
        print("### Orchestration / Session Gaps")
        print()
        print("| Latency | Wall | Tool | Args |")
        print("|---:|---:|---|---|")
        for row in sorted(gap_rows, key=lambda r: float(r["latency"]), reverse=True)[: min(top, 8)]:
            print(
                f"| {format_seconds(float(row['latency']))} | {format_seconds(row.get('wall'))} | "
                f"`{row['name']}` | `{row['args']}` |"
            )
    if aborts:
        print()
        print("### Aborted Turns")
        for value in aborts:
            print(f"- {dt.datetime.fromtimestamp(value, dt.timezone.utc).isoformat()}")

    print_user_feedback(user_messages, top)


def print_user_feedback(user_messages: list[dict[str, Any]], top: int) -> None:
    if not user_messages:
        return

    buckets: dict[str, list[dict[str, Any]]] = collections.defaultdict(list)
    for message in user_messages:
        for item in message["categories"]:
            buckets[item].append(message)

    print()
    print("### User Feedback Loops")
    print()
    print("| Category | Count | First | Last | Latest sample |")
    print("|---|---:|---|---|---|")
    for name, messages in sorted(buckets.items(), key=lambda item: len(item[1]), reverse=True):
        first = dt.datetime.fromtimestamp(messages[0]["timestamp"], dt.timezone.utc).strftime("%H:%M")
        last = dt.datetime.fromtimestamp(messages[-1]["timestamp"], dt.timezone.utc).strftime("%H:%M")
        sample = messages[-1]["text"].replace("|", "/")
        print(f"| {name} | {len(messages)} | {first} | {last} | `{sample}` |")

    repeated = [(name, messages) for name, messages in buckets.items() if len(messages) >= 3]
    if repeated:
        print()
        print("### Repeated Corrections")
        for name, messages in sorted(repeated, key=lambda item: len(item[1]), reverse=True)[:top]:
            samples = " / ".join(f"`{message['text']}`" for message in messages[-3:])
            print(f"- **{name}**: {len(messages)} mentions. Latest: {samples}")


def main() -> int:
    configure_utf8_stdio()
    parser = argparse.ArgumentParser(description="Summarize Codex rollout tool timing.")
    parser.add_argument("--rollout", type=Path, help="Path to rollout-*.jsonl")
    parser.add_argument("--thread-id", help="Codex thread id to resolve through state_*.sqlite")
    parser.add_argument("--cwd", help="Workspace cwd to select the latest matching thread")
    parser.add_argument("--codex-home", type=Path, default=codex_home())
    parser.add_argument("--top", type=int, default=20)
    parser.add_argument("--children", action="store_true", help="Also summarize child subagent rollouts")
    args = parser.parse_args()

    thread_id = args.thread_id
    rollout = args.rollout
    if not rollout and thread_id:
        rollout = rollout_for_thread(thread_id, args.codex_home)
    if not rollout:
        thread_id, rollout = latest_rollout_for_cwd(args.cwd, args.codex_home)
    if not rollout or not rollout.exists():
        raise SystemExit("No rollout JSONL found. Pass --rollout, --thread-id, or --cwd.")

    rows, event_counts, item_counts, aborts, user_messages = read_rollout(rollout)
    print_report(rollout, rows, event_counts, item_counts, aborts, user_messages, args.top)

    if args.children:
        for child_id, status, nickname, child_path in child_threads(thread_id, args.codex_home):
            print()
            print(f"## Child Agent: {nickname or child_id} ({status})")
            if not child_path:
                print("No rollout file found.")
                continue
            child_rows, child_events, child_items, child_aborts, child_messages = read_rollout(child_path)
            print_report(
                child_path,
                child_rows,
                child_events,
                child_items,
                child_aborts,
                child_messages,
                min(args.top, 8),
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
