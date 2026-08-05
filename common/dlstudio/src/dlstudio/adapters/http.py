"""Thin FastAPI adapter bound to one explicit Studio v3 production."""

from __future__ import annotations

import os
import tempfile
import uuid
from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Literal
from urllib.parse import urlsplit

from fastapi import (
    FastAPI,
    Header,
    HTTPException,
    Path as PathParam,
    Query,
    Request,
    Response,
)
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict, Field

from dlstudio.application.api import (
    advance_production,
    BlobRef,
    CasConflict,
    CorruptObject,
    DeliveryReceipt,
    DeliveryContext,
    deliver_local,
    query_delivery_context,
    project_status,
    query_authorized_review_artifact_contexts,
    query_current_review,
    query_review_frame_evidence,
    query_review_context,
    query_review_task_pack,
    query_review_waveform,
    ReviewArtifactContext,
    query_status,
    query_voice_recorder,
    record_voice_take,
    ReviewContext,
    ReviewTaskPack,
    ReviewWaveform,
    ReviewVerdict,
    resolve_blob,
    submit_review_payload,
    StudioError,
    WorkflowStatus,
    VoiceRecorderContext,
    approve_voice_take,
)

from .local import LocalProduction, load_local_production

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "testserver"})


class _FlightLock:
    def __init__(self) -> None:
        self.lock = Lock()
        self.users = 0
        self.failure: tuple[type[Exception], tuple[object, ...]] | None = None


def _join_flight(
    pool: dict[object, _FlightLock],
    key: object,
    guard: Lock,
) -> _FlightLock:
    with guard:
        flight = pool.get(key)
        if flight is None:
            flight = _FlightLock()
            pool[key] = flight
        flight.users += 1
        return flight


def _acquire_flight(
    pool: dict[object, _FlightLock],
    key: object,
    guard: Lock,
) -> _FlightLock:
    flight = _join_flight(pool, key, guard)
    flight.lock.acquire()
    return flight


def _release_flight(
    pool: dict[object, _FlightLock],
    key: object,
    flight: _FlightLock,
    guard: Lock,
) -> None:
    flight.lock.release()
    with guard:
        flight.users -= 1
        if flight.users == 0 and pool.get(key) is flight:
            del pool[key]


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewRegionBody(_Body):
    x_milli: int
    y_milli: int
    width_milli: int
    height_milli: int


class ReviewLocatorBody(_Body):
    start_frame: int
    end_frame_exclusive: int
    region: ReviewRegionBody | None = None
    target_ids: list[str] = Field(default_factory=list)


class ReviewFindingBody(_Body):
    finding_id: str
    text: str
    requires_change: bool = False
    locator: ReviewLocatorBody | None = None


class ReviewResolutionBody(_Body):
    previous_finding_id: str
    status: Literal["fixed", "obsolete", "still_wrong"]
    current_finding_id: str | None = None


class ReviewVerdictBody(_Body):
    expected_artifact: BlobRef
    expected_timeline: BlobRef
    expected_artifact_report: BlobRef
    expected_publication_manifest: BlobRef
    expected_check_report: BlobRef
    expected_constraints: BlobRef
    outcome: Literal["pass", "changes_requested", "block"]
    scope: list[str]
    reviewer: str
    reviewed_at: str
    findings: list[ReviewFindingBody]
    expected_latest_round: BlobRef | None = None
    resolutions: list[ReviewResolutionBody] = Field(default_factory=list)


class DeliveryBody(_Body):
    destination_id: str
    expected_candidate: BlobRef


class DeliveryResponse(_Body):
    status: WorkflowStatus
    receipt: DeliveryReceipt


class ApproveVoiceTakeBody(_Body):
    expected_revision: int = Field(ge=0)
    approved_at: str = Field(min_length=1)
    expected_production_id: str = Field(min_length=1)
    expected_script_ref: BlobRef


def _advance(production: LocalProduction):
    return advance_production(
        production.workflows,
        production.assets,
        production.repository.objects,
        authoring_path=production.authoring_path,
        output_root=production.production_root / "data" / ".studio" / "outputs",
        cache_root=production.production_root / "data" / ".studio" / "cache",
    )


