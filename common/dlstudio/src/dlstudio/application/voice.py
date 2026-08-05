"""Voice-recorder use cases shared by Studio v3 adapters."""

from __future__ import annotations

import hashlib
from collections.abc import Callable
from dataclasses import dataclass
from pathlib import Path
from typing import Literal, Protocol

from dlstudio.assets.api import (
    Approval,
    AssetIngestPort,
    AssetReadPort,
    AssetRevision,
    License,
    MediaFacts,
)
from dlstudio.authoring.api import load_edit
from dlstudio.foundation.api import BlobRef, CorruptObject, DomainId, canonical_bytes
from dlstudio.speech.api import SpeechTakeReceipt, VoiceRecorderReceipt
from dlstudio.timeline.api import TimelineIR
from dlstudio.workflow.api import WorkflowStore

from .assets import IngestAssetCommand, ingest_asset
from .release import BlobStore


@dataclass(frozen=True, slots=True)
class VoiceTakeSummary:
    asset_id: str
    take_id: str
    blob: BlobRef
    recorded_at: str
    duration_ns: int
    mime_type: str
    format_name: str
    codec: str | None
    current_script: bool
    approval_status: Literal["pending", "validated", "approved", "rejected"]
    approval_reason: str | None
    referenced_by_timeline: bool


@dataclass(frozen=True, slots=True)
class VoiceRecorderContext:
    production_id: str
    script_text: str
    script_ref: BlobRef
    state_revision: int
    takes: tuple[VoiceTakeSummary, ...]


def _script_evidence(script_text: str) -> tuple[bytes, BlobRef]:
    raw = canonical_bytes({"text": script_text}, domain="dlstudio.voice_script")
    return raw, BlobRef(hashlib.sha256(raw).hexdigest(), len(raw))


def _voice_script(authoring_path: Path, production_id: str) -> str:
    edit = load_edit(authoring_path)
    if edit.production_id != production_id:
        raise ValueError("authoring production identity mismatch")
    if edit.voice_script is None:
        raise ValueError("production has no voice script")
    return edit.voice_script


