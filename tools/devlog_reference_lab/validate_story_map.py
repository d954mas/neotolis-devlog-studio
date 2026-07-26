#!/usr/bin/env python3
"""Validate the evidence-first story map for a long-form devlog."""

from __future__ import annotations

import argparse
import json
import math
import sys
from pathlib import Path
from typing import Any


SOURCE_ROLES = {"before", "failure", "process", "payoff"}
SOURCE_STATUSES = {"existing", "needs_capture", "placeholder"}


def nonempty(value: Any) -> bool:
    return isinstance(value, str) and bool(value.strip())


def validate_source(
    source: Any,
    location: str,
    production_root: Path,
    *,
    strict: bool,
) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warnings: list[str] = []
    if not isinstance(source, dict):
        return [f"{location}: source must be an object"], warnings
    role = source.get("role")
    path = source.get("path")
    status = source.get("status")
    if role not in SOURCE_ROLES:
        errors.append(
            f"{location}: role must be one of {sorted(SOURCE_ROLES)}, got {role!r}"
        )
    if not nonempty(path):
        errors.append(f"{location}: path is required")
    if status not in SOURCE_STATUSES:
        errors.append(
            f"{location}: status must be one of {sorted(SOURCE_STATUSES)}, got {status!r}"
        )
    if nonempty(path) and status == "existing":
        resolved = (production_root / path).resolve()
        if not resolved.exists():
            errors.append(f"{location}: existing source is missing: {resolved}")
    if status in {"needs_capture", "placeholder"}:
        message = f"{location}: unresolved source ({status}): {path}"
        (errors if strict else warnings).append(message)
    return errors, warnings


def validate_story_map(
    document: dict[str, Any],
    production_root: Path,
    *,
    strict: bool,
) -> tuple[list[str], list[str], dict[str, Any]]:
    errors: list[str] = []
    warnings: list[str] = []

    for field in ("title", "macro_question"):
        if not nonempty(document.get(field)):
            errors.append(f"{field}: non-empty text is required")

    duration = document.get("target_duration_seconds")
    if not isinstance(duration, (int, float)) or duration <= 0:
        errors.append("target_duration_seconds: positive number is required")
        duration = 0
    elif not 360 <= duration <= 720:
        warnings.append(
            "target_duration_seconds: the 6–12 minute long-form working range "
            f"is recommended; got {duration}"
        )

    cold_open = document.get("cold_open")
    if not isinstance(cold_open, dict):
        errors.append("cold_open: object is required")
        cold_open = {}
    for field in ("anomaly", "result_glimpse", "episode_promise"):
        if not nonempty(cold_open.get(field)):
            errors.append(f"cold_open.{field}: non-empty text is required")
    cold_sources = cold_open.get("sources")
    if not isinstance(cold_sources, list) or not cold_sources:
        errors.append("cold_open.sources: at least one source is required")
        cold_sources = []
    for index, source in enumerate(cold_sources):
        source_errors, source_warnings = validate_source(
            source,
            f"cold_open.sources[{index}]",
            production_root,
            strict=strict,
        )
        errors.extend(source_errors)
        warnings.extend(source_warnings)

    mini_arcs = document.get("mini_arcs")
    if not isinstance(mini_arcs, list):
        errors.append("mini_arcs: array is required")
        mini_arcs = []
    minimum_arcs = max(4, math.ceil(float(duration or 0) / 90))
    if len(mini_arcs) < minimum_arcs:
        warnings.append(
            f"mini_arcs: {len(mini_arcs)} supplied; a {duration:g}s episode "
            f"normally needs at least {minimum_arcs} completed problem/payoff arcs"
        )

    prior_end = 0.0
    unresolved_sources = 0
    for index, arc in enumerate(mini_arcs):
        location = f"mini_arcs[{index}]"
        if not isinstance(arc, dict):
            errors.append(f"{location}: arc must be an object")
            continue
        for field in (
            "id",
            "viewer_question",
            "goal",
            "failure",
            "cause",
            "solution",
            "proof",
            "reaction",
        ):
            if not nonempty(arc.get(field)):
                errors.append(f"{location}.{field}: non-empty text is required")

        start = arc.get("planned_start_seconds")
        end = arc.get("planned_end_seconds")
        if not isinstance(start, (int, float)) or not isinstance(end, (int, float)):
            errors.append(f"{location}: numeric planned start/end are required")
        elif start < prior_end:
            errors.append(
                f"{location}: starts at {start}, before the prior arc ends at {prior_end}"
            )
        elif end <= start:
            errors.append(f"{location}: end must be later than start")
        else:
            prior_end = float(end)
            if end - start > 100:
                warnings.append(
                    f"{location}: {end - start:g}s is long for one mini-arc; "
                    "split it or add an internal payoff"
                )

        sources = arc.get("sources")
        if not isinstance(sources, list) or not sources:
            errors.append(f"{location}.sources: evidence sources are required")
            sources = []
        roles: set[str] = set()
        for source_index, source in enumerate(sources):
            source_errors, source_warnings = validate_source(
                source,
                f"{location}.sources[{source_index}]",
                production_root,
                strict=strict,
            )
            errors.extend(source_errors)
            warnings.extend(source_warnings)
            if isinstance(source, dict) and source.get("role") in SOURCE_ROLES:
                roles.add(source["role"])
                if source.get("status") != "existing":
                    unresolved_sources += 1
        for required_role in ("before", "payoff"):
            if required_role not in roles:
                errors.append(
                    f"{location}.sources: required role is missing: {required_role}"
                )
        if not roles.intersection({"failure", "process"}):
            errors.append(
                f"{location}.sources: add failure or process evidence; "
                "a result-only block is a status report"
            )

    ending = document.get("ending")
    if not isinstance(ending, dict):
        errors.append("ending: object is required")
        ending = {}
    for field in ("resolved_question", "honest_status", "next_open_loop"):
        if not nonempty(ending.get(field)):
            errors.append(f"ending.{field}: non-empty text is required")

    metrics = {
        "target_duration_seconds": duration,
        "mini_arc_count": len(mini_arcs),
        "recommended_minimum_arcs": minimum_arcs,
        "unresolved_sources": unresolved_sources,
        "strict": strict,
    }
    return errors, warnings, metrics


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("story_map", type=Path)
    parser.add_argument(
        "--production-root",
        type=Path,
        default=Path.cwd(),
        help="Base directory for source paths in the map.",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Treat needs_capture and placeholder sources as errors.",
    )
    return parser


def main() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    args = build_parser().parse_args()
    document = json.loads(args.story_map.read_text(encoding="utf-8"))
    if not isinstance(document, dict):
        print("ERROR: story map root must be an object")
        return 2
    errors, warnings, metrics = validate_story_map(
        document,
        args.production_root.resolve(),
        strict=args.strict,
    )
    print(json.dumps(metrics, ensure_ascii=False, indent=2))
    for warning in warnings:
        print(f"WARNING: {warning}")
    for error in errors:
        print(f"ERROR: {error}")
    if errors:
        print(f"FAIL: {len(errors)} error(s), {len(warnings)} warning(s)")
        return 1
    print(f"PASS: 0 errors, {len(warnings)} warning(s)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
