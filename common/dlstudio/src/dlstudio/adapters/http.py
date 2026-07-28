"""Thin FastAPI adapter bound to one explicit Studio v3 production."""

from __future__ import annotations

from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

from fastapi import FastAPI, Path as PathParam, Query, Request, Response
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.trustedhost import TrustedHostMiddleware
from pydantic import BaseModel, ConfigDict

from dlstudio.application.api import (
    advance_production,
    CasConflict,
    CorruptObject,
    DeliveryReceipt,
    deliver_local,
    project_status,
    query_status,
    resolve_blob,
    submit_review_payload,
    StudioError,
    WorkflowStatus,
)

from .local import LocalProduction, load_local_production

_LOCAL_HOSTS = frozenset({"127.0.0.1", "localhost", "testserver"})


class _Body(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ReviewFindingBody(_Body):
    finding_id: str
    text: str
    requires_change: bool = False


class ReviewVerdictBody(_Body):
    outcome: Literal["pass", "changes_requested", "block"]
    scope: list[str]
    reviewer: str
    reviewed_at: str
    findings: list[ReviewFindingBody]


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
        return project_status(
            submit_review_payload(production.workflows, body.model_dump())
        )

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
