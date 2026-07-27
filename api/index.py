"""FastAPI entrypoint for Vercel (Python runtime) and local uvicorn."""

from __future__ import annotations

import asyncio
import mimetypes
import sys
import tempfile
from pathlib import Path

from fastapi import FastAPI, File, HTTPException, UploadFile
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
    run_pipeline,
    update_scene_plan,
)
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

    docling_ok: bool | None = None
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
    # Run sync Supabase I/O off the event loop so usage stays responsive
    # even while generation SSE streams are open.
    await asyncio.to_thread(_prepare_user, user)
    usage = await asyncio.to_thread(db.get_user_usage, user.id)
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
        payload = store.load_job(job_id, user_id=user.id)
        payload["runtime"] = job_runner.job_status(job_id)
        return payload
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc


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
    body: ContinueRequest = ContinueRequest(),
) -> StreamingResponse:
    """SSE: continue a plan_only job after the user confirms the storyboard."""
    _require_job_owner(job_id, user.id)
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
    slide_id: str | None = None,
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
    tmp_path: Path | None = None
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
