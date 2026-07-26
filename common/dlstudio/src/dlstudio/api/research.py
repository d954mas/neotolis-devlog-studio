"""FastAPI router for the workspace-scoped Studio research lab."""
from __future__ import annotations

from pathlib import Path
import re
from typing import Literal
from urllib.parse import urlparse

from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field, HttpUrl

from dlstudio.services import research, research_media, research_scrapecreators


class ResearchProjectRequest(BaseModel):
    title: str = Field(min_length=1, max_length=120)
    description: str = Field(default="", max_length=2000)
    style_profile: str = Field(default="", max_length=8000)


class ResearchAuthorRequest(BaseModel):
    username: str = Field(min_length=1, max_length=80)
    display_name: str = Field(default="", max_length=160)
    profile_url: HttpUrl | None = None
    followers_count: int | None = Field(default=None, ge=0)
    median_views: int | None = Field(default=None, ge=0)


class ResearchReelRequest(BaseModel):
    id: str = Field(min_length=1, max_length=160)
    author_id: str = Field(min_length=1, max_length=80)
    url: HttpUrl
    published_at: str = Field(min_length=10, max_length=40)
    caption: str = Field(default="", max_length=20_000)
    thumbnail_url: HttpUrl | None = None
    duration_seconds: float | None = Field(default=None, ge=0)
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    hook: str = Field(default="", max_length=4000)
    patterns: list[str] = Field(default_factory=list, max_length=40)
    metrics_captured_at: str | None = Field(default=None, max_length=40)
    platform: str = Field(default="instagram", max_length=40)


class ResearchExperimentRequest(BaseModel):
    reel_id: str = Field(min_length=1, max_length=160)
    mode: Literal["inspiration", "adaptation", "remake"] = "adaptation"
    hypothesis: str = Field(default="", max_length=8000)
    take_from_reference: list[str] = Field(default_factory=list, max_length=30)
    keep_original: list[str] = Field(default_factory=list, max_length=30)


class ResearchExperimentResultRequest(BaseModel):
    verdict: Literal["worked", "mixed", "did_not_work", "inconclusive"]
    published_url: HttpUrl | None = None
    views: int = Field(default=0, ge=0)
    likes: int = Field(default=0, ge=0)
    comments: int = Field(default=0, ge=0)
    notes: str = Field(default="", max_length=8000)
    measured_at: str | None = Field(default=None, max_length=40)


class ResearchSyncRequest(BaseModel):
    author_ids: list[str] | None = Field(default=None, max_length=25)


class ResearchQuickAddRequest(BaseModel):
    kind: Literal["author", "reel"]
    value: str = Field(min_length=1, max_length=1000)


def _instagram_username(value: str) -> str:
    source = value.strip()
    if source.startswith("@"):
        username = source[1:]
    elif "://" in source:
        parsed = urlparse(source)
        host = parsed.netloc.lower().split(":", 1)[0]
        if parsed.scheme not in {"http", "https"} or host not in {
            "instagram.com", "www.instagram.com", "m.instagram.com"
        }:
            raise research.ResearchError("paste an Instagram profile link or @username")
        parts = [part for part in parsed.path.split("/") if part]
        if not parts or parts[0].lower() in {"reel", "reels", "p", "tv", "stories", "explore"}:
            raise research.ResearchError("paste an Instagram profile link or @username")
        username = parts[0]
    else:
        username = source
    username = username.strip().lstrip("@").lower()
    if not re.fullmatch(r"[a-z0-9._]{1,80}", username):
        raise research.ResearchError("Instagram username contains unsupported characters")
    return username