def create_app(manifest_path: str | Path) -> FastAPI:
    """Create an API that can access only the explicitly named production."""

    production = load_local_production(manifest_path)
    app = FastAPI(title="DLStudio v3", version="3.0.0")
    authorized_review_artifacts: OrderedDict[
        tuple[int, BlobRef | None],
        dict[BlobRef, ReviewArtifactContext],
    ] = OrderedDict()
    verified_review_artifacts: OrderedDict[
        tuple[str, int],
        Path,
    ] = OrderedDict()
    authorization_flights: dict[object, _FlightLock] = {}
    verification_flights: dict[object, _FlightLock] = {}
    review_cache_lock = Lock()
    presentation_cache_root = (
        production.production_root
        / "data"
        / ".studio"
        / "cache"
        / "presentation"
    )
    app.add_middleware(
        TrustedHostMiddleware,
        allowed_hosts=sorted(_LOCAL_HOSTS),
    )

    @app.middleware("http")
    async def same_origin_control_plane(
        request: Request, call_next
    ) -> Response:
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            if request.headers.get("sec-fetch-site", "").lower() == "cross-site":
                return JSONResponse(
                    status_code=403, content={"detail": "cross-origin request blocked"}
                )
            origin = request.headers.get("origin")
            if origin:
                parsed = urlsplit(origin)
                request_host = request.headers.get("host", "").lower()
                if (
                    parsed.scheme != "http"
                    or parsed.hostname not in _LOCAL_HOSTS
                    or parsed.netloc.lower() != request_host
                ):
                    return JSONResponse(
                        status_code=403,
                        content={"detail": "cross-origin request blocked"},
                    )
        return await call_next(request)

    @app.exception_handler(ValueError)
    async def value_error(_request: object, exc: ValueError) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CasConflict)
    async def cas_conflict(_request: object, exc: CasConflict) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(exc)})

    @app.exception_handler(CorruptObject)
    async def corrupt_object(
        _request: object, exc: CorruptObject
    ) -> JSONResponse:
        return JSONResponse(status_code=500, content={"detail": str(exc)})

    @app.exception_handler(StudioError)
    async def studio_error(_request: object, exc: StudioError) -> JSONResponse:
        return JSONResponse(status_code=422, content={"detail": str(exc)})

    def raise_flight_failure(flight: _FlightLock) -> None:
        if flight.failure is None:
            return
        exception_type, args = flight.failure
        raise exception_type(*args)

    def stable_authorization_key() -> tuple[int, BlobRef | None]:
        for _attempt in range(4):
            before = production.workflows.head_revision()
            latest = production.workflows.read_latest_review_round_ref()
            after = production.workflows.head_revision()
            if before == after:
                return after, latest
        raise ValueError("review state changed while authorizing artifact")

    def load_authorized_contexts() -> dict[BlobRef, ReviewArtifactContext]:
        for _attempt in range(4):
            authorization_key = stable_authorization_key()
            with review_cache_lock:
                authorized = authorized_review_artifacts.get(
                    authorization_key
                )
                if authorized is not None:
                    authorized_review_artifacts.move_to_end(authorization_key)
            if authorized is not None:
                if stable_authorization_key() == authorization_key:
                    return authorized
                continue

            flight = _acquire_flight(
                authorization_flights,
                authorization_key,
                review_cache_lock,
            )
            try:
                if stable_authorization_key() != authorization_key:
                    continue
                with review_cache_lock:
                    authorized = authorized_review_artifacts.get(
                        authorization_key
                    )
                    if authorized is not None:
                        authorized_review_artifacts.move_to_end(
                            authorization_key
                        )
                if authorized is None:
                    if flight.failure is not None:
                        if stable_authorization_key() != authorization_key:
                            continue
                        raise_flight_failure(flight)
                    try:
                        computed = {
                            context.artifact: context
                            for context in (
                                query_authorized_review_artifact_contexts(
                                    production.workflows,
                                    production.repository.objects,
                                )
                            )
                        }
                    except Exception as exc:
                        if stable_authorization_key() != authorization_key:
                            continue
                        flight.failure = (type(exc), exc.args)
                        raise
                    if stable_authorization_key() != authorization_key:
                        continue
                    with review_cache_lock:
                        authorized = authorized_review_artifacts.get(
                            authorization_key
                        )
                        if authorized is None:
                            authorized = computed
                            authorized_review_artifacts[
                                authorization_key
                            ] = authorized
                            while len(authorized_review_artifacts) > 8:
                                authorized_review_artifacts.popitem(
                                    last=False
                                )
                        else:
                            authorized_review_artifacts.move_to_end(
                                authorization_key
                            )
                elif stable_authorization_key() != authorization_key:
                    continue
                return authorized
            finally:
                _release_flight(
                    authorization_flights,
                    authorization_key,
                    flight,
                    review_cache_lock,
                )
        raise ValueError("review state changed while authorizing artifact")

    def verified_artifact_path(requested: BlobRef) -> Path:
        artifact_key = (requested.sha256, requested.size)
        with review_cache_lock:
            source = verified_review_artifacts.get(artifact_key)
            if source is not None:
                verified_review_artifacts.move_to_end(artifact_key)
        if source is not None:
            return source

        flight = _acquire_flight(
            verification_flights,
            artifact_key,
            review_cache_lock,
        )
        try:
            with review_cache_lock:
                source = verified_review_artifacts.get(artifact_key)
                if source is not None:
                    verified_review_artifacts.move_to_end(artifact_key)
            if source is None:
                raise_flight_failure(flight)
                try:
                    source = resolve_blob(
                        production.repository.objects,
                        requested.sha256,
                        requested.size,
                    )
                except Exception as exc:
                    flight.failure = (type(exc), exc.args)
                    raise
                with review_cache_lock:
                    cached = verified_review_artifacts.get(artifact_key)
                    if cached is None:
                        verified_review_artifacts[artifact_key] = source
                        verified_review_artifacts.move_to_end(artifact_key)
                        while len(verified_review_artifacts) > 256:
                            verified_review_artifacts.popitem(last=False)
                    else:
                        source = cached
                        verified_review_artifacts.move_to_end(artifact_key)
            return source
        finally:
            _release_flight(
                verification_flights,
                artifact_key,
                flight,
                review_cache_lock,
            )

    def authorize_review_artifact(
        requested: BlobRef,
    ) -> tuple[ReviewArtifactContext, Path]:
        authorized = load_authorized_contexts()
        context = authorized.get(requested)
        if context is None:
            raise ValueError("review artifact is not authorized")
        return context, verified_artifact_path(requested)

    @app.get("/api/v3/status", operation_id="getStatus")
    def status() -> WorkflowStatus:
        return query_status(production.workflows)

    def current_state_revision() -> int:
        head = production.repository.read_head()
        return 0 if head is None else head.revision

    @app.get("/api/v3/voice", operation_id="getVoiceRecorder")
    def voice_recorder() -> VoiceRecorderContext:
        return query_voice_recorder(
            production.assets,
            production.repository.objects,
            production_id=production.production_id,
            authoring_path=production.authoring_path,
            state_revision=current_state_revision(),
            workflows=production.workflows,
        )

    @app.post(
        "/api/v3/voice/takes",
        operation_id="recordVoiceTake",
        responses={
            200: {"description": "Voice take saved as an immutable asset"},
            413: {"description": "Voice take exceeds 64 MiB"},
        },
    )
    async def record_voice_take_route(
        request: Request,
        expected_revision: int = Query(ge=0),
        recorded_at: str = Header(alias="X-Recorded-At", min_length=1),
        duration_ms: int = Header(alias="X-Duration-Ms", gt=0),
        expected_production_id: str = Header(
            alias="X-Production-Id", min_length=1
        ),
        expected_script_sha256: str = Header(
            alias="X-Script-Sha256", pattern=r"^[0-9a-f]{64}$"
        ),
        expected_script_size: int = Header(alias="X-Script-Size", gt=0),
    ) -> VoiceRecorderContext:
        mime_type = request.headers.get("content-type", "").split(";", 1)[0]
        if not mime_type.startswith("audio/"):
            raise HTTPException(
                status_code=415,
                detail="voice take requires an audio content type",
            )
        staging_root = production.repository.staging_root
        staging_root.mkdir(parents=True, exist_ok=True)
        fd, raw_path = tempfile.mkstemp(prefix="voice-upload-", dir=staging_root)
        source = Path(raw_path)
        size = 0
        try:
            with os.fdopen(fd, "wb") as handle:
                async for chunk in request.stream():
                    size += len(chunk)
                    if size > 64 * 1024 * 1024:
                        raise HTTPException(
                            status_code=413,
                            detail="voice take exceeds 64 MiB",
                        )
                    handle.write(chunk)
            if size == 0:
                raise HTTPException(status_code=422, detail="voice take is empty")
            from .providers.media import FfprobeMediaInspector

            state_revision = record_voice_take(
                production.assets,
                production.repository.objects,
                production_id=production.production_id,
                authoring_path=production.authoring_path,
                source=source,
                take_id=uuid.uuid4().hex,
                recorded_at=recorded_at,
                duration_ms=duration_ms,
                mime_type=mime_type,
                expected_production_id=expected_production_id,
                expected_script_ref=BlobRef(
                    expected_script_sha256, expected_script_size
                ),
                expected_revision=expected_revision,
                inspect_media=FfprobeMediaInspector(),
            )
        finally:
            source.unlink(missing_ok=True)
        return query_voice_recorder(
            production.assets,
            production.repository.objects,
            production_id=production.production_id,
            authoring_path=production.authoring_path,
            state_revision=state_revision,
            workflows=production.workflows,
        )

    @app.post(
        "/api/v3/voice/takes/{asset_id}/approve",
        operation_id="approveVoiceTake",
    )
    def approve_voice_take_route(
        body: ApproveVoiceTakeBody,
        asset_id: str = PathParam(min_length=1),
    ) -> VoiceRecorderContext:
        from .providers.media import FfprobeMediaInspector

        state_revision = approve_voice_take(
            production.assets,
            production.repository.objects,
            production_id=production.production_id,
            authoring_path=production.authoring_path,
            asset_id=asset_id,
            approved_at=body.approved_at,
            expected_production_id=body.expected_production_id,
            expected_script_ref=body.expected_script_ref,
            expected_revision=body.expected_revision,
            inspect_media=FfprobeMediaInspector(),
        )
        return query_voice_recorder(
            production.assets,
            production.repository.objects,
            production_id=production.production_id,
            authoring_path=production.authoring_path,
            state_revision=state_revision,
            workflows=production.workflows,
        )

    @app.post("/api/v3/advance", operation_id="advanceProduction")
    def advance_route() -> WorkflowStatus:
        return project_status(_advance(production))

    @app.post("/api/v3/review", operation_id="submitReview")
    def review(body: ReviewVerdictBody) -> WorkflowStatus:
        payload = body.model_dump(
            exclude={
                "expected_artifact",
                "expected_timeline",
                "expected_artifact_report",
                "expected_publication_manifest",
                "expected_check_report",
                "expected_constraints",
            }
        )
        return project_status(
            submit_review_payload(
                production.workflows,
                payload,
                production.repository.objects,
                expected_artifact=body.expected_artifact,
                expected_timeline=body.expected_timeline,
                expected_artifact_report=body.expected_artifact_report,
                expected_publication_manifest=(
                    body.expected_publication_manifest
                ),
                expected_check_report=body.expected_check_report,
                expected_constraints=body.expected_constraints,
            )
        )

    @app.get("/api/v3/review/context", operation_id="getReviewContext")
    def review_context() -> ReviewContext:
        return query_review_context(
            production.workflows,
            production.repository.objects,
        )

    @app.get("/api/v3/review/current", operation_id="getCurrentReview")
    def current_review() -> ReviewVerdict:
        return query_current_review(
            production.workflows,
            production.repository.objects,
        )

    @app.get(
        "/api/v3/review/task-pack",
        operation_id="getReviewTaskPack",
    )
    def review_task_pack() -> ReviewTaskPack:
        pack = query_review_task_pack(
            production.workflows,
            production.repository.objects,
        )
        if pack is None:
            raise HTTPException(
                status_code=404,
                detail="no submitted review round",
            )
        return pack

    @app.get(
        "/api/v3/review/artifacts/{sha256}",
        operation_id="getReviewArtifact",
        response_class=Response,
        responses={200: {"content": {"video/mp4": {}}}},
    )
    @app.head(
        "/api/v3/review/artifacts/{sha256}",
        include_in_schema=False,
    )
    def review_artifact(
        sha256: str = PathParam(pattern=r"^[0-9a-f]{64}$"),
        size: int = Query(gt=0),
    ) -> FileResponse:
        requested = BlobRef(sha256, size)
        _, source = authorize_review_artifact(requested)
        return FileResponse(source, media_type="video/mp4")

    @app.get(
        "/api/v3/review/artifacts/{sha256}/evidence",
        operation_id="getReviewFrameEvidence",
        response_class=Response,
        responses={
            200: {
                "description": "Exact bounded JPEG review evidence",
                "headers": {
                    "ETag": {
                        "description": "SHA-256 identity of the JPEG bytes",
                        "schema": {"type": "string"},
                    }
                },
                "content": {
                    "image/jpeg": {
                        "schema": {
                            "type": "string",
                            "format": "binary",
                        }
                    }
                },
            }
        },
    )
    def review_frame_evidence(
        sha256: str = PathParam(pattern=r"^[0-9a-f]{64}$"),
        size: int = Query(gt=0),
        frame: int = Query(ge=0),
        width: int = Query(ge=64, le=640),
        x_milli: int | None = Query(default=None, ge=0, le=999),
        y_milli: int | None = Query(default=None, ge=0, le=999),
        width_milli: int | None = Query(default=None, ge=1, le=1000),
        height_milli: int | None = Query(default=None, ge=1, le=1000),
    ) -> Response:
        requested = BlobRef(sha256, size)
        context, source = authorize_review_artifact(requested)
        coordinates = (x_milli, y_milli, width_milli, height_milli)
        if any(value is not None for value in coordinates) and not all(
            value is not None for value in coordinates
        ):
            raise HTTPException(
                status_code=422,
                detail="all review evidence region coordinates are required",
            )
        region = (
            None
            if all(value is None for value in coordinates)
            else tuple(int(value) for value in coordinates if value is not None)
        )
        result = query_review_frame_evidence(
            context,
            source,
            frame=frame,
            width=width,
            region_milli=region,
            cache_root=presentation_cache_root,
        )
        return Response(
            content=result.content,
            media_type=result.media_type,
            headers={"ETag": f'"{result.content_ref.sha256}"'},
        )

    @app.get(
        "/api/v3/review/artifacts/{sha256}/waveform",
        operation_id="getReviewWaveform",
    )
    def review_waveform(
        sha256: str = PathParam(pattern=r"^[0-9a-f]{64}$"),
        size: int = Query(gt=0),
        samples: int = Query(ge=256, le=8192),
    ) -> ReviewWaveform:
        requested = BlobRef(sha256, size)
        context, source = authorize_review_artifact(requested)
        return query_review_waveform(
            context,
            source,
            sample_count=samples,
            cache_root=presentation_cache_root,
        )

    @app.post("/api/v3/deliver", operation_id="deliverProduction")
    def deliver(body: DeliveryBody) -> DeliveryResponse:
        workflow, receipt = deliver_local(
            production.workflows,
            production.delivery_root,
            destination_id=body.destination_id,
            expected_candidate=body.expected_candidate,
        )
        return DeliveryResponse(status=project_status(workflow), receipt=receipt)

    @app.get(
        "/api/v3/delivery/context",
        operation_id="getDeliveryContext",
    )
    def delivery_context() -> DeliveryContext:
        return query_delivery_context(production.workflows)

    @app.get(
        "/api/v3/blobs/{sha256}",
        operation_id="getBlob",
        response_class=Response,
        responses={200: {"content": {"application/octet-stream": {}}}},
    )
    def blob(
        sha256: str = PathParam(pattern=r"^[0-9a-f]{64}$"),
        size: int = Query(gt=0),
    ) -> FileResponse:
        source = resolve_blob(production.repository.objects, sha256, size)
        return FileResponse(source, media_type="application/octet-stream")

    static_root = Path(__file__).with_name("static")
    app.mount(
        "/assets",
        StaticFiles(directory=static_root / "assets", check_dir=False),
        name="studio-v3-assets",
    )

    @app.get("/", include_in_schema=False)
    def dashboard() -> FileResponse:
        return FileResponse(static_root / "index.html")

    return app
