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
from backend.config import get_settings
from backend.pipeline.orchestrator import iter_pipeline_events, run_pipeline
from backend.schemas import GenerateRequest, GenerateResult

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
    return {
        "ok": True,
        "model": settings.openrouter_model,
        "vlm_model": settings.openrouter_vlm_model,
        "openrouter_configured": bool(settings.openrouter_api_key),
        "tts_configured": bool(settings.tts_api_key),
        "manim_render_enabled": settings.enable_manim_render,
        "manim_available": manim_available,
        "manim_version": manim_version,
        "artifacts_root": str(store.artifacts_root()),
    }


@app.post("/api/generate", response_model=GenerateResult)
def generate(request: GenerateRequest) -> GenerateResult:
    """Run the full pipeline and return the final result."""
    try:
        return run_pipeline(request)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@app.post("/api/generate/stream")
def generate_stream(request: GenerateRequest) -> StreamingResponse:
    """SSE stream of pipeline events for live UI progress."""

    def event_stream():
        for chunk in iter_pipeline_events(request):
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


@app.get("/api/jobs")
def list_jobs(limit: int = 50) -> dict:
    return {"jobs": store.list_jobs(limit=limit)}


@app.get("/api/jobs/{job_id}")
def get_job(job_id: str) -> dict:
    try:
        return store.load_job(job_id)
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=f"Job not found: {job_id}") from exc


@app.get("/api/jobs/{job_id}/file/{file_path:path}")
def get_job_file(job_id: str, file_path: str) -> FileResponse:
    try:
        path = store.resolve_job_file(job_id, file_path)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except FileNotFoundError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc

    media_type, _ = mimetypes.guess_type(str(path))
    return FileResponse(path, media_type=media_type or "application/octet-stream")


@app.get("/")
def root() -> dict:
    return {
        "service": "NowIGetIt API",
        "docs": "/docs",
        "health": "/api/health",
        "jobs": "/api/jobs",
    }
