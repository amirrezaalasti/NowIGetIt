"""FastAPI entrypoint for Vercel (Python runtime) and local uvicorn."""

from __future__ import annotations

import mimetypes
import sys
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, StreamingResponse

# Ensure repo root is importable (backend package)
ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from backend import artifacts as store
from backend import supabase_db as db
from backend.auth import CurrentUser, MediaUser, auth_is_configured
from backend.config import get_settings
from backend.pipeline.orchestrator import (
    approve_scene,
    iter_continue_events,
    iter_pipeline_events,
    iter_regenerate_scene,
    iter_retouch_scene,
    run_pipeline,
    update_scene_plan,
)
from backend.schemas import (
    ContinueRequest,
    GenerateRequest,
    GenerateResult,
    RegenerateSceneRequest,
    SceneComment,
    SceneCommentRequest,
    UpdatePlanRequest,
)


def _quota_http(exc: db.QuotaExceededError) -> HTTPException:
    return HTTPException(
        status_code=402,
        detail={"code": exc.code, "message": exc.detail},
    )


def _prepare_user(user: CurrentUser) -> None:
    db.ensure_user(
        user_id=user.id,
        email=user.email,
        name=user.name,
        image_url=user.image,
    )

app = FastAPI(
    title="NowIGetIt API",
    description="Scene-planned Manim video generation with VLM review and TTS",
    version="0.1.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _require_job_owner(job_id: str, user_id: str) -> None:
    try:
        store.assert_job_owner(job_id, user_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc


@app.get("/api/health")
def health() -> dict:
    settings = get_settings()
    manim_available = False
    manim_version = None
    try:
        import manim

        manim_available = True
        manim_version = getattr(manim, "__version__", "unknown")
    except ImportError:
        pass
    artifacts_path = None
    try:
        artifacts_path = str(store.artifacts_root())
    except OSError:
        artifacts_path = "unavailable"
    worker_ok: bool | None = None
    worker_detail = None
    if settings.render_worker_url:
        try:
            import httpx

            with httpx.Client(timeout=5.0) as client:
                wr = client.get(f"{settings.render_worker_url.rstrip('/')}/health")
            worker_ok = wr.status_code == 200 and "nowigetit-render-worker" in wr.text
            worker_detail = (
                "ok"
                if worker_ok
                else f"unexpected response HTTP {wr.status_code} (is RENDER_WORKER_URL the Manim worker?)"
            )
        except Exception as exc:  # noqa: BLE001
            worker_ok = False
            worker_detail = f"unreachable: {exc}"

    return {
        "ok": True,
        "model": settings.openrouter_model,
        "vlm_model": settings.openrouter_vlm_model,
        "openrouter_configured": bool(settings.openrouter_api_key),
        "tts_configured": bool(settings.tts_api_key),
        "manim_render_enabled": settings.enable_manim_render,
        "manim_available": manim_available,
        "manim_version": manim_version,
        "artifacts_root": artifacts_path,
        "auth_configured": auth_is_configured(),
        "supabase_configured": db.supabase_enabled(),
        "render_worker_configured": bool(settings.render_worker_url),
        "render_worker_ok": worker_ok,
        "render_worker_detail": worker_detail,
    }


@app.get("/api/me")
def me(user: CurrentUser) -> dict:
    """Current user profile + monthly LLM/storage usage."""
    _prepare_user(user)
    usage = db.get_user_usage(user.id)
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "image": user.image,
        },
        "usage": usage,
        "supabase_configured": db.supabase_enabled(),
    }


@app.post("/api/generate", response_model=GenerateResult)
def generate(request: GenerateRequest, user: CurrentUser) -> GenerateResult:
    """Run the full pipeline and return the final result."""
    settings = get_settings()
    try:
        _prepare_user(user)
        db.reserve_generation(
            user.id,
            estimated_tokens=settings.default_llm_estimate_tokens,
        )
        return run_pipeline(
            request,
            user_id=user.id,
            user_email=user.email,
            user_name=user.name,
        )
    except db.QuotaExceededError as exc:
        raise _quota_http(exc) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/generate/stream")
def generate_stream(request: GenerateRequest, user: CurrentUser) -> StreamingResponse:
    """SSE stream of pipeline events for live UI progress."""
    settings = get_settings()
    try:
        _prepare_user(user)
        db.reserve_generation(
            user.id,
            estimated_tokens=settings.default_llm_estimate_tokens,
        )
    except db.QuotaExceededError as exc:
        raise _quota_http(exc) from exc

    def event_stream():
        try:
            for chunk in iter_pipeline_events(
                request,
                user_id=user.id,
                user_email=user.email,
                user_name=user.name,
            ):
                yield chunk
        except db.QuotaExceededError as exc:
            import json

            yield f"data: {json.dumps({'type': 'error', 'message': exc.detail, 'data': {'code': exc.code}})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/jobs")
def list_jobs(user: CurrentUser, limit: int = 50) -> dict:
    return {"jobs": store.list_jobs(limit=limit, user_id=user.id)}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user: CurrentUser) -> dict:
    _require_job_owner(job_id, user.id)
    try:
        return store.load_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc


