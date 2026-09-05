"""FastAPI entrypoint for Vercel (Python runtime) and local uvicorn."""

from __future__ import annotations

import asyncio
import mimetypes
import sys
import tempfile
from pathlib import Path
from typing import Optional

from fastapi import Body, FastAPI, File, HTTPException, UploadFile
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
from backend import job_runner
from backend.languages import languages_for_api
from backend.tts_voices import voices_for_api
from backend.pipeline.orchestrator import (
    aiter_continue_events,
    aiter_job_event_stream,
    approve_scene,
    iter_pipeline_events,
    iter_regenerate_scene,
    iter_retouch_scene,
    job_codegen_spec,
    job_is_host_authored,
    patch_scene_section,
    prepare_production_options,
    ProductionOptionsRequired,
    revise_scene_plan,
    run_pipeline,
    submit_host_scene_code,
    update_job_settings,
    update_scene_plan,
)
from backend.pipeline.planner import planning_spec_payload
from backend.pipeline.tts import synthesize_narration
from backend.documents import store as doc_store
from backend.documents.pipeline import (
    ask_document_block,
    iter_document_ingest_events,
    load_document,
    run_document_ingest,
)
from backend.documents.schemas import (
    SUPPORTED_EXTENSIONS,
    DocumentAnnotation,
    DocumentAskRequest,
    DocumentAskResult,
    DocumentCommentRequest,
)
from backend.documents.source import extract_upload, list_library_sources
from backend.learn.pipeline import (
    check_lab_progress,
    grade_quiz_item,
    iter_learn_events,
    load_item as load_learn_item,
    run_learn,
)
from backend.learn.schemas import (
    LabProgressRequest,
    LearnGenerateRequest,
    QuizGradeRequest,
)
from backend.schemas import (
    ContinueRequest,
    GenerateRequest,
    GenerateResult,
    JobSettingsRequest,
    PatchSceneRequest,
    RegenerateSceneRequest,
    RevisePlanRequest,
    SceneComment,
    SceneCommentRequest,
    StorageModeRequest,
    SubmitSceneCodeRequest,
    UpdatePlanRequest,
    VideoMarkRequest,
)


def _storage_mode() -> str:
    from backend.local_db import storage_mode

    get_settings()
    return storage_mode()


def _database_name() -> str:
    mode = _storage_mode()
    if mode == "local":
        return "sqlite"
    return mode


def _mongo_configured() -> bool:
    from backend.local_db import mongo_configured

    get_settings()
    return mongo_configured()


def _supabase_available() -> bool:
    from backend.local_db import supabase_available

    get_settings()
    return supabase_available()


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


def _require_scene_free(job_id: str, scene_id: str) -> None:
    """Reject an edit only for the one scene that is mid-generation.

    Every other scene stays editable, including while the pipeline builds the
    rest of the video and while sibling scenes are being edited.
    """
    if job_runner.is_scene_busy(job_id, scene_id):
        raise HTTPException(
            status_code=409,
            detail={
                "code": "SCENE_BUSY",
                "message": (
                    f"Scene {scene_id} is being generated or edited right now. "
                    "Wait for it to finish, then try again."
                ),
                "scene_id": scene_id,
            },
        )


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
    worker_ok: Optional[bool] = None
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

    docling_ok: Optional[bool] = None
    docling_detail = None
    docling_local = False
    try:
        import docling  # noqa: F401

        docling_local = True
    except ImportError:
        pass
    if settings.docling_worker_url:
        try:
            import httpx

            with httpx.Client(timeout=5.0) as client:
                wr = client.get(f"{settings.docling_worker_url.rstrip('/')}/health")
            docling_ok = wr.status_code == 200 and "nowigetit-docling-worker" in wr.text
            docling_detail = (
                "ok"
                if docling_ok
                else f"unexpected response HTTP {wr.status_code}"
            )
        except Exception as exc:  # noqa: BLE001
            docling_ok = False
            docling_detail = f"unreachable: {exc}"

    return {
        "ok": True,
        "model": settings.openrouter_model,
        "manim_model": settings.openrouter_model_manim,
        "vlm_model": settings.openrouter_vlm_model,
        "openrouter_configured": bool(settings.openrouter_api_key),
        "tts_configured": bool(settings.tts_api_key),
        "tts_model": settings.tts_model,
        "tts_voice": settings.tts_voice,
        "tts_voices": voices_for_api(),
        "languages": languages_for_api(),
        "manim_render_enabled": settings.enable_manim_render,
        "manim_available": manim_available,
        "manim_version": manim_version,
        "artifacts_root": artifacts_path,
        "auth_configured": auth_is_configured(),
        "supabase_configured": db.supabase_enabled(),
        "storage_mode": _storage_mode(),
        "supabase_available": _supabase_available(),
        "database": _database_name(),
        "mongodb_configured": _mongo_configured(),
        "render_worker_configured": bool(settings.render_worker_url),
        "render_worker_ok": worker_ok,
        "render_worker_detail": worker_detail,
        "docling_local": docling_local,
        "docling_worker_configured": bool(settings.docling_worker_url),
        "docling_worker_ok": docling_ok,
        "docling_worker_detail": docling_detail,
        "document_extensions": sorted(SUPPORTED_EXTENSIONS),
    }