def _summary(
    revision: AssetRevision,
    store: BlobStore,
    *,
    current_script_ref: BlobRef,
    referenced_asset_ids: frozenset[str],
) -> VoiceTakeSummary:
    provenance = revision.provenance
    if (
        provenance.capture_method != "voice_take"
        or provenance.state_id is None
        or provenance.script_ref is None
        or provenance.provider_receipt_ref is None
    ):
        raise ValueError("asset is not a voice take")
    try:
        receipt = VoiceRecorderReceipt.from_canonical_bytes(
            store.read(provenance.provider_receipt_ref)
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CorruptObject("invalid canonical voice recorder receipt") from exc
    if revision.media.duration_ns is None:
        raise CorruptObject("voice take has no audio duration")
    return VoiceTakeSummary(
        asset_id=revision.asset_id,
        take_id=provenance.state_id,
        blob=revision.blob,
        recorded_at=receipt.recorded_at,
        duration_ns=revision.media.duration_ns,
        mime_type=receipt.mime_type,
        format_name=revision.media.format_name,
        codec=revision.media.codec,
        current_script=provenance.script_ref == current_script_ref,
        approval_status=revision.approval.status,
        approval_reason=revision.approval.reason,
        referenced_by_timeline=revision.asset_id in referenced_asset_ids,
    )


def query_voice_recorder(
    assets: AssetReadPort,
    store: BlobStore,
    *,
    production_id: str,
    authoring_path: Path,
    state_revision: int,
    workflows: WorkflowStore | None = None,
) -> VoiceRecorderContext:
    script_text = _voice_script(authoring_path, production_id)
    _, script_ref = _script_evidence(script_text)
    referenced_asset_ids: frozenset[str] = frozenset()
    if workflows is not None:
        workflow = workflows.read_current()
        latest_prepare = None if workflow is None else next(
            (
                attempt
                for attempt in reversed(workflow.attempts)
                if attempt.stage == "prepare"
            ),
            None,
        )
        if latest_prepare is not None and latest_prepare.state == "succeeded":
            timeline_ref = next(
                (
                    item.blob
                    for item in latest_prepare.outputs
                    if item.name == "timeline"
                ),
                None,
            )
            if timeline_ref is None:
                raise CorruptObject("prepared workflow has no TimelineIR")
            try:
                timeline = TimelineIR.from_canonical_bytes(store.read(timeline_ref))
            except (KeyError, TypeError, ValueError) as exc:
                raise CorruptObject("invalid prepared TimelineIR") from exc
            if timeline.ref != timeline_ref or timeline.production_id != production_id:
                raise CorruptObject("prepared TimelineIR identity mismatch")
            referenced_asset_ids = frozenset(
                clip.asset.asset_id
                for clip in timeline.audio
                if clip.role == "voice"
            )
    takes = tuple(
        _summary(
            revision,
            store,
            current_script_ref=script_ref,
            referenced_asset_ids=referenced_asset_ids,
        )
        for revision in assets.list_current()
        if revision.provenance.capture_method == "voice_take"
    )
    return VoiceRecorderContext(
        production_id=production_id,
        script_text=script_text,
        script_ref=script_ref,
        state_revision=state_revision,
        takes=tuple(
            sorted(
                takes,
                key=lambda take: (take.recorded_at, take.take_id),
                reverse=True,
            )
        ),
    )


def record_voice_take(
    assets: AssetIngestPort,
    store: BlobStore,
    *,
    production_id: str,
    authoring_path: Path,
    source: Path,
    take_id: str,
    recorded_at: str,
    duration_ms: int,
    mime_type: str,
    expected_production_id: str,
    expected_script_ref: BlobRef,
    expected_revision: int,
    inspect_media: Callable[[Path], MediaFacts],
) -> int:
    DomainId(take_id)
    script_text = _voice_script(authoring_path, production_id)
    script_bytes, current_script_ref = _script_evidence(script_text)
    if production_id != expected_production_id:
        raise ValueError("voice draft belongs to another production")
    if expected_script_ref != current_script_ref:
        raise ValueError("voice draft belongs to another script")
    script_ref = store.put_bytes(script_bytes)
    if script_ref != current_script_ref:
        raise CorruptObject("voice script evidence identity mismatch")
    recorder_receipt = VoiceRecorderReceipt(
        recorded_at=recorded_at,
        duration_ms=duration_ms,
        mime_type=mime_type,
    )
    recorder_receipt_ref = store.put_bytes(recorder_receipt.canonical_bytes())
    speech_receipt = SpeechTakeReceipt(
        script_text=script_text,
        script_ref=script_ref,
        take_id=take_id,
        recorder_receipt_ref=recorder_receipt_ref,
    )

    def inspect_voice(path: Path) -> MediaFacts:
        media = inspect_media(path)
        if media.kind != "audio":
            raise ValueError("voice take must contain audio")
        return media

    result = ingest_asset(
        assets,
        IngestAssetCommand(
            source=source,
            asset_id=f"voice.take.{take_id}",
            provenance=speech_receipt.provenance(),
            approval=Approval("pending"),
            license=License("owned", False),
            expected_revision=expected_revision,
        ),
        inspect_media=inspect_voice,
    )
    return result.state_revision


class VoiceAssetPort(AssetReadPort, AssetIngestPort, Protocol):
    """Asset operations required for an explicit voice-take approval."""


def approve_voice_take(
    assets: VoiceAssetPort,
    store: BlobStore,
    *,
    production_id: str,
    authoring_path: Path,
    asset_id: str,
    approved_at: str,
    expected_production_id: str,
    expected_script_ref: BlobRef,
    expected_revision: int,
    inspect_media: Callable[[Path], MediaFacts],
) -> int:
    """Create an approved immutable revision without editing authoring."""

    DomainId(asset_id)
    if not approved_at.strip():
        raise ValueError("approved_at is required")
    script_text = _voice_script(authoring_path, production_id)
    _, current_script_ref = _script_evidence(script_text)
    if expected_production_id != production_id:
        raise ValueError("voice approval belongs to another production")
    if expected_script_ref != current_script_ref:
        raise ValueError("voice approval belongs to another script")
    revision = assets.current(asset_id)
    if (
        revision.provenance.capture_method != "voice_take"
        or revision.provenance.script_ref != current_script_ref
    ):
        raise ValueError("voice take does not match the current script")
    if revision.approval.status not in {"pending", "validated"}:
        raise ValueError(
            f"voice take cannot be approved from {revision.approval.status}"
        )
    evidence = canonical_bytes(
        {
            "asset_revision": revision.ref.object.as_payload(),
            "approved_at": approved_at,
        },
        domain="dlstudio.voice_take_approval",
    )
    evidence_ref = store.put_bytes(evidence)
    result = assets.ingest(
        store.path_for(revision.blob),
        asset_id=revision.asset_id,
        media=revision.media,
        provenance=revision.provenance,
        approval=Approval("approved", (evidence_ref,)),
        license=revision.license,
        expected_revision=expected_revision,
        inspect_media=inspect_media,
    )
    return result.state_revision