@app.put("/api/jobs/{job_id}/plan")
def put_scene_plan(
    job_id: str, body: UpdatePlanRequest, user: CurrentUser
) -> dict:
    """Save an edited storyboard before continuing generation."""
    _require_job_owner(job_id, user.id)
    plan = update_scene_plan(job_id, body.plan)
    return {"ok": True, "job_id": job_id, "plan": plan.model_dump()}


@app.post("/api/jobs/{job_id}/continue/stream")
def continue_stream(
    job_id: str,
    user: CurrentUser,
    body: ContinueRequest = ContinueRequest(),
) -> StreamingResponse:
    """SSE: continue a plan_only job after the user confirms the storyboard."""
    _require_job_owner(job_id, user.id)
    try:
        db.assert_within_quotas(user.id, need_tokens=20_000)
    except db.QuotaExceededError as exc:
        raise _quota_http(exc) from exc

    def event_stream():
        try:
            for chunk in iter_continue_events(
                job_id, body, user_id=user.id
            ):
                yield chunk
        except db.QuotaExceededError as exc:
            import json

            yield f"data: {json.dumps({'type': 'error', 'message': exc.detail, 'data': {'code': exc.code}})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/jobs/{job_id}/scenes/{scene_id}/regenerate/stream")
def regenerate_scene_stream(
    job_id: str,
    scene_id: str,
    user: CurrentUser,
    body: RegenerateSceneRequest = RegenerateSceneRequest(),
) -> StreamingResponse:
    """SSE: regenerate one scene from its plan section (optionally with direction)."""
    _require_job_owner(job_id, user.id)
    try:
        db.assert_within_quotas(user.id, need_tokens=8_000)
    except db.QuotaExceededError as exc:
        raise _quota_http(exc) from exc

    def event_stream():
        try:
            for chunk in iter_regenerate_scene(job_id, scene_id, body):
                yield chunk
        except db.QuotaExceededError as exc:
            import json

            yield f"data: {json.dumps({'type': 'error', 'message': exc.detail, 'data': {'code': exc.code}})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/jobs/{job_id}/scenes/{scene_id}/comments")
def get_scene_comments(job_id: str, scene_id: str, user: CurrentUser) -> dict:
    _require_job_owner(job_id, user.id)
    return {"comments": store.get_scene_comments(job_id, scene_id)}


@app.post("/api/jobs/{job_id}/scenes/{scene_id}/comments", response_model=SceneComment)
def add_scene_comment(
    job_id: str, scene_id: str, body: SceneCommentRequest, user: CurrentUser
) -> SceneComment:
    """Save a human comment. The frontend should then call /retouch/stream to apply it."""
    _require_job_owner(job_id, user.id)
    author = user.name or user.email or "User"
    comment_data = store.add_scene_comment(
        job_id,
        scene_id,
        comment=body.comment,
        timestamp=body.timestamp,
        author=author,
    )
    return SceneComment(**comment_data)


@app.post("/api/jobs/{job_id}/scenes/{scene_id}/retouch/stream")
def retouch_scene_stream(
    job_id: str, scene_id: str, body: SceneCommentRequest, user: CurrentUser
) -> StreamingResponse:
    """SSE stream: AI reads the comment, revises code, and re-renders the scene."""
    _require_job_owner(job_id, user.id)
    try:
        db.assert_within_quotas(user.id, need_tokens=5_000)
    except db.QuotaExceededError as exc:
        raise _quota_http(exc) from exc

    def event_stream():
        try:
            for chunk in iter_retouch_scene(
                job_id,
                scene_id,
                human_instructions=body.comment,
                timestamp=body.timestamp,
            ):
                yield chunk
        except db.QuotaExceededError as exc:
            import json

            yield f"data: {json.dumps({'type': 'error', 'message': exc.detail, 'data': {'code': exc.code}})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/jobs/{job_id}/scenes/{scene_id}/approve")
def approve_scene_endpoint(job_id: str, scene_id: str, user: CurrentUser) -> dict:
    """
    Human approves the AI retouch for this scene.
    Muxes scene audio and re-composes the final video.
    """
    _require_job_owner(job_id, user.id)
    try:
        return approve_scene(job_id, scene_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/jobs/{job_id}/file/{file_path:path}")
def get_job_file(job_id: str, file_path: str, user: MediaUser) -> FileResponse:
    _require_job_owner(job_id, user.id)
    try:
        path = store.resolve_job_file(job_id, file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    media_type, _ = mimetypes.guess_type(str(path))
    headers = {
        "Accept-Ranges": "bytes",
        "Cache-Control": "private, max-age=60",
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Expose-Headers": "Content-Length, Content-Range, Accept-Ranges",
    }
    return FileResponse(
        path,
        media_type=media_type or "application/octet-stream",
        headers=headers,
    )


@app.get("/")
def root() -> dict:
    return {
        "service": "NowIGetIt API",
        "docs": "/docs",
        "health": "/api/health",
        "jobs": "/api/jobs",
    }
