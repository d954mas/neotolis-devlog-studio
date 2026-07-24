"""Production-scoped, append-only telemetry for deterministic Studio stages.

The service records facts supplied by the orchestrator; it does not estimate
token usage and contains no AI runtime.  JSONL remains the audit log, while a
small JSON summary is atomically regenerated after every successful append.
"""
from __future__ import annotations

import json
import os
import re
import tempfile
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterable, Mapping

from dlstudio.production import ProductionManifest


class TelemetryError(RuntimeError):
    """Base class for telemetry persistence and validation failures."""


class TelemetryValidationError(TelemetryError, ValueError):
    """An event cannot be attributed safely to the target production."""


@dataclass(frozen=True)
class TelemetryEvent:
    version: int
    timestamp: str
    product_id: str
    production_id: str
    run_id: str | None
    stage: str
    agent_role: str
    wall_ms: int
    human_wait_ms: int
    input_tokens: int
    cached_input_tokens: int
    output_tokens: int
    artifact_paths: tuple[str, ...]


@dataclass(frozen=True)
class TelemetryTotals:
    events: int = 0
    wall_ms: int = 0
    human_wait_ms: int = 0
    input_tokens: int = 0
    cached_input_tokens: int = 0
    output_tokens: int = 0


@dataclass(frozen=True)
class TelemetrySummary:
    version: int
    product_id: str
    production_id: str
    by_stage: Mapping[str, TelemetryTotals]
    by_agent_role: Mapping[str, TelemetryTotals]
    by_run_id: Mapping[str, TelemetryTotals]
    agent_roles: tuple[str, ...]
    total: TelemetryTotals


_NAME_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_EVENT_FIELDS = frozenset(TelemetryEvent.__dataclass_fields__)
_LEGACY_EVENT_FIELDS = _EVENT_FIELDS - {"run_id"}
_WRITE_LOCK = threading.RLock()
_DEFAULT_LOG = Path("data/review/telemetry.jsonl")
_DEFAULT_SUMMARY = Path("data/review/telemetry_summary.json")


def _utc_timestamp() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds").replace(
        "+00:00", "Z"
    )


def _validate_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.endswith("Z"):
        raise TelemetryValidationError("timestamp must be an RFC3339 UTC string ending in Z")
    try:
        parsed = datetime.fromisoformat(value[:-1] + "+00:00")
    except ValueError as exc:
        raise TelemetryValidationError("timestamp must be valid RFC3339 UTC") from exc
    if parsed.tzinfo is None or parsed.utcoffset() != timezone.utc.utcoffset(parsed):
        raise TelemetryValidationError("timestamp must be UTC")
    return value


def _nonnegative_int(value: object, label: str) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        raise TelemetryValidationError(f"{label} must be a non-negative integer")
    return value


def _safe_name(value: object, label: str) -> str:
    if not isinstance(value, str) or _NAME_RE.fullmatch(value) is None:
        raise TelemetryValidationError(
            f"{label} must match {_NAME_RE.pattern!r}"
        )
    return value


def _inside(path: Path, root: Path) -> bool:
    try:
        path.relative_to(root)
        return True
    except ValueError:
        return False


def _allowed_artifact(manifest: ProductionManifest, path: Path) -> bool:
    return _inside(path, manifest.root.resolve()) or _inside(
        path, manifest.delivery_dir.resolve()
    )


def _artifact_for_record(manifest: ProductionManifest, value: str | Path) -> str:
    raw = Path(value)
    resolved = (manifest.root / raw).resolve() if not raw.is_absolute() else raw.resolve()
    if not _allowed_artifact(manifest, resolved):
        raise TelemetryValidationError(
            f"artifact must stay inside production or delivery: {resolved}"
        )
    if resolved.is_symlink() or not resolved.is_file():
        raise TelemetryValidationError(f"artifact must be an existing regular file: {resolved}")
    try:
        return resolved.relative_to(manifest.product.root.resolve()).as_posix()
    except ValueError as exc:  # defensive: both allowed roots are product children
        raise TelemetryValidationError(f"artifact escapes product root: {resolved}") from exc


def _artifact_from_log(manifest: ProductionManifest, value: object) -> str:
    if not isinstance(value, str) or not value:
        raise TelemetryValidationError("artifact_paths must contain non-empty strings")
    path = Path(value)
    if path.is_absolute() or path.drive or ".." in path.parts:
        raise TelemetryValidationError("logged artifact path must be product-relative")
    resolved = (manifest.product.root / path).resolve()
    if not _allowed_artifact(manifest, resolved):
        raise TelemetryValidationError(f"logged artifact is outside production scope: {value}")
    return resolved.relative_to(manifest.product.root.resolve()).as_posix()