@app.get("/api/me")
async def me(user: CurrentUser) -> dict:
    """Current user profile + monthly LLM/storage usage."""
    try:
        await asyncio.to_thread(_prepare_user, user)
    except Exception:  # noqa: BLE001
        pass
    try:
        usage = await asyncio.to_thread(db.get_user_usage, user.id)
    except Exception:  # noqa: BLE001
        usage = None
    return {
        "user": {
            "id": user.id,
            "email": user.email,
            "name": user.name,
            "image": user.image,
        },
        "usage": usage,
        "supabase_configured": db.supabase_enabled(),
        "storage_mode": _storage_mode(),
        "supabase_available": _supabase_available(),
        "database": _database_name(),
        "mongodb_configured": _mongo_configured(),
        "artifacts_root": str(store.artifacts_root()),
    }


@app.put("/api/me/storage")
async def set_my_storage(request: StorageModeRequest, user: CurrentUser) -> dict:
    """Switch between local disk and Supabase for this server."""
    del user
    from backend.local_db import set_storage_mode

    get_settings()
    try:
        mode = await asyncio.to_thread(set_storage_mode, request.mode)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        "storage_mode": mode,
        "supabase_configured": db.supabase_enabled(),
        "supabase_available": _supabase_available(),
        "artifacts_root": str(store.artifacts_root()),
    }


@app.get("/api/tts/preview")
def preview_tts(voice: str, user: MediaUser) -> FileResponse:
    """Generate or return a cached audio preview for a specific voice."""
    try:
        _prepare_user(user)
        # Use a short standard phrase
        text = f"Hi, I am {voice}. Let's make learning click."
        previews_dir = store.artifacts_root() / "previews"
        previews_dir.mkdir(parents=True, exist_ok=True)
        # We don't know yet if it will be mp3 or wav, but synthesize_narration
        # will save it with the correct extension if we pass a base name.
        output_base = previews_dir / f"{voice}_preview"
        
        # Check if cache exists
        for ext in [".wav", ".mp3"]:
            if output_base.with_suffix(ext).exists():
                path = output_base.with_suffix(ext)
                media_type, _ = mimetypes.guess_type(str(path))
                return FileResponse(path, media_type=media_type or "application/octet-stream")
        
        # Generate new preview
        output_path, skipped = synthesize_narration(
            text=text,
            output_path=output_base.with_suffix(".wav"),
            voice=voice,
        )
        
        if skipped or not output_path:
            raise HTTPException(status_code=500, detail="TTS generation skipped or failed")
            
        path = Path(output_path)
        media_type, _ = mimetypes.guess_type(str(path))
        return FileResponse(path, media_type=media_type or "application/octet-stream")
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


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
        if request.scene_plan is None:
            db.reserve_generation(
                user.id,
                estimated_tokens=settings.default_llm_estimate_tokens,
            )
    except db.QuotaExceededError as exc:
        raise _quota_http(exc) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

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
    jobs = store.list_jobs(limit=limit, user_id=user.id)
    for job in jobs:
        job_id = str(job.get("job_id") or "")
        if not job_id:
            continue
        runtime = job_runner.job_status(job_id)
        if runtime.get("running"):
            job["status"] = "running"
        elif runtime.get("status"):
            job["status"] = runtime["status"]
    return {"jobs": jobs}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str, user: CurrentUser) -> dict:
    _require_job_owner(job_id, user.id)
    try:
        payload = store.load_job(job_id, user_id=user.id)
        payload["runtime"] = job_runner.job_status(job_id)
        return payload
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc


