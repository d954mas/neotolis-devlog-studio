"""Thin FastAPI adapter bound to one explicit Studio v3 production."""

from __future__ import annotations

from collections import OrderedDict
from pathlib import Path
from threading import Lock
from typing import Literal
from urllib.parse import urlsplit

from fastapi import (
    FastAPI,
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
    deliver_local,
    project_status,
    query_authorized_review_artifacts,
    query_current_review,
    query_review_context,
    query_review_task_pack,
    query_status,
    ReviewContext,
    ReviewTaskPack,
    ReviewVerdict,
    resolve_blob,
    submit_review_payload,
    StudioError,
    WorkflowStatus,
)

from .local import LocalProduction, load_local_production

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "testserver"})


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


class DeliveryResponse(_Body):
    status: WorkflowStatus
    receipt: DeliveryReceipt


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
        frozenset[BlobRef],
    ] = OrderedDict()
    verified_review_artifacts: OrderedDict[
        tuple[str, int],
        None,
    ] = OrderedDict()
    review_cache_lock = Lock()
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

    @app.get("/api/v3/status", operation_id="getStatus")
    def status() -> WorkflowStatus:
        return query_status(production.workflows)

    @app.post("/api/v3/advance", operation_id="advanceProduction")
    def advance_route() -> WorkflowStatus:
        return project_status(_advance(production))

    @app.post("/api/v3/review", operation_id="submitReview")
    def review(body: ReviewVerdictBody) -> WorkflowStatus:
        payload = body.model_dump(
            exclude={
                "expected_artifact",
                "expected_timeline",
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
        authorization_key = (
            production.workflows.head_revision(),
            production.workflows.read_latest_review_round_ref(),
        )
        with review_cache_lock:
            authorized = authorized_review_artifacts.get(authorization_key)
            if authorized is not None:
                authorized_review_artifacts.move_to_end(authorization_key)
        if authorized is None:
            computed = frozenset(
                query_authorized_review_artifacts(
                    production.workflows,
                    production.repository.objects,
                )
            )
            with review_cache_lock:
                authorized = authorized_review_artifacts.get(
                    authorization_key
                )
                if authorized is None:
                    authorized = computed
                    authorized_review_artifacts[authorization_key] = authorized
                    while len(authorized_review_artifacts) > 8:
                        authorized_review_artifacts.popitem(last=False)
                else:
                    authorized_review_artifacts.move_to_end(authorization_key)
        if requested not in authorized:
            raise ValueError("review artifact is not authorized")

        artifact_key = (sha256, size)
        with review_cache_lock:
            verified = artifact_key in verified_review_artifacts
            if verified:
                verified_review_artifacts.move_to_end(artifact_key)
        if not verified:
            source = resolve_blob(
                production.repository.objects,
                sha256,
                size,
            )
            with review_cache_lock:
                verified_review_artifacts[artifact_key] = None
                verified_review_artifacts.move_to_end(artifact_key)
                while len(verified_review_artifacts) > 256:
                    verified_review_artifacts.popitem(last=False)
        else:
            source = production.repository.objects.path_for(requested)
        return FileResponse(source, media_type="video/mp4")

    @app.post("/api/v3/deliver", operation_id="deliverProduction")
    def deliver(body: DeliveryBody) -> DeliveryResponse:
        workflow, receipt = deliver_local(
            production.workflows,
            production.delivery_root,
            destination_id=body.destination_id,
        )
        return DeliveryResponse(status=project_status(workflow), receipt=receipt)

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
