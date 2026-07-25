"""Batch handoff contract between Studio and an external capture agent.

Studio owns requests and validation, not screen recording.  One normalized
manifest carries every missing capture to the external agent; a hash-bound
result manifest is then ingested into the production asset catalog.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator

from dlstudio.production import load_production_manifest
from dlstudio.services.asset_registry import _register_ingested_captures
from dlstudio.services.autopilot import build_asset_catalog
from dlstudio.services.render_preflight import analyze_rendered_video


class CaptureBatchError(ValueError):
    """Invalid request/result contract or captured artifact."""


class _Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class CaptureRequestSpec(_Model):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    source: Literal["gameplay", "canvas", "diary", "steam", "desktop"]
    target: str = Field(min_length=1)
    orientation: Literal["landscape", "vertical", "square"]
    min_width: int = Field(gt=0)
    min_height: int = Field(gt=0)
    min_duration: float = Field(default=0.0, ge=0.0)
    scene: str | None = None
    instructions: str = ""


class PreparedCaptureRequest(CaptureRequestSpec):
    target_absolute: str


class CaptureBatch(_Model):
    version: Literal[1] = 1
    product_id: str
    production_id: str
    game_root: str
    production_root: str
    requested_at: str
    requests: list[PreparedCaptureRequest]


class CaptureRequestSpecV2(_Model):
    id: str = Field(min_length=1, max_length=120, pattern=r"^[A-Za-z0-9_-]+$")
    source: Literal["gameplay", "canvas", "diary", "steam", "desktop"]
    target: str = Field(min_length=1)
    editorial_role: Literal["gameplay", "debug_proof", "presentation", "reference"]
    capture_method: Literal[
        "realtime_window",
        "deterministic_devapi",
        "screen_recording",
        "screenshot",
    ]
    state_id: str | None = None
    build_id: str | None = None
    orientation: Literal["landscape", "vertical", "square"]
    min_width: int = Field(gt=0)
    min_height: int = Field(gt=0)
    min_fps: float = Field(default=30.0, gt=0)
    simulation_rate: float = Field(default=1.0, gt=0)
    content_seconds: float = Field(default=0.0, ge=0.0)
    head_handle_seconds: float = Field(default=0.0, ge=0.0)
    tail_handle_seconds: float = Field(default=0.0, ge=0.0)
    continuous: bool = False
    clean_ui: bool = False
    action_id: str | None = None
    scene: str | None = None
    instructions: str = ""

    @model_validator(mode="after")
    def validate_gameplay_contract(self) -> "CaptureRequestSpecV2":
        if self.editorial_role != "gameplay":
            return self
        if self.source != "gameplay":
            raise ValueError("editorial_role=gameplay requires source=gameplay")
        if self.capture_method != "realtime_window":
            raise ValueError("gameplay requires capture_method=realtime_window")
        if not self.state_id:
            raise ValueError("gameplay requires state_id")
        if not self.build_id:
            raise ValueError("gameplay requires build_id")
        if not self.action_id:
            raise ValueError("gameplay requires action_id")
        if re.fullmatch(r"exe-sha256:[0-9a-fA-F]{64}", self.build_id) is None:
            raise ValueError("gameplay build_id requires exe-sha256:<64 hex>")
        if self.head_handle_seconds < 5:
            raise ValueError("gameplay requires head_handle_seconds >= 5")
        if self.tail_handle_seconds < 5:
            raise ValueError("gameplay requires tail_handle_seconds >= 5")
        if self.content_seconds <= 0:
            raise ValueError("gameplay requires content_seconds > 0")
        if self.simulation_rate != 1.0:
            raise ValueError("gameplay requires simulation_rate=1.0")
        if not self.continuous:
            raise ValueError("gameplay requires continuous=true")
        if not self.clean_ui:
            raise ValueError("gameplay requires clean_ui=true")
        return self


class PreparedCaptureRequestV2(CaptureRequestSpecV2):
    target_absolute: str


class CaptureBatchV2(_Model):
    version: Literal[2] = 2
    product_id: str
    production_id: str
    game_root: str
    production_root: str
    requested_at: str
    requests: list[PreparedCaptureRequestV2]


class CaptureResultSpec(_Model):
    request_id: str
    status: Literal["captured", "failed"]
    path: str
    sha256: str = Field(pattern=r"^[0-9a-fA-F]{64}$")
    captured_at: str = ""
    note: str = ""


class CaptureResults(_Model):
    version: Literal[1] = 1
    production_id: str
    results: list[CaptureResultSpec]


class CaptureResultSpecV2(_Model):
    request_id: str
    status: Literal["captured", "failed"]
    path: str | None = None
    sha256: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    capture_method: str | None = None
    state_id: str | None = None
    build_id: str | None = None
    recorder_metadata_path: str | None = None
    recorder_metadata_sha256: str | None = Field(
        default=None,
        pattern=r"^[0-9a-fA-F]{64}$",
    )
    captured_at: str = ""
    note: str = ""

    @model_validator(mode="after")
    def require_captured_evidence(self) -> "CaptureResultSpecV2":
        if self.status == "failed":
            return self
        required = {
            "path": self.path,
            "sha256": self.sha256,
            "capture_method": self.capture_method,
            "state_id": self.state_id,
            "build_id": self.build_id,
            "recorder_metadata_path": self.recorder_metadata_path,
            "recorder_metadata_sha256": self.recorder_metadata_sha256,
        }
        missing = [name for name, value in required.items() if not value]
        if missing:
            raise ValueError(
                "captured result requires " + ", ".join(sorted(missing))
            )
        return self


class CaptureResultsV2(_Model):
    version: Literal[2] = 2
    production_id: str
    results: list[CaptureResultSpecV2]


@dataclass(frozen=True)
class CaptureIngestReceipt:
    ingested: tuple[str, ...]
    failed: tuple[str, ...]
    catalog_path: Path
    receipt_path: Path
    registry_path: Path | None = None


def _read_json(path: Path) -> object:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise CaptureBatchError(f"capture manifest not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise CaptureBatchError(f"invalid capture JSON {path}: {exc}") from exc


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _target_path(production_root: Path, raw: str) -> Path:
    value = Path(raw)
    if value.is_absolute() or value.drive or ".." in value.parts:
        raise CaptureBatchError(
            f"capture target must stay inside production data: {raw}"
        )
    target = (production_root / value).resolve()
    data_root = (production_root / "data").resolve()
    try:
        target.relative_to(data_root)
    except ValueError as exc:
        raise CaptureBatchError(
            f"capture target must stay inside production data: {raw}"
        ) from exc
    return target


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_v2_recorder_metadata(
    production_root: Path,
    task: PreparedCaptureRequestV2,
    result: CaptureResultSpecV2,
    artifact: Path,
) -> dict:
    if result.capture_method != task.capture_method:
        raise CaptureBatchError(
            f"capture method mismatch: {result.request_id}"
        )
    if result.state_id != task.state_id:
        raise CaptureBatchError(f"result state_id mismatch: {result.request_id}")
    if result.build_id != task.build_id:
        raise CaptureBatchError(f"result build_id mismatch: {result.request_id}")

    metadata_path = _target_path(
        production_root,
        result.recorder_metadata_path or "",
    )
    if not metadata_path.is_file():
        raise CaptureBatchError(
            f"recorder metadata is missing: {result.request_id}"
        )
    if _sha256(metadata_path).casefold() != (
        result.recorder_metadata_sha256 or ""
    ).casefold():
        raise CaptureBatchError(
            f"recorder metadata hash mismatch: {result.request_id}"
        )
    metadata = _read_json(metadata_path)
    if not isinstance(metadata, dict):
        raise CaptureBatchError(
            f"recorder metadata must be an object: {result.request_id}"
        )
    expected = {
        "capture_method": task.capture_method,
        "editorial_role": task.editorial_role,
        "state_id": task.state_id,
        "build_id": task.build_id,
        "action_id": task.action_id,
        "simulation_rate": task.simulation_rate,
        "continuous": task.continuous,
        "clean_ui": task.clean_ui,
    }
    for field, value in expected.items():
        if metadata.get(field) != value:
            raise CaptureBatchError(
                f"recorder {field} mismatch: {result.request_id}"
            )
    if metadata.get("sha256", "").casefold() != (result.sha256 or "").casefold():
        raise CaptureBatchError(
            f"recorder artifact hash mismatch: {result.request_id}"
        )
    recorded_artifact = Path(str(metadata.get("artifact") or ""))
    if not recorded_artifact.is_absolute():
        recorded_artifact = production_root / recorded_artifact
    if recorded_artifact.resolve() != artifact.resolve():
        raise CaptureBatchError(
            f"recorder artifact path mismatch: {result.request_id}"
        )
    if task.editorial_role == "gameplay":
        if metadata.get("schema") != "devlog.realtime_window_capture":
            raise CaptureBatchError(
                f"invalid gameplay recorder schema: {result.request_id}"
            )
        if metadata.get("client_area") is not True:
            raise CaptureBatchError(
                f"gameplay was not proven client-area-only: {result.request_id}"
            )
        if metadata.get("cursor_visible") is not False:
            raise CaptureBatchError(
                f"gameplay cursor exclusion was not proven: {result.request_id}"
            )
        executable_sha = metadata.get("executable_sha256")
        if (
            not isinstance(executable_sha, str)
            or task.build_id.casefold()
            != f"exe-sha256:{executable_sha}".casefold()
        ):
            raise CaptureBatchError(
                f"recorder executable SHA mismatch: {result.request_id}"
            )
    return {
        "request_id": result.request_id,
        "artifact_path": task.target,
        "artifact_sha256": (result.sha256 or "").lower(),
        "metadata_path": metadata_path.relative_to(production_root).as_posix(),
        "metadata_sha256": (result.recorder_metadata_sha256 or "").lower(),
        "editorial_role": task.editorial_role,
        "capture_method": task.capture_method,
        "state_id": task.state_id,
        "build_id": task.build_id,
        "action_id": task.action_id,
        "client_rect": metadata.get("client_rect"),
        "simulation_rate": metadata.get("simulation_rate"),
        "continuous": metadata.get("continuous"),
        "clean_ui": metadata.get("clean_ui"),
        "client_area": metadata.get("client_area"),
        "cursor_visible": metadata.get("cursor_visible"),
        "head_handle_seconds": metadata.get("head_handle_seconds"),
        "tail_handle_seconds": metadata.get("tail_handle_seconds"),
        "content_seconds": metadata.get("content_seconds"),
    }


def prepare_capture_batch(
    production_root: str | Path,
    requests_path: str | Path,
    *,
    out_path: str | Path | None = None,
) -> CaptureBatch | CaptureBatchV2:
    """Normalize all requests into one external-agent handoff file."""

    production = load_production_manifest(production_root)
    path = Path(requests_path)
    try:
        payload = _read_json(path)
        if not isinstance(payload, dict) or payload.get("version") not in {1, 2}:
            raise CaptureBatchError("capture requests require version 1 or 2")
        raw_requests = payload.get("requests")
        if not isinstance(raw_requests, list) or not raw_requests:
            raise CaptureBatchError("capture requests must be a non-empty list")
        version = payload["version"]
        spec_type = CaptureRequestSpec if version == 1 else CaptureRequestSpecV2
        specs = [spec_type.model_validate(item) for item in raw_requests]
    except ValidationError as exc:
        raise CaptureBatchError(f"invalid capture request: {exc}") from exc
    ids = [item.id for item in specs]
    if len(ids) != len(set(ids)):
        raise CaptureBatchError("capture request ids must be unique")

    prepared_type = PreparedCaptureRequest if version == 1 else PreparedCaptureRequestV2
    batch_type = CaptureBatch if version == 1 else CaptureBatchV2
    tasks = [
        prepared_type(
            **spec.model_dump(),
            target_absolute=str(_target_path(production.root, spec.target)),
        )
        for spec in specs
    ]
    batch = batch_type(
        product_id=production.product.id,
        production_id=production.id,
        game_root=str(production.product.game_root),
        production_root=str(production.root),
        requested_at=datetime.now(timezone.utc).isoformat(),
        requests=tasks,
    )
    destination = (
        Path(out_path)
        if out_path is not None
        else production.data_dir / "plan" / "capture_batch.json"
    )
    _write_json(destination, batch.model_dump(mode="json"))
    return batch


def ingest_capture_results(
    production_root: str | Path,
    results_path: str | Path,
    *,
    batch_path: str | Path | None = None,
) -> CaptureIngestReceipt:
    """Verify external results and rebuild the authoritative asset catalog."""

    production = load_production_manifest(production_root)
    batch_file = (
        Path(batch_path)
        if batch_path is not None
        else production.data_dir / "plan" / "capture_batch.json"
    )
    try:
        batch_payload = _read_json(batch_file)
        results_payload = _read_json(Path(results_path))
        if not isinstance(batch_payload, dict) or not isinstance(results_payload, dict):
            raise CaptureBatchError("capture batch and results must be objects")
        version = batch_payload.get("version")
        if version != results_payload.get("version"):
            raise CaptureBatchError("capture batch and results versions differ")
        if version == 1:
            batch = CaptureBatch.model_validate(batch_payload)
            results = CaptureResults.model_validate(results_payload)
        elif version == 2:
            batch = CaptureBatchV2.model_validate(batch_payload)
            results = CaptureResultsV2.model_validate(results_payload)
        else:
            raise CaptureBatchError("capture ingest requires version 1 or 2")
    except ValidationError as exc:
        raise CaptureBatchError(f"invalid capture result: {exc}") from exc
    if results.production_id != production.id:
        raise CaptureBatchError("capture results belong to a different production")
    tasks = {item.id: item for item in batch.requests}
    seen: set[str] = set()
    ingested: list[str] = []
    failed: list[str] = []
    validated: dict[str, dict] = {}
    for result in results.results:
        if result.request_id in seen:
            raise CaptureBatchError(f"duplicate capture result: {result.request_id}")
        seen.add(result.request_id)
        task = tasks.get(result.request_id)
        if task is None:
            raise CaptureBatchError(f"unknown capture request: {result.request_id}")
        if result.status == "failed":
            failed.append(result.request_id)
            continue
        path = _target_path(production.root, result.path or "")
        if path != Path(task.target_absolute).resolve():
            raise CaptureBatchError(
                f"capture result path differs from requested target: {result.request_id}"
            )
        if not path.is_file():
            raise CaptureBatchError(f"captured file is missing: {path}")
        actual_hash = _sha256(path)
        if actual_hash.casefold() != (result.sha256 or "").casefold():
            raise CaptureBatchError(f"capture hash mismatch: {result.request_id}")
        if version == 2:
            if not isinstance(task, PreparedCaptureRequestV2):
                raise CaptureBatchError("version 2 task contract was not preserved")
            if not isinstance(result, CaptureResultSpecV2):
                raise CaptureBatchError("version 2 result contract was not preserved")
            validated[result.request_id] = _validate_v2_recorder_metadata(
                production.root,
                task,
                result,
                path,
            )
        ingested.append(result.request_id)

    if version == 2:
        missing = sorted(set(tasks) - seen)
        if missing:
            raise CaptureBatchError(
                "missing capture results: " + ", ".join(missing)
            )

    catalog_path = production.data_dir / "assets" / "catalog.json"
    catalog = build_asset_catalog(production.root)
    by_path = {item.path.replace("\\", "/"): item for item in catalog.assets}
    for request_id in ingested:
        task = tasks[request_id]
        asset = by_path.get(task.target.replace("\\", "/"))
        if asset is None:
            raise CaptureBatchError(
                f"captured file was not indexed by asset catalog: {task.target}"
            )
        if (asset.width or 0) < task.min_width or (asset.height or 0) < task.min_height:
            raise CaptureBatchError(
                f"capture resolution below request for {request_id}: "
                f"{asset.width}x{asset.height} < {task.min_width}x{task.min_height}"
            )
        min_duration = getattr(task, "min_duration", 0.0)
        if version == 2:
            min_duration = (
                task.head_handle_seconds
                + task.content_seconds
                + task.tail_handle_seconds
            )
            if (asset.fps or 0.0) < task.min_fps:
                raise CaptureBatchError(
                    f"capture FPS below request for {request_id}: "
                    f"{asset.fps or 0.0:.3f} < {task.min_fps:.3f}"
                )
            if asset.orientation != task.orientation:
                raise CaptureBatchError(
                    f"capture orientation differs for {request_id}: "
                    f"{asset.orientation} != {task.orientation}"
                )
            facts = validated[request_id]
            rect = facts.get("client_rect")
            if (
                not isinstance(rect, dict)
                or rect.get("width") != asset.width
                or rect.get("height") != asset.height
            ):
                raise CaptureBatchError(
                    f"encoded frame differs from recorder client_rect: {request_id}"
                )
            if (facts.get("head_handle_seconds") or 0.0) < task.head_handle_seconds:
                raise CaptureBatchError(
                    f"actual head handle below request: {request_id}"
                )
            if (facts.get("tail_handle_seconds") or 0.0) < task.tail_handle_seconds:
                raise CaptureBatchError(
                    f"actual tail handle below request: {request_id}"
                )
            facts.update({
                "actual_width": asset.width,
                "actual_height": asset.height,
                "actual_fps": asset.fps,
                "actual_duration": asset.duration,
                "actual_orientation": asset.orientation,
            })
            content_start = task.head_handle_seconds
            content_end = content_start + task.content_seconds
            frame_report = analyze_rendered_video(
                asset_path := (production.root / task.target).resolve(),
                cut_times=(),
                freeze_ranges=((
                    content_start,
                    content_end,
                    f"capture:{request_id}",
                ),),
                final=True,
            )
            if frame_report.issues:
                summary = "; ".join(
                    f"{issue.code}: {issue.message}"
                    for issue in frame_report.issues
                )
                raise CaptureBatchError(
                    f"capture frame audit failed for {request_id}: {summary}"
                )
            facts["frame_audit"] = {
                "artifact": str(asset_path),
                "content_window": [content_start, content_end],
                "verdict": "pass",
                "issues": [],
            }
            facts["frame_audit_passed"] = True
        if min_duration and (asset.duration or 0.0) < min_duration:
            raise CaptureBatchError(
                f"capture duration below request for {request_id}: "
                f"{asset.duration or 0.0:.2f}s < {min_duration:.2f}s"
            )

    registry_path: Path | None = None
    if version == 2 and ingested:
        try:
            batch_relative = batch_file.resolve().relative_to(production.root)
            results_relative = Path(results_path).resolve().relative_to(
                production.root
            )
        except ValueError as exc:
            raise CaptureBatchError(
                "v2 capture batch and results must stay inside the production"
            ) from exc
        batch_sha = _sha256(batch_file)
        results_sha = _sha256(Path(results_path))
        for facts in validated.values():
            facts.update({
                "capture_batch_path": batch_relative.as_posix(),
                "capture_batch_sha256": batch_sha,
                "capture_results_path": results_relative.as_posix(),
                "capture_results_sha256": results_sha,
            })
        _register_ingested_captures(
            production.root,
            [validated[request_id] for request_id in ingested],
        )
        registry_path = production.data_dir / "assets" / "registry.json"

    _write_json(catalog_path, catalog.model_dump(mode="json"))
    receipt_path = production.data_dir / "assets" / "capture_ingest.json"
    _write_json(
        receipt_path,
        {
            "version": version,
            "production_id": production.id,
            "ingested_at": datetime.now(timezone.utc).isoformat(),
            "batch": str(batch_file),
            "results": str(Path(results_path)),
            "ingested": ingested,
            "failed": failed,
            "validated": validated,
            "catalog": str(catalog_path),
            "registry": str(registry_path) if registry_path else None,
        },
    )
    return CaptureIngestReceipt(
        ingested=tuple(ingested),
        failed=tuple(failed),
        catalog_path=catalog_path,
        receipt_path=receipt_path,
        registry_path=registry_path,
    )


__all__ = [
    "CaptureBatch",
    "CaptureBatchV2",
    "CaptureBatchError",
    "CaptureIngestReceipt",
    "PreparedCaptureRequest",
    "PreparedCaptureRequestV2",
    "ingest_capture_results",
    "prepare_capture_batch",
]