def create_research_router(workspace_root: Path) -> APIRouter:
    router = APIRouter(prefix="/api/research", tags=["research"])

    def call(fn, *args, **kwargs):
        try:
            return fn(*args, **kwargs)
        except research.ResearchError as exc:
            message = str(exc)
            status = 404 if message.startswith("unknown ") else 400
            raise HTTPException(status_code=status, detail=message) from exc

    @router.get("/projects")
    def list_research_projects() -> list[dict]:
        return call(research.list_projects, workspace_root)

    @router.post("/projects", status_code=201)
    def create_research_project(body: ResearchProjectRequest) -> dict:
        return call(
            research.create_project,
            workspace_root,
            title=body.title,
            description=body.description,
            style_profile=body.style_profile,
        )

    @router.get("/collector/status")
    def get_research_collector_status() -> dict:
        return research_scrapecreators.collector_status()

    @router.get("/media-cache")
    def get_research_media_cache() -> dict:
        return research_media.summary(workspace_root)

    @router.delete("/media-cache")
    def clear_research_media_cache() -> dict:
        return research_media.clear(workspace_root)

    @router.post("/projects/{project_id}/sync")
    def sync_research_project(project_id: str, body: ResearchSyncRequest) -> dict:
        try:
            return research_scrapecreators.sync_project(
                workspace_root,
                project_id,
                author_ids=body.author_ids,
            )
        except research.ResearchError as exc:
            message = str(exc)
            status = 404 if message.startswith("unknown research project") else 400
            raise HTTPException(status_code=status, detail=message) from exc
        except research_scrapecreators.ScrapeCreatorsError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc

    @router.post("/projects/{project_id}/quick-add", status_code=201)
    def quick_add_research_source(project_id: str, body: ResearchQuickAddRequest) -> dict:
        if body.kind == "reel":
            try:
                return research_scrapecreators.import_reel_url(
                    workspace_root,
                    project_id,
                    url=body.value,
                )
            except research.ResearchError as exc:
                message = str(exc)
                status = 404 if message.startswith("unknown research project") else 400
                raise HTTPException(status_code=status, detail=message) from exc
            except research_scrapecreators.ScrapeCreatorsError as exc:
                raise HTTPException(status_code=503, detail=str(exc)) from exc

        username = call(_instagram_username, body.value)
        feed = call(research.get_project_feed, workspace_root, project_id, window="all")
        existing = next((item for item in feed["authors"] if item.get("id") == username), None)
        if existing is not None:
            return {
                "kind": "author",
                "created": False,
                "author_created": False,
                "credits_used": 0,
                "author": existing,
                "reel": None,
            }
        author = call(
            research.add_author,
            workspace_root,
            project_id,
            username=username,
            profile_url=f"https://www.instagram.com/{username}/",
        )
        return {
            "kind": "author",
            "created": True,
            "author_created": True,
            "credits_used": 0,
            "author": author,
            "reel": None,
        }

    @router.get("/projects/{project_id}")
    def get_research_project(
        project_id: str,
        window: Literal["7d", "30d", "90d", "all"] = Query(default="all", alias="range"),
        sort: Literal["outlier", "velocity", "views", "newest"] = "newest",
        author_id: str | None = None,
        limit: int = Query(default=60, ge=1, le=100),
        cursor: str | None = Query(default=None, max_length=1000),
    ) -> dict:
        return call(
            research.get_project_feed,
            workspace_root,
            project_id,
            window=window,
            sort=sort,
            author_id=author_id,
            limit=limit,
            cursor=cursor,
        )

    @router.post("/projects/{project_id}/authors", status_code=201)
    def add_research_author(project_id: str, body: ResearchAuthorRequest) -> dict:
        return call(
            research.add_author,
            workspace_root,
            project_id,
            username=body.username,
            display_name=body.display_name,
            profile_url=str(body.profile_url) if body.profile_url else "",
            followers_count=body.followers_count,
            median_views=body.median_views,
        )

    @router.delete("/projects/{project_id}/authors/{author_id}")
    def remove_research_author(project_id: str, author_id: str) -> dict:
        return call(research.remove_author, workspace_root, project_id, author_id)

    @router.post("/projects/{project_id}/reels", status_code=201)
    def ingest_research_reel(project_id: str, body: ResearchReelRequest) -> dict:
        return call(
            research.ingest_reel,
            workspace_root,
            project_id,
            reel_id=body.id,
            author_id=body.author_id,
            url=str(body.url),
            published_at=body.published_at,
            caption=body.caption,
            thumbnail_url=str(body.thumbnail_url) if body.thumbnail_url else "",
            duration_seconds=body.duration_seconds,
            views=body.views,
            likes=body.likes,
            comments=body.comments,
            hook=body.hook,
            patterns=body.patterns,
            metrics_captured_at=body.metrics_captured_at,
            platform=body.platform,
        )

    @router.post("/projects/{project_id}/reels/{reel_id}/media")
    def cache_research_reel_media(project_id: str, reel_id: str) -> dict:
        try:
            return research_media.download(
                workspace_root,
                project_id,
                reel_id,
                resolve_media_url=research_scrapecreators.resolve_reel_video_url,
            )
        except research.ResearchError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        except research_scrapecreators.ScrapeCreatorsError as exc:
            raise HTTPException(status_code=503, detail=str(exc)) from exc
        except research_media.ResearchMediaError as exc:
            raise HTTPException(status_code=502, detail=str(exc)) from exc

    @router.get("/projects/{project_id}/reels/{reel_id}/media")
    def get_research_reel_media(project_id: str, reel_id: str) -> FileResponse:
        try:
            info = research_media.status(workspace_root, project_id, reel_id)
        except research.ResearchError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if not info["cached"]:
            raise HTTPException(status_code=404, detail="Reel video is not cached")
        path = research_media.media_path(workspace_root, project_id, reel_id)
        return FileResponse(path, media_type="video/mp4")

    @router.delete("/projects/{project_id}/reels/{reel_id}/media")
    def delete_research_reel_media(project_id: str, reel_id: str) -> dict:
        try:
            return research_media.delete(workspace_root, project_id, reel_id)
        except research.ResearchError as exc:
            raise HTTPException(status_code=404, detail=str(exc)) from exc

    @router.post("/projects/{project_id}/experiments", status_code=201)
    def create_research_experiment(project_id: str, body: ResearchExperimentRequest) -> dict:
        return call(
            research.create_experiment,
            workspace_root,
            project_id,
            reel_id=body.reel_id,
            mode=body.mode,
            hypothesis=body.hypothesis,
            take_from_reference=body.take_from_reference,
            keep_original=body.keep_original,
        )

    @router.post(
        "/projects/{project_id}/experiments/{experiment_id}/result",
        status_code=200,
    )
    def record_research_experiment_result(
        project_id: str,
        experiment_id: str,
        body: ResearchExperimentResultRequest,
    ) -> dict:
        return call(
            research.record_experiment_result,
            workspace_root,
            project_id,
            experiment_id,
            verdict=body.verdict,
            published_url=str(body.published_url) if body.published_url else "",
            views=body.views,
            likes=body.likes,
            comments=body.comments,
            notes=body.notes,
            measured_at=body.measured_at,
        )

    return router