@app.post("/api/jobs/{job_id}/cancel")
def cancel_job(job_id: str, user: CurrentUser) -> dict:
    _require_job_owner(job_id, user.id)
    try:
        store.load_job(job_id, user_id=user.id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc
    job_runner.cancel_job(job_id)
    return {"ok": True, "job_id": job_id, "status": "cancelled"}


@app.get("/api/jobs/{job_id}/status")
def get_job_status(job_id: str, user: CurrentUser) -> dict:
    _require_job_owner(job_id, user.id)
    try:
        store.load_job(job_id, user_id=user.id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc
    return job_runner.job_status(job_id)


@app.put("/api/jobs/{job_id}/plan")
def put_scene_plan(
    job_id: str, body: UpdatePlanRequest, user: CurrentUser
) -> dict:
    """Save an edited storyboard before continuing generation."""
    _require_job_owner(job_id, user.id)
    plan = update_scene_plan(job_id, body.plan)
    return {"ok": True, "job_id": job_id, "plan": plan.model_dump()}


@app.patch("/api/jobs/{job_id}/scenes/{scene_id}")
def patch_scene(
    job_id: str, scene_id: str, body: PatchSceneRequest, user: CurrentUser
) -> dict:
    """Edit one scene's title, narration, beats, or visuals without rewriting the plan."""
    _require_job_owner(job_id, user.id)
    try:
        plan = patch_scene_section(
            job_id,
            scene_id,
            title=body.title,
            narration=body.narration,
            visual_description=body.visual_description,
            duration_seconds=body.duration_seconds,
            visual_device=body.visual_device,
            camera_notes=body.camera_notes,
            beats=(
                [beat.model_dump() for beat in body.beats]
                if body.beats is not None
                else None
            ),
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"ok": True, "job_id": job_id, "plan": plan.model_dump()}


@app.put("/api/jobs/{job_id}/settings")
def put_job_settings(
    job_id: str, body: JobSettingsRequest, user: CurrentUser
) -> dict:
    """Change narrator voice, language, audio, or subtitles after the storyboard."""
    _require_job_owner(job_id, user.id)
    try:
        store.load_job(job_id, user_id=user.id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc
    settings = update_job_settings(
        job_id,
        tts_voice=body.tts_voice,
        language=body.language,
        include_audio=body.include_audio,
        include_subtitles=body.include_subtitles,
    )
    return {"ok": True, **settings}


@app.get("/api/video/planning-spec")
def video_planning_spec(_user: CurrentUser) -> dict:
    """Constraints + ScenePlan schema for host-authored MCP storyboards."""
    return planning_spec_payload()


@app.get("/api/jobs/{job_id}/scenes/{scene_id}/codegen-spec")
def scene_codegen_spec(job_id: str, scene_id: str, user: CurrentUser) -> dict:
    """Manim codegen prompt pack for one scene (host LLM writes the code)."""
    _require_job_owner(job_id, user.id)
    try:
        return job_codegen_spec(job_id, scene_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProductionOptionsRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@app.put("/api/jobs/{job_id}/scenes/{scene_id}/code")
def put_scene_code(
    job_id: str, scene_id: str, body: SubmitSceneCodeRequest, user: CurrentUser
) -> dict:
    """Save host-authored Manim for a scene. Call continue with skip_codegen after all scenes."""
    _require_job_owner(job_id, user.id)
    try:
        return submit_host_scene_code(job_id, scene_id, body.code)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ProductionOptionsRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/jobs/{job_id}/plan/revise")
def revise_scene_plan_endpoint(
    job_id: str, body: RevisePlanRequest, user: CurrentUser
) -> dict:
    """AI-revise the storyboard: add/remove/rewrite scenes from a free-text
    instruction, before generation starts."""
    _require_job_owner(job_id, user.id)
    try:
        db.assert_within_quotas(user.id, need_tokens=6_000)
    except db.QuotaExceededError as exc:
        raise _quota_http(exc) from exc
    try:
        plan = revise_scene_plan(job_id, body.instructions)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {"ok": True, "job_id": job_id, "plan": plan.model_dump()}


@app.get("/api/jobs/{job_id}/events/stream")
async def job_events_stream(
    job_id: str,
    user: CurrentUser,
    after: int = 0,
) -> StreamingResponse:
    """SSE: attach to a job's durable event log (refresh / navigate safe)."""
    _require_job_owner(job_id, user.id)
    try:
        await asyncio.to_thread(store.load_job, job_id, user_id=user.id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc

    async def event_stream():
        async for chunk in aiter_job_event_stream(job_id, after=max(0, after)):
            yield chunk

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/jobs/{job_id}/continue/stream")
async def continue_stream(
    job_id: str,
    user: CurrentUser,
    body: ContinueRequest = Body(default_factory=ContinueRequest),
) -> StreamingResponse:
    """SSE: continue a plan_only job after the user confirms the storyboard."""
    _require_job_owner(job_id, user.id)
    try:
        prepare_production_options(job_id, body)
    except ProductionOptionsRequired as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    skip_quota = body.skip_codegen or job_is_host_authored(job_id)
    if not skip_quota:
        try:
            await asyncio.to_thread(db.assert_within_quotas, user.id, need_tokens=20_000)
        except db.QuotaExceededError as exc:
            raise _quota_http(exc) from exc

    async def event_stream():
        try:
            async for chunk in aiter_continue_events(
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
    _require_scene_free(job_id, scene_id)
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


@app.get("/api/jobs/{job_id}/marks")
def get_video_marks(job_id: str, user: CurrentUser) -> dict:
    _require_job_owner(job_id, user.id)
    try:
        store.load_job(job_id, user_id=user.id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc
    timeline = store.job_timeline(job_id)
    return {
        "marks": store.list_job_marks(job_id, timeline=timeline),
        "timeline": timeline,
    }


@app.post("/api/jobs/{job_id}/marks", response_model=SceneComment)
def add_video_mark(
    job_id: str, body: VideoMarkRequest, user: CurrentUser
) -> SceneComment:
    """Mark the current video frame, attach a comment, and map it onto a scene."""
    _require_job_owner(job_id, user.id)
    author = user.name or user.email or "User"
    try:
        comment_data = store.add_video_mark(
            job_id,
            comment=body.comment,
            author=author,
            scene_id=body.scene_id,
            timestamp=body.timestamp,
            global_timestamp=body.global_timestamp,
            frame_base64=body.frame_base64,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return SceneComment(**comment_data)


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
        global_timestamp=body.global_timestamp,
        frame_base64=body.frame_base64,
        author=author,
    )
    return SceneComment(**comment_data)


@app.post("/api/jobs/{job_id}/scenes/{scene_id}/retouch/stream")
def retouch_scene_stream(
    job_id: str, scene_id: str, body: SceneCommentRequest, user: CurrentUser
) -> StreamingResponse:
    """SSE stream: AI reads the comment, revises code, and re-renders the scene."""
    _require_job_owner(job_id, user.id)
    _require_scene_free(job_id, scene_id)
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
                comment_id=body.comment_id,
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
    _require_scene_free(job_id, scene_id)
    try:
        return approve_scene(job_id, scene_id)
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


# ── Interactive Scene Editor ──────────────────────────────────────────────


@app.get("/api/jobs/{job_id}/scenes/{scene_id}/elements")
def get_scene_elements(job_id: str, scene_id: str, user: CurrentUser) -> dict:
    """Parse the scene's final Manim code and return a JSON scene graph."""
    _require_job_owner(job_id, user.id)
    sdir = store.scene_dir(job_id, scene_id)
    code_path = sdir / "code_final.py"
    if not code_path.exists():
        raise HTTPException(status_code=404, detail="No code found for this scene")
    code = code_path.read_text(encoding="utf-8")

    from backend.pipeline.scene_parser import parse_scene_code

    elements = parse_scene_code(code)
    return {"elements": elements, "scene_id": scene_id, "job_id": job_id}


@app.put("/api/jobs/{job_id}/scenes/{scene_id}/elements")
def save_scene_elements(
    job_id: str, scene_id: str, body: dict, user: CurrentUser
) -> dict:
    """Save user-edited element properties (position, color, size, text)."""
    _require_job_owner(job_id, user.id)
    edits = body.get("edits", [])
    if not edits:
        raise HTTPException(status_code=400, detail="No edits provided")

    sdir = store.scene_dir(job_id, scene_id)
    # Persist the edits for apply-edits to consume
    store.write_json(sdir / "pending_edits.json", edits)
    return {"ok": True, "scene_id": scene_id, "edit_count": len(edits)}


@app.post("/api/jobs/{job_id}/scenes/{scene_id}/apply-edits")
def apply_scene_edits(
    job_id: str, scene_id: str, body: dict, user: CurrentUser
) -> dict:
    """Apply element edits to the Manim code and re-render the scene video."""
    _require_job_owner(job_id, user.id)
    _require_scene_free(job_id, scene_id)
    sdir = store.scene_dir(job_id, scene_id)
    code_path = sdir / "code_final.py"
    if not code_path.exists():
        raise HTTPException(status_code=404, detail="No code found for this scene")

    # Get edits from body or pending file
    edits = body.get("edits", [])
    if not edits:
        edits_path = sdir / "pending_edits.json"
        if edits_path.exists():
            import json as _json

            edits = _json.loads(edits_path.read_text(encoding="utf-8"))

    if not edits:
        raise HTTPException(status_code=400, detail="No edits to apply")

    from backend.pipeline.scene_patcher import apply_element_edits
    from backend.pipeline.scene_parser import parse_scene_code

    video_url = None
    render_log = ""
    settings = get_settings()
    # Hold this scene only: patching code, numbering the revision, and
    # publishing the clip must not interleave with a retouch/regenerate of the
    # same scene. Other scenes are untouched and stay editable in parallel.
    try:
        scene_guard = job_runner.scene_lock(job_id, scene_id, timeout=30)
    except job_runner.SceneBusyError as exc:  # pragma: no cover - guarded above
        raise HTTPException(status_code=409, detail=str(exc)) from exc

    with scene_guard:
        code = code_path.read_text(encoding="utf-8")
        updated_code = apply_element_edits(code, edits)

        # Save the patched code
        code_path.write_text(updated_code, encoding="utf-8")

        # Also save a revision copy
        import glob

        existing = glob.glob(str(sdir / "code_r*.py"))
        next_rev = len(existing) + 1
        (sdir / f"code_r{next_rev}.py").write_text(updated_code, encoding="utf-8")

        # Clean up pending edits
        (sdir / "pending_edits.json").unlink(missing_ok=True)

        # Re-render if Manim is available
        if settings.enable_manim_render or settings.render_worker_url:
            from backend.pipeline.renderer import render_scene, make_job_dir

            work_dir = make_job_dir(job_id)
            video_path, frame_path, render_log = render_scene(
                updated_code,
                work_dir=work_dir,
                resolution="720p",
                scene_id=scene_id,
            )
            if video_path:
                video_url = store.publish_scene_video(job_id, scene_id, video_path)

    # Re-parse elements from the patched code for the frontend
    new_elements = parse_scene_code(updated_code)

    return {
        "ok": True,
        "scene_id": scene_id,
        "video_url": video_url,
        "elements": new_elements,
        "render_log": render_log[-500:] if render_log else None,
    }


@app.get("/api/documents")
def list_documents(user: CurrentUser, limit: int = 50) -> dict:
    _prepare_user(user)
    return {"documents": doc_store.list_documents(user_id=user.id, limit=limit)}


@app.get("/api/documents/{doc_id}")
def get_document(doc_id: str, user: CurrentUser) -> dict:
    _require_job_owner(doc_id, user.id)
    try:
        return load_document(doc_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}") from exc


@app.delete("/api/documents/{doc_id}")
def delete_document_endpoint(doc_id: str, user: CurrentUser) -> dict:
    """Permanently delete a converted document and its artifacts."""
    try:
        root = store.artifacts_root() / doc_id
        if root.exists():
            _require_job_owner(doc_id, user.id)
        # If local artifacts are already gone, still clear the remote job row
        # (scoped by user_id inside delete_job RPC).
        doc_store.delete_document(doc_id, user_id=user.id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}") from exc
    except PermissionError as exc:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}") from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(
            status_code=500,
            detail=f"Failed to delete document: {exc}",
        ) from exc
    return {"ok": True, "doc_id": doc_id}


@app.get("/api/documents/{doc_id}/annotations")
def get_document_annotations(
    doc_id: str,
    user: CurrentUser,
    slide_id: Optional[str] = None,
) -> dict:
    _require_job_owner(doc_id, user.id)
    if slide_id:
        return {
            "annotations": doc_store.list_slide_comments(doc_id, slide_id),
        }
    return {"annotations": doc_store.list_annotations(doc_id)}


@app.post(
    "/api/documents/{doc_id}/comments",
    response_model=DocumentAnnotation,
)
def save_document_comment(
    doc_id: str, body: DocumentCommentRequest, user: CurrentUser
) -> DocumentAnnotation:
    """Save an LLM answer (or note) as a comment on a specific slide."""
    _require_job_owner(doc_id, user.id)
    try:
        manifest = doc_store.load_manifest(doc_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}") from exc
    if body.slide_id not in {s.id for s in manifest.slides}:
        raise HTTPException(status_code=400, detail=f"Unknown slide_id: {body.slide_id}")
    author = body.author or (user.name or user.email or "user")
    return doc_store.add_annotation(
        doc_id,
        slide_id=body.slide_id,
        block_id=body.block_id,
        action=body.action,
        message=body.message,
        reply=body.reply,
        author=author,
        pinned=True,
    )


@app.delete("/api/documents/{doc_id}/comments/{comment_id}")
def delete_document_comment(
    doc_id: str, comment_id: str, user: CurrentUser
) -> dict:
    _require_job_owner(doc_id, user.id)
    ok = doc_store.delete_annotation(doc_id, comment_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Comment not found")
    return {"ok": True, "comment_id": comment_id}


@app.post("/api/documents/upload")
async def upload_document(
    user: CurrentUser,
    file: UploadFile = File(...),
) -> dict:
    """Upload a PDF/PPTX/DOCX/… and convert to interactive HTML slides."""
    settings = get_settings()
    filename = file.filename or "document.bin"
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'. Supported: {', '.join(sorted(SUPPORTED_EXTENSIONS))}",
        )
    try:
        _prepare_user(user)
        db.reserve_generation(
            user.id,
            estimated_tokens=settings.default_llm_estimate_tokens,
        )
    except db.QuotaExceededError as exc:
        raise _quota_http(exc) from exc

    suffix = ext or ".bin"
    tmp_path: Optional[Path] = None
    try:
        with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
            tmp_path = Path(tmp.name)
            tmp.write(await file.read())
        manifest = await asyncio.to_thread(
            run_document_ingest,
            tmp_path,
            original_filename=filename,
            user_id=user.id,
            user_email=user.email,
            user_name=user.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        if tmp_path is not None:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

    return {
        "doc_id": manifest.doc_id,
        "title": manifest.title,
        "slide_count": manifest.slide_count,
        "status": manifest.status,
        "manifest": manifest.model_dump(),
    }


@app.post("/api/documents/upload/stream")
async def upload_document_stream(
    user: CurrentUser,
    file: UploadFile = File(...),
) -> StreamingResponse:
    settings = get_settings()
    filename = file.filename or "document.bin"
    ext = Path(filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"Unsupported file type '{ext}'",
        )
    try:
        _prepare_user(user)
        db.reserve_generation(
            user.id,
            estimated_tokens=settings.default_llm_estimate_tokens,
        )
    except db.QuotaExceededError as exc:
        raise _quota_http(exc) from exc

    suffix = ext or ".bin"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp:
        tmp_path = Path(tmp.name)
        tmp.write(await file.read())

    def event_stream():
        try:
            for chunk in iter_document_ingest_events(
                tmp_path,
                original_filename=filename,
                user_id=user.id,
                user_email=user.email,
                user_name=user.name,
            ):
                yield chunk
        finally:
            try:
                tmp_path.unlink(missing_ok=True)
            except Exception:  # noqa: BLE001
                pass

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.post("/api/source/extract")
async def extract_source_upload(
    user: CurrentUser,
    file: UploadFile = File(...),
) -> dict:
    """Extract plain text from an upload for video / Learn generation."""
    filename = file.filename or "upload.bin"
    try:
        _prepare_user(user)
        data = await file.read()
        return await asyncio.to_thread(
            extract_upload,
            data,
            filename=filename,
            user_id=user.id,
            user_email=user.email,
            user_name=user.name,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.get("/api/source/library")
def source_library(user: CurrentUser, limit: int = 30) -> dict:
    _prepare_user(user)
    return {"items": list_library_sources(user_id=user.id, limit=limit)}


@app.post("/api/learn/generate")
def learn_generate(request: LearnGenerateRequest, user: CurrentUser) -> dict:
    settings = get_settings()
    try:
        _prepare_user(user)
        db.reserve_generation(
            user.id,
            estimated_tokens=settings.default_llm_estimate_tokens,
        )
        return run_learn(
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


@app.post("/api/learn/generate/stream")
def learn_generate_stream(
    request: LearnGenerateRequest, user: CurrentUser
) -> StreamingResponse:
    settings = get_settings()
    try:
        _prepare_user(user)
        db.reserve_generation(
            user.id,
            estimated_tokens=settings.default_llm_estimate_tokens,
        )
    except db.QuotaExceededError as exc:
        raise _quota_http(exc) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc

    def event_stream():
        try:
            for chunk in iter_learn_events(
                request,
                user_id=user.id,
                user_email=user.email,
                user_name=user.name,
            ):
                yield chunk
        except db.QuotaExceededError as exc:
            import json as _json

            yield (
                "data: "
                + _json.dumps(
                    {
                        "type": "error",
                        "message": exc.detail,
                        "data": {"code": exc.code},
                    }
                )
                + "\n\n"
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-transform",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@app.get("/api/learn/{item_id}")
def get_learn_item(item_id: str, user: CurrentUser) -> dict:
    _require_job_owner(item_id, user.id)
    try:
        return load_learn_item(item_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {item_id}") from exc


@app.post("/api/learn/{item_id}/grade")
def grade_learn_quiz(
    item_id: str, body: QuizGradeRequest, user: CurrentUser
) -> dict:
    _require_job_owner(item_id, user.id)
    try:
        return grade_quiz_item(item_id, body).model_dump()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {item_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post("/api/learn/{item_id}/progress")
def learn_lab_progress(
    item_id: str, body: LabProgressRequest, user: CurrentUser
) -> dict:
    _require_job_owner(item_id, user.id)
    try:
        return check_lab_progress(item_id, body).model_dump()
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Not found: {item_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@app.post(
    "/api/documents/{doc_id}/ask",
    response_model=DocumentAskResult,
)
async def ask_document(
    doc_id: str, body: DocumentAskRequest, user: CurrentUser
) -> DocumentAskResult:
    _require_job_owner(doc_id, user.id)
    try:
        db.assert_within_quotas(user.id, need_tokens=4_000)
    except db.QuotaExceededError as exc:
        raise _quota_http(exc) from exc
    try:
        return await asyncio.to_thread(
            ask_document_block,
            doc_id,
            body,
            user_id=user.id,
        )
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Document not found: {doc_id}") from exc
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
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
        "Cross-Origin-Resource-Policy": "cross-origin",
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
