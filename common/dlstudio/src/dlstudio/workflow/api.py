"""A short, resumable workflow that exposes only meaningful checkpoints."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from typing import Any, Literal, Protocol

from dlstudio.foundation.api import (
    BlobRef,
    DomainId,
    canonical_bytes,
    canonical_hash,
)

StageId = Literal["prepare", "draft", "final", "review", "package", "deliver"]
WorkflowKind = Literal["reel", "longform", "capture_vo"]
STAGES: tuple[StageId, ...] = (
    "prepare",
    "draft",
    "final",
    "review",
    "package",
    "deliver",
)


@dataclass(frozen=True, slots=True)
class NamedRef:
    name: str
    blob: BlobRef

    def __post_init__(self) -> None:
        DomainId(self.name)

    def as_payload(self) -> dict[str, object]:
        return {"name": self.name, "blob": self.blob.as_payload()}


@dataclass(frozen=True, slots=True)
class StageAttempt:
    stage: StageId
    operation_id: str
    inputs: tuple[NamedRef, ...]
    outputs: tuple[NamedRef, ...] = ()
    state: Literal["running", "succeeded", "failed"] = "running"
    error: str | None = None

    def __post_init__(self) -> None:
        if self.stage not in STAGES:
            raise ValueError("unsupported workflow stage")
        if len(self.operation_id) != 64 or any(
            character not in "0123456789abcdef"
            for character in self.operation_id
        ):
            raise ValueError("invalid workflow operation id")
        inputs = tuple(sorted(self.inputs, key=lambda item: item.name))
        outputs = tuple(sorted(self.outputs, key=lambda item: item.name))
        if len({item.name for item in inputs}) != len(inputs):
            raise ValueError("duplicate stage input name")
        if len({item.name for item in outputs}) != len(outputs):
            raise ValueError("duplicate stage output name")
        if self.state == "running" and (outputs or self.error is not None):
            raise ValueError("running attempt cannot have outputs or error")
        if self.state == "succeeded" and self.error is not None:
            raise ValueError("succeeded attempt cannot have an error")
        if self.state == "failed" and not self.error:
            raise ValueError("failed attempt requires an error")
        object.__setattr__(self, "inputs", inputs)
        object.__setattr__(self, "outputs", outputs)

    def as_payload(self) -> dict[str, object]:
        return {
            "stage": self.stage,
            "operation_id": self.operation_id,
            "inputs": [item.as_payload() for item in self.inputs],
            "outputs": [item.as_payload() for item in self.outputs],
            "state": self.state,
            "error": self.error,
        }


@dataclass(frozen=True, slots=True)
class WorkflowRun:
    run_id: str
    production_id: str
    kind: WorkflowKind
    revision: int = 0
    attempts: tuple[StageAttempt, ...] = ()
    eligible_candidate: BlobRef | None = None
    delivery_receipt: BlobRef | None = None

    DOMAIN = "dlstudio.workflow_run"
    VERSION = 1

    def __post_init__(self) -> None:
        DomainId(self.run_id)
        DomainId(self.production_id)
        if self.kind not in {"reel", "longform", "capture_vo"}:
            raise ValueError("unsupported workflow kind")
        if self.revision < 0:
            raise ValueError("workflow revision cannot be negative")
        attempts = tuple(
            sorted(self.attempts, key=lambda item: STAGES.index(item.stage))
        )
        stages = [item.stage for item in attempts]
        if len(stages) != len(set(stages)):
            raise ValueError("workflow keeps one selected attempt per stage")
        object.__setattr__(self, "attempts", attempts)

    @property
    def current_stage(self) -> StageId | None:
        selected = {item.stage: item for item in self.attempts}
        for stage in STAGES:
            attempt = selected.get(stage)
            if attempt is None or attempt.state != "succeeded":
                return stage
        return None

    @property
    def completed(self) -> bool:
        return self.current_stage is None and self.delivery_receipt is not None

    def start(
        self,
        stage: StageId,
        inputs: tuple[NamedRef, ...],
        *,
        contract: str,
    ) -> "WorkflowRun":
        if stage not in STAGES:
            raise ValueError("unsupported workflow stage")
        if stage == "deliver":
            raise ValueError("delivery is completed only by the delivery use case")
        if not contract:
            raise ValueError("stage contract fingerprint is required")
        normalized_inputs = tuple(sorted(inputs, key=lambda item: item.name))
        operation_id = canonical_hash(
            {
                "run_id": self.run_id,
                "production_id": self.production_id,
                "stage": stage,
                "inputs": [item.as_payload() for item in normalized_inputs],
                "contract": contract,
            },
            domain="dlstudio.workflow_operation",
        )
        selected = {item.stage: item for item in self.attempts}
        existing = selected.get(stage)
        if (
            existing is not None
            and existing.operation_id == operation_id
            and existing.state in {"running", "succeeded"}
        ):
            return self
        current = self.current_stage
        if current is not None and STAGES.index(stage) > STAGES.index(current):
            raise ValueError(f"workflow must complete {current} before {stage}")
        kept = tuple(
            item
            for item in self.attempts
            if STAGES.index(item.stage) < STAGES.index(stage)
        )
        attempt = StageAttempt(stage, operation_id, normalized_inputs)
        return replace(
            self,
            revision=self.revision + 1,
            attempts=(*kept, attempt),
            eligible_candidate=None,
            delivery_receipt=None,
        )

    def succeed(
        self,
        operation_id: str,
        outputs: tuple[NamedRef, ...],
    ) -> "WorkflowRun":
        attempt = next(
            (
                item
                for item in self.attempts
                if item.operation_id == operation_id
            ),
            None,
        )
        if attempt is None:
            raise ValueError("unknown workflow operation")
        if attempt.state == "succeeded":
            if attempt.outputs != tuple(
                sorted(outputs, key=lambda item: item.name)
            ):
                raise ValueError("completed operation has different outputs")
            return self
        if attempt.state != "running":
            raise ValueError("only a running operation can succeed")
        if attempt.stage == "package" and {
            item.name for item in outputs
        } != {"candidate"}:
            raise ValueError("package must output exactly one candidate")
        completed = replace(
            attempt,
            outputs=outputs,
            state="succeeded",
        )
        return replace(
            self,
            revision=self.revision + 1,
            attempts=tuple(
                completed if item.operation_id == operation_id else item
                for item in self.attempts
            ),
            delivery_receipt=self.delivery_receipt,
        )

    def fail(self, operation_id: str, error: str) -> "WorkflowRun":
        if not error.strip():
            raise ValueError("workflow failure requires an error")
        attempt = next(
            (
                item
                for item in self.attempts
                if item.operation_id == operation_id
            ),
            None,
        )
        if attempt is None or attempt.state != "running":
            raise ValueError("only a running operation can fail")
        failed = replace(attempt, state="failed", error=error)
        return replace(
            self,
            revision=self.revision + 1,
            attempts=tuple(
                failed if item.operation_id == operation_id else item
                for item in self.attempts
            ),
        )

    def allow_delivery(self) -> "WorkflowRun":
        package = next(
            (item for item in self.attempts if item.stage == "package"),
            None,
        )
        if package is None or package.state != "succeeded":
            raise ValueError("package must succeed before delivery is allowed")
        if self.current_stage != "deliver":
            raise ValueError("workflow is not ready for delivery")
        candidate = next(
            item.blob for item in package.outputs if item.name == "candidate"
        )
        if self.eligible_candidate == candidate:
            return self
        return replace(
            self,
            revision=self.revision + 1,
            eligible_candidate=candidate,
            delivery_receipt=None,
        )

    def delivered(
        self, candidate: BlobRef, receipt: BlobRef
    ) -> "WorkflowRun":
        """Record the journal-protected delivery as one workflow transition."""

        if self.eligible_candidate != candidate:
            raise ValueError("delivered candidate is not eligible")
        if self.completed:
            if self.delivery_receipt != receipt:
                raise ValueError("delivery already has another receipt")
            return self
        if self.current_stage != "deliver":
            raise ValueError("workflow is not ready to deliver")
        operation_id = canonical_hash(
            {
                "run_id": self.run_id,
                "candidate": candidate.as_payload(),
            },
            domain="dlstudio.workflow_delivery",
        )
        attempt = StageAttempt(
            "deliver",
            operation_id,
            (NamedRef("candidate", candidate),),
            (NamedRef("receipt", receipt),),
            "succeeded",
        )
        kept = tuple(item for item in self.attempts if item.stage != "deliver")
        return replace(
            self,
            revision=self.revision + 1,
            attempts=(*kept, attempt),
            delivery_receipt=receipt,
        )

    def as_payload(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "production_id": self.production_id,
            "kind": self.kind,
            "revision": self.revision,
            "attempts": [item.as_payload() for item in self.attempts],
            "eligible_candidate": (
                None
                if self.eligible_candidate is None
                else self.eligible_candidate.as_payload()
            ),
            "delivery_receipt": (
                None
                if self.delivery_receipt is None
                else self.delivery_receipt.as_payload()
            ),
        }

    @property
    def run_hash(self) -> str:
        return canonical_hash(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    def canonical_bytes(self) -> bytes:
        return canonical_bytes(
            self.as_payload(), domain=self.DOMAIN, version=self.VERSION
        )

    @classmethod
    def from_canonical_bytes(cls, raw: bytes) -> "WorkflowRun":
        wrapped = json.loads(raw)
        if (
            wrapped.get("$domain") != cls.DOMAIN
            or wrapped.get("$version") != cls.VERSION
        ):
            raise ValueError("invalid workflow schema")
        value = wrapped["payload"]

        def named(item: dict[str, Any]) -> NamedRef:
            return NamedRef(
                str(item["name"]), BlobRef.from_payload(item["blob"])
            )

        result = cls(
            run_id=str(value["run_id"]),
            production_id=str(value["production_id"]),
            kind=value["kind"],
            revision=int(value["revision"]),
            attempts=tuple(
                StageAttempt(
                    stage=item["stage"],
                    operation_id=str(item["operation_id"]),
                    inputs=tuple(named(ref) for ref in item["inputs"]),
                    outputs=tuple(named(ref) for ref in item["outputs"]),
                    state=item["state"],
                    error=item["error"],
                )
                for item in value["attempts"]
            ),
            eligible_candidate=(
                None
                if value["eligible_candidate"] is None
                else BlobRef.from_payload(value["eligible_candidate"])
            ),
            delivery_receipt=(
                None
                if value["delivery_receipt"] is None
                else BlobRef.from_payload(value["delivery_receipt"])
            ),
        )
        if result.canonical_bytes() != raw:
            raise ValueError("workflow run is not canonical")
        return result


class WorkflowStore(Protocol):
    """Storage operations required by application workflow use cases."""

    @property
    def production_id(self) -> str: ...

    def read_current(self) -> WorkflowRun | None: ...

    def head_revision(self) -> int: ...

    def save(
        self,
        workflow: WorkflowRun,
        *,
        expected_workflow_revision: int,
        expected_head_revision: int,
    ) -> object: ...

    def put_blob(self, data: bytes) -> BlobRef: ...

    def verify_blob(self, ref: BlobRef) -> None: ...
