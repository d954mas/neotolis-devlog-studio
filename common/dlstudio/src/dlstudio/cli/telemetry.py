"""Explicit orchestrator boundary for exact stage/token attribution."""
from __future__ import annotations

import argparse
import os
import time
from pathlib import Path


_RUN_ID_ENV = "DLSTUDIO_RUN_ID"


def current_run_id() -> str | None:
    return os.environ.get(_RUN_ID_ENV) or None


def record_automatic_stage(
    production_root: str | Path,
    *,
    stage: str,
    agent_role: str,
    started_ns: int,
    artifact_paths: list[str | Path] | tuple[str | Path, ...],
) -> None:
    """Record a deterministic CLI stage, or no-op for a legacy project."""

    from dlstudio.production import ProductionError, load_production_manifest
    from dlstudio.services.telemetry import record_telemetry_event

    root = Path(production_root).resolve()
    if not (root / "production.toml").is_file():
        return
    try:
        manifest = load_production_manifest(root)
    except ProductionError:
        return
    existing = tuple(Path(value) for value in artifact_paths if Path(value).is_file())
    record_telemetry_event(
        manifest,
        stage=stage,
        agent_role=agent_role,
        wall_ms=max(0, (time.perf_counter_ns() - started_ns) // 1_000_000),
        human_wait_ms=0,
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        artifact_paths=existing,
        run_id=current_run_id(),
    )


def record_human_checkpoint(
    production_root: str | Path,
    *,
    run_id: str,
    human_active_ms: int,
    artifact_paths: list[str | Path] | tuple[str | Path, ...] = (),
) -> None:
    """Attribute explicitly supplied active author time to one run."""
    if human_active_ms <= 0:
        return
    from dlstudio.production import ProductionError, load_production_manifest
    from dlstudio.services.telemetry import record_telemetry_event

    root = Path(production_root).resolve()
    if not (root / "production.toml").is_file():
        return
    try:
        manifest = load_production_manifest(root)
    except ProductionError:
        return
    existing = tuple(Path(value) for value in artifact_paths if Path(value).is_file())
    record_telemetry_event(
        manifest,
        stage="author_checkpoint",
        agent_role="author",
        wall_ms=human_active_ms,
        human_wait_ms=human_active_ms,
        input_tokens=0,
        cached_input_tokens=0,
        output_tokens=0,
        artifact_paths=existing,
        run_id=run_id,
    )


def cmd_record_stage(args: argparse.Namespace) -> int:
    from dlstudio.cli import CliError, _find_workspace_root
    from dlstudio.production import (
        ProductionError,
        load_production_manifest,
        resolve_production_reference,
    )
    from dlstudio.services.telemetry import TelemetryError, record_telemetry_event

    try:
        root = resolve_production_reference(
            args.production, workspace_root=_find_workspace_root()
        )
        manifest = load_production_manifest(root)
        event = record_telemetry_event(
            manifest,
            stage=args.stage,
            agent_role=args.role,
            wall_ms=args.wall_ms,
            human_wait_ms=args.human_wait_ms,
            input_tokens=args.input_tokens,
            cached_input_tokens=args.cached_input_tokens,
            output_tokens=args.output_tokens,
            artifact_paths=args.artifacts,
            run_id=args.run_id,
        )
    except (ProductionError, TelemetryError) as exc:
        raise CliError(str(exc)) from exc
    print(
        f"[dl2] telemetry: {event.production_id} {event.stage}/"
        f"{event.agent_role} {event.wall_ms}ms"
    )
    return 0


def add_subparser(sub: argparse._SubParsersAction) -> None:
    parser = sub.add_parser(
        "record-stage",
        help="append exact production stage, role, time, token, and artifact facts",
    )
    parser.add_argument(
        "production", help="production path or product_id:production_id reference"
    )
    parser.add_argument("--stage", required=True)
    parser.add_argument("--role", required=True)
    parser.add_argument("--wall-ms", type=int, required=True)
    parser.add_argument("--human-wait-ms", type=int, default=0)
    parser.add_argument("--input-tokens", type=int, default=0)
    parser.add_argument("--cached-input-tokens", type=int, default=0)
    parser.add_argument("--output-tokens", type=int, default=0)
    parser.add_argument("--run-id")
    parser.add_argument(
        "--artifact", dest="artifacts", action="append", default=[]
    )
    parser.set_defaults(func=cmd_record_stage)


__all__ = [
    "add_subparser", "cmd_record_stage", "current_run_id", "record_automatic_stage",
    "record_human_checkpoint",
]