def _event(
    manifest: ProductionManifest,
    *,
    version: object = 1,
    timestamp: object,
    product_id: object,
    production_id: object,
    run_id: object = None,
    stage: object,
    agent_role: object,
    wall_ms: object,
    human_wait_ms: object,
    input_tokens: object,
    cached_input_tokens: object,
    output_tokens: object,
    artifact_paths: object,
    from_log: bool,
) -> TelemetryEvent:
    if version != 1:
        raise TelemetryValidationError(f"unsupported telemetry event version: {version!r}")
    if product_id != manifest.product.id or production_id != manifest.id:
        raise TelemetryValidationError(
            "telemetry product_id/production_id do not match the target manifest"
        )
    if run_id is not None:
        run_id = _safe_name(run_id, "run_id")
    wall = _nonnegative_int(wall_ms, "wall_ms")
    human_wait = _nonnegative_int(human_wait_ms, "human_wait_ms")
    inputs = _nonnegative_int(input_tokens, "input_tokens")
    cached = _nonnegative_int(cached_input_tokens, "cached_input_tokens")
    outputs = _nonnegative_int(output_tokens, "output_tokens")
    if human_wait > wall:
        raise TelemetryValidationError("human_wait_ms cannot exceed wall_ms")
    if cached > inputs:
        raise TelemetryValidationError("cached_input_tokens cannot exceed input_tokens")
    if not isinstance(artifact_paths, (list, tuple)):
        raise TelemetryValidationError("artifact_paths must be an array")
    converter = _artifact_from_log if from_log else _artifact_for_record
    artifacts = tuple(converter(manifest, path) for path in artifact_paths)
    if len(set(artifacts)) != len(artifacts):
        raise TelemetryValidationError("artifact_paths must not contain duplicates")
    return TelemetryEvent(
        version=1,
        timestamp=_validate_timestamp(timestamp),
        product_id=manifest.product.id,
        production_id=manifest.id,
        run_id=run_id,
        stage=_safe_name(stage, "stage"),
        agent_role=_safe_name(agent_role, "agent_role"),
        wall_ms=wall,
        human_wait_ms=human_wait,
        input_tokens=inputs,
        cached_input_tokens=cached,
        output_tokens=outputs,
        artifact_paths=artifacts,
    )


def _totals(events: Iterable[TelemetryEvent]) -> TelemetryTotals:
    values = tuple(events)
    return TelemetryTotals(
        events=len(values),
        wall_ms=sum(item.wall_ms for item in values),
        human_wait_ms=sum(item.human_wait_ms for item in values),
        input_tokens=sum(item.input_tokens for item in values),
        cached_input_tokens=sum(item.cached_input_tokens for item in values),
        output_tokens=sum(item.output_tokens for item in values),
    )


def summarize_telemetry(events: Iterable[TelemetryEvent]) -> TelemetrySummary:
    """Aggregate one production's immutable events by stage and in total."""
    values = tuple(events)
    if not values:
        raise TelemetryValidationError("cannot summarize an empty telemetry stream")
    identities = {(item.product_id, item.production_id) for item in values}
    if len(identities) != 1:
        raise TelemetryValidationError("telemetry summary cannot mix productions")
    product_id, production_id = next(iter(identities))
    stages = sorted({item.stage for item in values})
    roles = tuple(sorted({item.agent_role for item in values}))
    return TelemetrySummary(
        version=1,
        product_id=product_id,
        production_id=production_id,
        by_stage={
            stage: _totals(item for item in values if item.stage == stage)
            for stage in stages
        },
        by_agent_role={
            role: _totals(item for item in values if item.agent_role == role)
            for role in roles
        },
        by_run_id={
            run_id: _totals(item for item in values if item.run_id == run_id)
            for run_id in sorted({item.run_id for item in values if item.run_id})
        },
        agent_roles=roles,
        total=_totals(values),
    )


def _summary_payload(summary: TelemetrySummary) -> dict[str, object]:
    return {
        "version": summary.version,
        "product_id": summary.product_id,
        "production_id": summary.production_id,
        "by_stage": {
            stage: asdict(totals) for stage, totals in summary.by_stage.items()
        },
        "by_agent_role": {
            role: asdict(totals)
            for role, totals in summary.by_agent_role.items()
        },
        "by_run_id": {
            run_id: asdict(totals) for run_id, totals in summary.by_run_id.items()
        },
        "agent_roles": list(summary.agent_roles),
        "total": asdict(summary.total),
    }


