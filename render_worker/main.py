"""Railway Manim render worker — Manim Community Edition + ffmpeg."""

from __future__ import annotations

import base64
import os
import secrets
import sys
import tempfile
from pathlib import Path

from typing import Optional

from fastapi import FastAPI, Header, HTTPException
from pydantic import BaseModel, Field

ROOT = Path(__file__).resolve().parent.parent
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

# Force-enable local Manim inside the worker container.
os.environ.setdefault("ENABLE_MANIM_RENDER", "true")
os.environ.setdefault("RENDER_WORKER_MODE", "true")
# Never call ourselves as a remote worker.
os.environ.pop("RENDER_WORKER_URL", None)

app = FastAPI(title="NowIGetIt Render Worker", version="0.1.0")


class RenderRequest(BaseModel):
    code: str = Field(..., min_length=10)
    resolution: str = Field(default="720p", pattern="^(480p|720p|1080p)$")
    scene_id: str = Field(default="scene", min_length=1, max_length=120)
    job_id: Optional[str] = None
    save_last_frame: bool = False


class RenderResponse(BaseModel):
    ok: bool
    video_base64: Optional[str] = None
    frame_base64: Optional[str] = None
    log: str = ""
    error: Optional[str] = None


def _check_secret(authorization: Optional[str]) -> None:
    expected = (os.getenv("RENDER_WORKER_SECRET") or "").strip()
    if not expected:
        return  # open worker (local/dev only)
    if not authorization or not authorization.lower().startswith("bearer "):
        raise HTTPException(status_code=401, detail="Missing bearer token")
    token = authorization.split(" ", 1)[1].strip()
    if not secrets.compare_digest(token, expected):
        raise HTTPException(status_code=401, detail="Invalid token")


@app.get("/health")
def health() -> dict:
    manim_ok = False
    manim_version = None
    try:
        import manim

        manim_ok = True
        manim_version = getattr(manim, "__version__", "unknown")
    except ImportError:
        pass
    return {
        "ok": True,
        "service": "nowigetit-render-worker",
        "manim_available": manim_ok,
        "manim_version": manim_version,
        "ffmpeg": bool(__import__("shutil").which("ffmpeg")),
        "enable_manim_render": os.getenv("ENABLE_MANIM_RENDER", ""),
        "render_worker_mode": os.getenv("RENDER_WORKER_MODE", ""),
    }


@app.post("/render", response_model=RenderResponse)
def render(
    body: RenderRequest,
    authorization: Optional[str] = Header(default=None),
) -> RenderResponse:
    _check_secret(authorization)

    # Lazy import so /health can pass before Manim/renderer load.
    from backend.pipeline.renderer import render_scene

    work = Path(tempfile.mkdtemp(prefix="nig-render-"))
    try:
        video_path, frame_path, log = render_scene(
            body.code,
            work_dir=work,
            resolution=body.resolution,
            scene_id=body.scene_id,
            save_last_frame=body.save_last_frame,
        )
        frame_b64 = None
        if frame_path and Path(frame_path).exists():
            frame_b64 = base64.b64encode(Path(frame_path).read_bytes()).decode("ascii")

        if body.save_last_frame:
            if not frame_b64:
                return RenderResponse(
                    ok=False,
                    log=log,
                    error=log[-2000:] if log else "No preview frame produced",
                )
            return RenderResponse(ok=True, frame_base64=frame_b64, log=log)

        if not video_path:
            return RenderResponse(ok=False, log=log, error=log[-2000:] if log else "Render failed")

        video_b64 = base64.b64encode(Path(video_path).read_bytes()).decode("ascii")
        return RenderResponse(
            ok=True,
            video_base64=video_b64,
            frame_base64=frame_b64,
            log=log,
        )
    except Exception as exc:  # noqa: BLE001
        raise HTTPException(status_code=500, detail=str(exc)) from exc
    finally:
        try:
            import shutil

            shutil.rmtree(work, ignore_errors=True)
        except Exception:  # noqa: BLE001
            pass
