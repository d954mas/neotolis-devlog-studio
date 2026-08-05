"""The single local delivery use case."""

from __future__ import annotations

import hashlib
import json
import os
import shutil
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Protocol

from dlstudio.foundation.api import BlobRef, CasConflict, CorruptObject, DomainId
from dlstudio.release.api import DeliveryReceipt, PackageFile, ReleaseCandidate
from dlstudio.workflow.api import WorkflowRun


class LocalDeliveryState(Protocol):
    production_id: str

    def snapshot(self) -> tuple[WorkflowRun, int]: ...
    def read_blob(self, ref: BlobRef) -> bytes: ...
    def put_blob(self, data: bytes) -> BlobRef: ...
    def verify_blob(self, ref: BlobRef) -> None: ...
    def blob_path(self, ref: BlobRef) -> Path: ...
    def read_pending(self) -> bytes | None: ...
    def begin_pending(self, journal: bytes, *, expected_head: int) -> None: ...
    def save_completed(
        self, workflow: WorkflowRun, *, expected_workflow: int, expected_head: int
    ) -> None: ...
    def clear_pending(self, journal: bytes) -> None: ...


@dataclass(frozen=True, slots=True)
class DeliveryContext:
    candidate: BlobRef
    candidate_id: str
    files: tuple[PackageFile, ...]


def _candidate(state: LocalDeliveryState, ref: BlobRef) -> ReleaseCandidate:
    try:
        value = ReleaseCandidate.from_canonical_bytes(state.read_blob(ref))
    except (KeyError, TypeError, ValueError) as exc:
        raise CorruptObject("invalid release candidate") from exc
    if value.ref != ref or value.production_id != state.production_id:
        raise CorruptObject("release candidate does not match this production")
    for reachable in value.reachable_blobs:
        state.verify_blob(reachable)
    return value


def query_delivery_context(state: LocalDeliveryState) -> DeliveryContext:
    """Project the exact eligible package without performing delivery."""

    workflow, _ = state.snapshot()
    if workflow.eligible_candidate is None:
        raise ValueError("workflow has no eligible release candidate")
    if not workflow.completed and workflow.current_stage != "deliver":
        raise ValueError("workflow is not ready to deliver")
    candidate = _candidate(state, workflow.eligible_candidate)
    return DeliveryContext(
        candidate=workflow.eligible_candidate,
        candidate_id=candidate.candidate_id,
        files=candidate.package,
    )


def _file_ref(path: Path) -> BlobRef:
    digest = hashlib.sha256()
    size = 0
    with path.open("rb") as handle:
        while chunk := handle.read(1024 * 1024):
            digest.update(chunk)
            size += len(chunk)
    return BlobRef(digest.hexdigest(), size)


def _matches(destination: Path, package: tuple[PackageFile, ...]) -> bool:
    if not destination.is_dir() or destination.is_symlink():
        return False
    actual = {
        path.relative_to(destination).as_posix(): _file_ref(path)
        for path in destination.rglob("*")
        if path.is_file() and not path.is_symlink()
    }
    if any(path.is_symlink() for path in destination.rglob("*")):
        return False
    return actual == {item.path: item.blob for item in package}


def _stage(
    state: LocalDeliveryState,
    candidate: ReleaseCandidate,
    destination: Path,
) -> Path:
    stage = destination.parent / (
        f".{destination.name}.dlstudio-{candidate.candidate_id[:12]}"
    )
    if stage.exists():
        shutil.rmtree(stage)
    stage.mkdir()
    try:
        for item in candidate.package:
            target = stage / item.path
            target.parent.mkdir(parents=True, exist_ok=True)
            shutil.copyfile(state.blob_path(item.blob), target)
            if _file_ref(target) != item.blob:
                raise CorruptObject(f"staged delivery changed: {item.path}")
    except BaseException:
        shutil.rmtree(stage, ignore_errors=True)
        raise
    return stage


def _promote(
    destination: Path,
    stage: Path,
    package: tuple[PackageFile, ...],
) -> None:
    if _matches(destination, package):
        shutil.rmtree(stage, ignore_errors=True)
        return
    if destination.exists():
        raise FileExistsError(f"delivery destination differs: {destination}")
    os.replace(stage, destination)
    if not _matches(destination, package):
        raise CorruptObject("promoted delivery differs from its manifest")


def _journal(
    candidate: BlobRef,
    workflow: BlobRef,
    head: int,
    destination_id: str,
    destination: Path,
    delivered_at: str,
) -> bytes:
    return json.dumps(
        {
            "schema": "dlstudio.pending_delivery",
            "version": 1,
            "candidate": candidate.as_payload(),
            "workflow": workflow.as_payload(),
            "head": head,
            "destination_id": destination_id,
            "destination": str(destination),
            "delivered_at": delivered_at,
        },
        sort_keys=True,
        separators=(",", ":"),
    ).encode()