def _atomic_write_json(path: Path, payload: Mapping[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=path.parent
    )
    temporary = Path(temporary_name)
    try:
        with os.fdopen(handle, "w", encoding="utf-8", newline="\n") as stream:
            json.dump(payload, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def load_telemetry_events(
    manifest: ProductionManifest,
    *,
    log_path: str | Path | None = None,
) -> tuple[TelemetryEvent, ...]:
    """Read and strictly validate the production's JSONL audit stream."""
    if not isinstance(manifest, ProductionManifest):
        raise TypeError("manifest must be a ProductionManifest")
    path = Path(log_path) if log_path is not None else manifest.root / _DEFAULT_LOG
    if not path.is_absolute():
        path = manifest.root / path
    try:
        lines = path.read_text(encoding="utf-8").splitlines()
    except FileNotFoundError:
        return ()
    except (OSError, UnicodeError) as exc:
        raise TelemetryError(f"cannot read telemetry log: {path}") from exc
    events: list[TelemetryEvent] = []
    for line_number, line in enumerate(lines, start=1):
        if not line.strip():
            raise TelemetryValidationError(
                f"blank telemetry line at {path}:{line_number}"
            )
        try:
            payload = json.loads(line)
        except json.JSONDecodeError as exc:
            raise TelemetryValidationError(
                f"invalid telemetry JSON at {path}:{line_number}: {exc}"
            ) from exc
        if not isinstance(payload, dict) or set(payload) not in {
            _EVENT_FIELDS, _LEGACY_EVENT_FIELDS
        }:
            raise TelemetryValidationError(
                f"telemetry fields at {path}:{line_number} must be exactly "
                f"{sorted(_EVENT_FIELDS)} (run_id may be absent in legacy events)"
            )
        payload.setdefault("run_id", None)
        events.append(_event(manifest, **payload, from_log=True))
    return tuple(events)


def record_telemetry_event(
    manifest: ProductionManifest,
    *,
    stage: str,
    agent_role: str,
    wall_ms: int,
    human_wait_ms: int,
    input_tokens: int,
    cached_input_tokens: int,
    output_tokens: int,
    artifact_paths: Iterable[str | Path],
    run_id: str | None = None,
    timestamp: str | None = None,
    log_path: str | Path | None = None,
    summary_path: str | Path | None = None,
) -> TelemetryEvent:
    """Append a validated event and atomically refresh its aggregate summary."""
    if not isinstance(manifest, ProductionManifest):
        raise TypeError("manifest must be a ProductionManifest")
    artifacts = tuple(artifact_paths)
    event = _event(
        manifest,
        timestamp=timestamp or _utc_timestamp(),
        product_id=manifest.product.id,
        production_id=manifest.id,
        run_id=run_id,
        stage=stage,
        agent_role=agent_role,
        wall_ms=wall_ms,
        human_wait_ms=human_wait_ms,
        input_tokens=input_tokens,
        cached_input_tokens=cached_input_tokens,
        output_tokens=output_tokens,
        artifact_paths=artifacts,
        from_log=False,
    )
    log = Path(log_path) if log_path is not None else manifest.root / _DEFAULT_LOG
    summary = (
        Path(summary_path)
        if summary_path is not None
        else manifest.root / _DEFAULT_SUMMARY
    )
    if not log.is_absolute():
        log = manifest.root / log
    if not summary.is_absolute():
        summary = manifest.root / summary
    for label, path in (("log_path", log), ("summary_path", summary)):
        if not _inside(path.resolve(), manifest.review_dir.resolve()):
            raise TelemetryValidationError(f"{label} must stay inside data/review")

    with _WRITE_LOCK:
        existing = load_telemetry_events(manifest, log_path=log)
        log.parent.mkdir(parents=True, exist_ok=True)
        line = json.dumps(asdict(event), ensure_ascii=False, separators=(",", ":"))
        try:
            with log.open("a", encoding="utf-8", newline="\n") as stream:
                stream.write(line + "\n")
                stream.flush()
                os.fsync(stream.fileno())
        except OSError as exc:
            raise TelemetryError(f"cannot append telemetry log: {log}") from exc
        _atomic_write_json(summary, _summary_payload(summarize_telemetry((*existing, event))))
    return event


__all__ = [
    "TelemetryError",
    "TelemetryEvent",
    "TelemetrySummary",
    "TelemetryTotals",
    "TelemetryValidationError",
    "load_telemetry_events",
    "record_telemetry_event",
    "summarize_telemetry",
]