def _read_journal(raw: bytes) -> dict[str, object]:
    try:
        value = json.loads(raw)
        if (
            value["schema"] != "dlstudio.pending_delivery"
            or value["version"] != 1
            or json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
            != raw
        ):
            raise ValueError("schema")
        DomainId(str(value["destination_id"]))
        Path(str(value["destination"])).resolve(strict=False)
        BlobRef.from_payload(value["candidate"])
        BlobRef.from_payload(value["workflow"])
        if int(value["head"]) < 1:
            raise ValueError("head")
        return value
    except (KeyError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CorruptObject("invalid pending delivery journal") from exc


def _finished(
    state: LocalDeliveryState,
    workflow: WorkflowRun,
    candidate: ReleaseCandidate,
    destination: Path,
    destination_id: str,
) -> DeliveryReceipt:
    if workflow.delivery_receipt is None:
        raise CorruptObject("completed delivery has no receipt")
    receipt = DeliveryReceipt.from_canonical_bytes(
        state.read_blob(workflow.delivery_receipt)
    )
    if (
        receipt.ref != workflow.delivery_receipt
        or receipt.candidate_id != candidate.candidate_id
        or receipt.destination_id != destination_id
        or receipt.manifest != candidate.package
        or not _matches(destination, candidate.package)
    ):
        raise CorruptObject("delivery does not match its receipt")
    return receipt


def _finish(
    state: LocalDeliveryState, raw: bytes
) -> tuple[WorkflowRun, DeliveryReceipt]:
    pending = _read_journal(raw)
    candidate_ref = BlobRef.from_payload(pending["candidate"])
    candidate = _candidate(state, candidate_ref)
    destination = Path(str(pending["destination"]))
    destination_id = str(pending["destination_id"])
    current, current_head = state.snapshot()
    if current.completed:
        receipt = _finished(
            state, current, candidate, destination, destination_id
        )
        state.clear_pending(raw)
        return current, receipt

    stored = WorkflowRun.from_canonical_bytes(
        state.read_blob(BlobRef.from_payload(pending["workflow"]))
    )
    expected_head = int(pending["head"])
    if current != stored or current_head != expected_head:
        raise CasConflict("workflow changed during delivery")
    if not _matches(destination, candidate.package):
        _promote(
            destination,
            _stage(state, candidate, destination),
            candidate.package,
        )
    receipt = DeliveryReceipt(
        candidate.candidate_id,
        destination_id,
        str(pending["delivered_at"]),
        candidate.package,
    )
    receipt_ref = state.put_blob(receipt.canonical_bytes())
    completed = current.delivered(candidate_ref, receipt_ref)
    state.save_completed(
        completed,
        expected_workflow=current.revision,
        expected_head=expected_head,
    )
    state.clear_pending(raw)
    return completed, receipt


def deliver_local(
    state: LocalDeliveryState,
    destination: Path,
    *,
    destination_id: str,
    expected_candidate: BlobRef,
    delivered_at: str | None = None,
) -> tuple[WorkflowRun, DeliveryReceipt]:
    """Deliver only the candidate selected by the current workflow."""

    DomainId(destination_id)
    destination = destination.resolve()
    if destination == Path(destination.anchor):
        raise ValueError("delivery destination cannot be a filesystem root")
    pending = state.read_pending()
    if pending is not None:
        value = _read_journal(pending)
        if (
            Path(str(value["destination"])) != destination
            or value["destination_id"] != destination_id
            or BlobRef.from_payload(value["candidate"]) != expected_candidate
        ):
            raise CasConflict("another delivery is pending")
        return _finish(state, pending)

    workflow, head = state.snapshot()
    if workflow.eligible_candidate is None:
        raise ValueError("workflow has no eligible release candidate")
    if workflow.eligible_candidate != expected_candidate:
        raise CasConflict("eligible release candidate changed before delivery")
    candidate = _candidate(state, workflow.eligible_candidate)
    if workflow.completed:
        return workflow, _finished(
            state, workflow, candidate, destination, destination_id
        )
    if workflow.current_stage != "deliver":
        raise ValueError("workflow is not ready to deliver")
    if destination.exists() and not _matches(destination, candidate.package):
        raise FileExistsError(f"delivery destination differs: {destination}")
    destination.parent.mkdir(parents=True, exist_ok=True)
    stage = _stage(state, candidate, destination)
    workflow_ref = state.put_blob(workflow.canonical_bytes())
    raw = _journal(
        workflow.eligible_candidate,
        workflow_ref,
        head,
        destination_id,
        destination,
        delivered_at
        or datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
    )
    state.begin_pending(raw, expected_head=head)
    _promote(destination, stage, candidate.package)
    return _finish(state, raw)


def recover_local_delivery(
    state: LocalDeliveryState,
) -> tuple[WorkflowRun, DeliveryReceipt]:
    raw = state.read_pending()
    if raw is None:
        raise ValueError("no delivery is pending")
    return _finish(state, raw)
