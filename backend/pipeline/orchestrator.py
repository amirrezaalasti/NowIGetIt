"""End-to-end generation pipeline with step events and durable artifacts."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Optional

from backend import artifacts as store
from backend.code_utils import validate_manim_code
from backend.config import get_settings
from backend.llm import OpenRouterClient
from backend.pipeline.compose import compose_final_video, mux_scene_audio
from backend.pipeline.planner import create_scene_plan
from backend.pipeline.renderer import render_scene
from backend.pipeline.scene_generator import generate_scene_code, revise_scene_code
from backend.pipeline.storyboard import create_storyboard_frame
from backend.pipeline.tts import synthesize_narration
from backend.pipeline.visual_preview import create_visual_preview
from backend.pipeline.vlm_review import final_debug_pass, review_scene
from backend.schemas import (
    GenerateRequest,
    GenerateResult,
    PipelineEvent,
    PipelineEventType,
    SceneArtifact,
    ScenePlan,
    SceneSection,
)

EventCallback = Callable[[PipelineEvent], None]


def _slim_data(data: Optional[dict]) -> Optional[dict]:
    """Keep live stream payloads small so the UI updates immediately."""
    if not data:
        return data
    slim: dict = {}
    # Drop bulky blobs; keep lightweight scene summaries for the UI.
    drop = {"code", "plan", "vlm_reviews", "section", "animation_beats"}
    for key, value in data.items():
        if key in drop:
            continue
        if key == "note" and isinstance(value, str) and len(value) > 280:
            slim[key] = value[:280] + "…"
            continue
        if key == "scenes" and isinstance(value, list):
            # Plan / complete events: only send what the UI needs
            slim[key] = [
                {
                    "id": s.get("id") or s.get("scene_id"),
                    "scene_id": s.get("scene_id") or s.get("id"),
                    "title": s.get("title"),
                    "narration": (s.get("narration") or "")[:220],
                    "video_url": s.get("video_url"),
                    "frame_url": s.get("frame_url"),
                    "vlm_approved": s.get("vlm_approved"),
                }
                for s in value
                if isinstance(s, dict)
            ]
            continue
        slim[key] = value
    return slim


def _emit(
    callback: Optional[EventCallback],
    event_type: PipelineEventType,
    message: str,
    data: Optional[dict] = None,
    *,
    job_id: Optional[str] = None,
) -> PipelineEvent:
    live_data = _slim_data(data)
    event = PipelineEvent(type=event_type, message=message, data=live_data)
    if job_id:
        # Persist fuller data server-side when useful; stream stays slim.
        store.append_event(
            job_id,
            {
                "type": event.type.value,
                "message": event.message,
                "data": live_data,
            },
        )
    if callback:
        callback(event)
    return event


def run_pipeline(
    request: GenerateRequest,
    *,
    on_event: Optional[EventCallback] = None,
) -> GenerateResult:
    """
    Pipeline:
      1) Prompt → JSON scene plan (saved)
      2) For each scene: generate code → render/storyboard → VLM check → revise → TTS
      3) Final model debug pass
    All plans, frames the VLM saw, and reviews are persisted under artifacts/{job_id}/.
    """
    settings = get_settings()
    client = OpenRouterClient(settings)
    job_id = uuid.uuid4().hex[:12]
    work_dir = store.init_job(
        job_id,
        prompt=request.prompt,
        settings_snapshot={
            "model": settings.openrouter_model,
            "vlm_model": settings.openrouter_vlm_model,
            "enable_manim_render": settings.enable_manim_render,
            "max_scene_revisions": settings.max_scene_revisions,
            "resolution": request.resolution,
            "skip_render": request.skip_render,
        },
    )

    _emit(
        on_event,
        PipelineEventType.status,
        f"Planning scenes from prompt… (job {job_id})",
        data={"job_id": job_id},
        job_id=job_id,
    )
    plan = create_scene_plan(client, request.prompt)
    plan_path = store.save_scene_plan(job_id, plan.model_dump())
    _emit(
        on_event,
        PipelineEventType.plan,
        f"Planned {len(plan.scenes)} scenes: {plan.title}",
        data={
            **plan.model_dump(),
            "job_id": job_id,
            "scene_plan_url": f"/api/jobs/{job_id}/file/scene_plan.json",
            "saved_path": plan_path,
        },
        job_id=job_id,
    )

    artifacts: list[SceneArtifact] = []
    previous_context = ""

    for index, scene in enumerate(plan.scenes):
        store.save_scene_section(job_id, scene.id, scene.model_dump())
        _emit(
            on_event,
            PipelineEventType.scene_start,
            f"Scene {index + 1}/{len(plan.scenes)}: {scene.title}",
            data={"scene_id": scene.id, "index": index, "job_id": job_id},
            job_id=job_id,
        )

        code = generate_scene_code(
            client, plan=plan, scene=scene, previous_context=previous_context
        )
        store.save_code(job_id, scene.id, code, revision=0)
        _emit(
            on_event,
            PipelineEventType.scene_code,
            f"Generated Manim code for {scene.id}",
            data={"scene_id": scene.id, "code_chars": len(code), "job_id": job_id},
            job_id=job_id,
        )

        # Single pass execution (automated revision deactivated in favor of human scene feedback)
        sdir = store.scene_dir(job_id, scene.id)
        video_path = None
        video_url = None
        frame_path = None
        frame_source = "none"
        frame_urls: list[str] = []
        reviews_log: list[dict] = []
        revision_count = 0

        if not request.skip_render:
            video_path, frame_path, render_log = render_scene(
                code,
                work_dir=work_dir / "render",
                resolution=request.resolution,
                scene_id=f"{scene.id}_r{revision_count}",
            )
            
            while not video_path and revision_count < settings.max_scene_revisions:
                revision_count += 1
                _emit(
                    on_event,
                    PipelineEventType.status,
                    f"Render failed, revising code for {scene.id} (attempt {revision_count})…",
                    data={"scene_id": scene.id, "job_id": job_id},
                    job_id=job_id,
                )
                
                rev_instructions = f"Manim render failed with error:\n{render_log[-500:] if render_log else 'Unknown error'}\nPlease fix the code so it renders successfully."
                code = revise_scene_code(
                    client,
                    code=code,
                    scene=scene,
                    revision_instructions=rev_instructions,
                )
                store.save_code(job_id, scene.id, code, revision=revision_count)
                
                video_path, frame_path, render_log = render_scene(
                    code,
                    work_dir=work_dir / "render",
                    resolution=request.resolution,
                    scene_id=f"{scene.id}_r{revision_count}",
                )

            preview_note = None if video_path else render_log
            if frame_path:
                frame_source = "manim_preview"
            if video_path:
                video_url = store.publish_scene_video(
                    job_id, scene.id, video_path
                )
            _emit(
                on_event,
                PipelineEventType.scene_render,
                f"Render step for {scene.id}"
                + (" · video ready" if video_url else " · render failed"),
                data={
                    "scene_id": scene.id,
                    "video_url": video_url,
                    "ok": bool(video_path),
                    "note": preview_note,
                    "job_id": job_id,
                },
                job_id=job_id,
            )
        else:
            preview_note = "Render skipped by request."

        if not frame_path:
            sdir = store.scene_dir(job_id, scene.id)
            create_storyboard_frame(
                scene,
                output_path=sdir / "vlm_r0_plan_card.png",
            )
            frame_path = create_visual_preview(
                scene,
                output_path=sdir / "vlm_r0_preview.png",
            )
            frame_source = "visual_preview"

        syntax_ok, syntax_err = validate_manim_code(code)
        use_image_vlm = frame_source == "manim_preview"
        review = review_scene(
            client,
            scene=scene,
            code=code,
            frame_path=frame_path if use_image_vlm else None,
            frame_source=frame_source if use_image_vlm else "visual_preview",
        )
        if not syntax_ok:
            review = review.model_copy(
                update={
                    "approved": False,
                    "issues": [syntax_err, *review.issues],
                    "revision_instructions": f"Fix invalid Python ({syntax_err}).",
                }
            )

        saved = store.save_vlm_review(
            job_id,
            scene.id,
            revision=0,
            review=review.model_dump(),
            frame_path=frame_path,
            frame_source=frame_source,
        )
        approved = review.approved
        issues = review.issues
        if saved.get("frame_url"):
            frame_urls.append(saved["frame_url"])
        reviews_log.append(
            {
                **review.model_dump(),
                "revision": 0,
                "frame_source": frame_source,
                "frame_url": saved.get("frame_url"),
                "review_mode": (
                    "image_vlm"
                    if frame_source == "manim_preview"
                    else "code_only"
                ),
            }
        )
        _emit(
            on_event,
            PipelineEventType.scene_vlm,
            f"Initial scene check for {scene.id}",
            data={
                **review.model_dump(),
                "scene_id": scene.id,
                "job_id": job_id,
                "frame_url": saved.get("frame_url"),
                "frame_source": frame_source,
                "revision": 0,
            },
            job_id=job_id,
        )

        audio_path, audio_skipped = synthesize_narration(
            scene.narration,
            work_dir / "audio" / f"{scene.id}.mp3",
            settings=settings,
        )
        if audio_path and Path(audio_path).exists():
            import shutil
            shutil.copy2(audio_path, sdir / "audio.mp3")
        _emit(
            on_event,
            PipelineEventType.scene_tts,
            f"TTS for {scene.id}"
            + (" (skipped — no TTS_API_KEY)" if audio_skipped else ""),
            data={
                "scene_id": scene.id,
                "audio_path": audio_path,
                "skipped": audio_skipped,
                "job_id": job_id,
            },
            job_id=job_id,
        )

        # Prefer the published artifact copy for serving
        if video_path and not video_url:
            video_url = store.publish_scene_video(job_id, scene.id, video_path)

        artifact = SceneArtifact(
            scene_id=scene.id,
            title=scene.title,
            narration=scene.narration,
            code=code,
            revision_count=revision_count,
            vlm_approved=approved,
            vlm_issues=issues,
            video_path=video_path,
            video_url=video_url,
            preview_note=preview_note,
            audio_path=audio_path,
            audio_skipped=audio_skipped,
            vlm_frame_urls=frame_urls,
            vlm_reviews=reviews_log,
            artifact_dir=str(store.scene_dir(job_id, scene.id)),
        )
        artifacts.append(artifact)
        previous_context += (
            f"\n- {scene.id}: {scene.title} — {scene.visual_description[:180]}"
        )
        _emit(
            on_event,
            PipelineEventType.scene_done,
            f"Completed {scene.id}",
            data={
                "scene_id": scene.id,
                "title": scene.title,
                "job_id": job_id,
                "video_url": video_url,
                "frame_url": frame_urls[-1] if frame_urls else None,
                "vlm_approved": approved,
                "revision_count": revision_count,
            },
            job_id=job_id,
        )

    scene_summaries = "\n\n".join(
        (
            f"[{a.scene_id}] {a.title}\n"
            f"approved={a.vlm_approved} revisions={a.revision_count}\n"
            f"issues={a.vlm_issues}\n"
            f"code:\n{a.code[:2500]}"
        )
        for a in artifacts
    )
    # Automated VLM revisions disabled in favor of human review
    debug = {"notes": "Automated VLM revisions disabled (human-in-the-loop review active)", "scene_fixes": []}
    store.save_final_debug(job_id, debug)
    notes = str(debug.get("notes", ""))
    _emit(
        on_event,
        PipelineEventType.final_debug,
        "Automated VLM revision pass skipped (human review mode active)",
        data={**debug, "job_id": job_id},
        job_id=job_id,
    )

    # Mux narration onto each scene clip, then stitch into final.mp4
    _emit(
        on_event,
        PipelineEventType.status,
        "Composing final video…",
        data={"job_id": job_id},
        job_id=job_id,
    )
    muxed_clips: list[str] = []
    for art in artifacts:
        if not art.video_path:
            continue
        muxed = mux_scene_audio(
            art.video_path,
            art.audio_path,
            store.scene_dir(job_id, art.scene_id) / "scene_vo.mp4",
        )
        if muxed:
            muxed_clips.append(muxed)
            # Prefer VO-muxed clip for playback URL
            art.video_url = store.publish_scene_video(
                job_id, art.scene_id, muxed
            )

    final_path = compose_final_video(
        muxed_clips,
        store.job_dir(job_id) / "final.mp4",
    )
    final_url = (
        f"/api/jobs/{job_id}/file/final.mp4" if final_path else None
    )

    result = GenerateResult(
        title=plan.title,
        plan=plan,
        scenes=artifacts,
        final_debug_notes=notes,
        final_video_path=final_path,
        final_video_url=final_url,
        render_enabled=settings.enable_manim_render and not request.skip_render,
        job_id=job_id,
        artifact_url=f"/api/jobs/{job_id}",
        scene_plan_url=f"/api/jobs/{job_id}/file/scene_plan.json",
    )
    store.save_result(job_id, result.model_dump())
    _emit(
        on_event,
        PipelineEventType.complete,
        "Pipeline finished",
        data={
            "job_id": job_id,
            "title": plan.title,
            "final_video_url": final_url,
            "artifact_url": result.artifact_url,
            "scene_count": len(artifacts),
            "scenes": [
                {
                    "scene_id": a.scene_id,
                    "title": a.title,
                    "video_url": a.video_url,
                    "frame_url": a.vlm_frame_urls[-1] if a.vlm_frame_urls else None,
                    "vlm_approved": a.vlm_approved,
                }
                for a in artifacts
            ],
        },
        job_id=job_id,
    )
    return result


def retouch_scene(job_id: str, scene_id: str, human_instructions: str, timestamp: Optional[float] = None, on_event: Optional[Any] = None) -> dict[str, Any]:
    """Retouch/revise ONLY a specific scene based on human feedback."""
    settings = get_settings()
    client = OpenRouterClient(settings=settings)

    def emit(msg: str, data: Optional[dict] = None) -> None:
        if on_event:
            on_event(PipelineEvent(type=PipelineEventType.status, message=msg, data=data or {}))

    emit(f"Loading scene data for '{scene_id}'…", {"scene_id": scene_id, "job_id": job_id})

    job_data = store.load_job(job_id)
    scenes = job_data.get("scenes") or []
    match_scene = next((s for s in scenes if s["scene_id"] == scene_id), None)
    if not match_scene:
        raise ValueError(f"Scene {scene_id} not found in job {job_id}")

    section_data = match_scene.get("section") or {}
    scene_sec = SceneSection(
        id=scene_id,
        title=section_data.get("title", scene_id),
        narration=section_data.get("narration", ""),
        visual_description=section_data.get("visual_description", ""),
        animation_beats=section_data.get("animation_beats", []),
    )

    current_code = match_scene.get("code_final", "")
    rev_instructions = human_instructions
    if timestamp is not None:
        rev_instructions = f"[At timestamp {timestamp:.1f}s]: {human_instructions}"

    emit(
        f"AI is reading your feedback and revising the Manim code for '{scene_sec.title}'…",
        {"scene_id": scene_id, "instructions": rev_instructions},
    )

    retry_count = 0
    max_retries = settings.max_scene_revisions

    new_code = revise_scene_code(
        client,
        code=current_code,
        scene=scene_sec,
        revision_instructions=rev_instructions,
    )

    ok, err = validate_manim_code(new_code)
    while not ok and retry_count < max_retries:
        retry_count += 1
        emit(f"Syntax error in revised code: {err} — retrying ({retry_count}/{max_retries}).", {"error": err})
        new_code = revise_scene_code(
            client,
            code=new_code,
            scene=scene_sec,
            revision_instructions=f"Previous revision had a syntax error:\n{err}\nPlease fix it.",
        )
        ok, err = validate_manim_code(new_code)

    if not ok:
        emit(f"Syntax error in revised code: {err} — aborting.", {"error": err})
        raise ValueError(f"Generated retouched code invalid: {err}")

    emit("Code revision complete. Saving new code…", {"code_chars": len(new_code)})

    # Calculate next revision number
    sdir = store.scene_dir(job_id, scene_id)
    rev_count = len(list(sdir.glob("code_r*.py")))
    store.save_code(job_id, scene_id, new_code, revision=rev_count)

    emit(f"Rendering scene '{scene_sec.title}' (revision {rev_count})…", {"revision": rev_count})

    work_dir = store.job_dir(job_id) / "work"
    video_path, frame_path, render_log = render_scene(
        new_code,
        work_dir=work_dir / "render",
        resolution="720p",
        scene_id=f"{scene_id}_retouch_{rev_count}",
    )
    
    while not video_path and retry_count < max_retries:
        retry_count += 1
        emit(f"Render failed, revising code for {scene_id} (attempt {retry_count}/{max_retries})…")
        
        rev_instructions_err = f"Manim render failed with error:\n{render_log[-500:] if render_log else 'Unknown error'}\nPlease fix the code so it renders successfully."
        new_code = revise_scene_code(
            client,
            code=new_code,
            scene=scene_sec,
            revision_instructions=rev_instructions_err,
        )
        rev_count = len(list(sdir.glob("code_r*.py")))
        store.save_code(job_id, scene_id, new_code, revision=rev_count)
        
        video_path, frame_path, render_log = render_scene(
            new_code,
            work_dir=work_dir / "render",
            resolution="720p",
            scene_id=f"{scene_id}_retouch_{rev_count}",
        )

    frame_source = "none"
    if frame_path:
        frame_source = "manim_preview"
        emit("Render complete! Video frame captured.", {"has_video": True})
    else:
        log_snippet = render_log[-300:] if render_log else ""
        emit(
            f"Manim render failed: {log_snippet}" if render_log else "Manim render not enabled — generating concept preview…",
            {"render_log": render_log or ""},
        )
        create_storyboard_frame(
            scene_sec,
            output_path=sdir / f"vlm_r{rev_count}_plan_card.png",
        )
        frame_path = create_visual_preview(
            scene_sec,
            output_path=sdir / f"vlm_r{rev_count}_preview.png",
        )
        frame_source = "visual_preview"

    # Save preview frame artifact
    saved_review = store.save_vlm_review(
        job_id,
        scene_id,
        revision=rev_count,
        review={
            "approved": True,
            "issues": [],
            "revision_instructions": f"Human retouch ({human_instructions})",
            "confidence": 1.0,
        },
        frame_path=frame_path,
        frame_source=frame_source,
    )

    video_url = None
    if video_path:
        # Check if existing audio file exists for this scene
        audio_file = sdir / "audio.mp3"
        if not audio_file.exists():
            audio_file = work_dir / "audio" / f"{scene_id}.mp3"

        final_video_path = video_path
        if audio_file.exists():
            muxed_path = sdir / "scene_vo.mp4"
            muxed = mux_scene_audio(video_path, str(audio_file), muxed_path)
            if muxed:
                final_video_path = str(muxed_path)

        video_url = store.publish_scene_video(job_id, scene_id, final_video_path)

    result = {
        "ok": True,
        "job_id": job_id,
        "scene_id": scene_id,
        "revision": rev_count,
        "video_url": video_url,
        "frame_url": saved_review.get("frame_url"),
        "code": new_code,
        "scene_title": scene_sec.title,
    }

    emit("Retouch complete! Review the concept preview and approve to update the final video.", result)
    return result


def iter_retouch_scene(
    job_id: str,
    scene_id: str,
    human_instructions: str,
    timestamp: Optional[float] = None,
) -> "Iterator[str]":
    """SSE stream of retouch progress events for a single scene."""
    from queue import Empty, Queue
    from threading import Thread

    q: "Queue[PipelineEvent | None]" = Queue()

    def on_event(event: PipelineEvent) -> None:
        q.put(event)

    def worker() -> None:
        try:
            retouch_scene(
                job_id,
                scene_id,
                human_instructions,
                timestamp=timestamp,
                on_event=on_event,
            )
        except Exception as exc:  # noqa: BLE001
            q.put(
                PipelineEvent(
                    type=PipelineEventType.error,
                    message=str(exc),
                    data={"error": str(exc)},
                )
            )
        finally:
            q.put(None)

    Thread(target=worker, daemon=True).start()
    while True:
        try:
            item = q.get(timeout=300)
        except Empty:
            yield _sse({"type": "error", "message": "Retouch timed out", "data": None})
            break
        if item is None:
            break
        yield _sse(item.model_dump())



def iter_pipeline_events(request: GenerateRequest) -> Iterator[str]:
    """SSE event stream that emits progress as steps complete."""
    from queue import Empty, Queue
    from threading import Thread

    q: Queue[PipelineEvent | None] = Queue()

    def on_event(event: PipelineEvent) -> None:
        q.put(event)

    def worker() -> None:
        try:
            run_pipeline(request, on_event=on_event)
        except Exception as exc:  # noqa: BLE001
            q.put(
                PipelineEvent(
                    type=PipelineEventType.error,
                    message=str(exc),
                    data={"error": str(exc)},
                )
            )
        finally:
            q.put(None)

    Thread(target=worker, daemon=True).start()
    while True:
        try:
            item = q.get(timeout=600)
        except Empty:
            yield _sse(
                {
                    "type": PipelineEventType.error.value,
                    "message": "Pipeline timed out waiting for the next event",
                    "data": None,
                }
            )
            break
        if item is None:
            break
        yield _sse(item.model_dump())


def _sse(payload: dict) -> str:
    """Server-Sent Event frame (flushes better through proxies than NDJSON)."""
    return f"data: {json.dumps(payload)}\n\n"


def approve_scene(job_id: str, scene_id: str) -> dict[str, Any]:
    """
    Called after the human approves an AI retouch.
    Muxes the latest scene video with its audio and re-composes the final video.
    Returns {'ok': True, 'final_video_url': '...', 'scene_video_url': '...'}.
    """
    job_data = store.load_job(job_id)
    scenes = job_data.get("scenes") or []

    sdir = store.scene_dir(job_id, scene_id)
    job_dir = store.job_dir(job_id)

    # Locate the latest rendered scene video (scene.mp4 published by publish_scene_video)
    scene_video = sdir / "scene.mp4"
    if not scene_video.exists():
        # No render available — nothing to mux, just note it
        return {
            "ok": True,
            "job_id": job_id,
            "scene_id": scene_id,
            "approved": True,
            "final_video_url": None,
            "scene_video_url": None,
            "note": "No rendered video available yet. Run locally with ENABLE_MANIM_RENDER=true to produce video.",
        }

    # Mux scene video with its narration audio
    audio_p = sdir / "audio.mp3"
    audio_str = str(audio_p) if audio_p.exists() else None
    muxed_path = sdir / "scene_vo.mp4"
    muxed = mux_scene_audio(str(scene_video), audio_str, muxed_path)

    # Collect all scene clips (vo-muxed if available, else plain scene.mp4)
    muxed_clips: list[str] = []
    for s in scenes:
        sid = s["scene_id"]
        candidate = sdir.parent / sid / "scene_vo.mp4"
        if not candidate.exists():
            candidate = sdir.parent / sid / "scene.mp4"
        if candidate.exists():
            muxed_clips.append(str(candidate))

    final_url = None
    if muxed_clips:
        final_out = job_dir / "final.mp4"
        compose_final_video(muxed_clips, final_out)
        # Expose via the job file endpoint
        final_url = f"/api/jobs/{job_id}/file/final.mp4"

    scene_video_url = f"/api/jobs/{job_id}/file/scenes/{scene_id}/scene_vo.mp4" if muxed else \
                      f"/api/jobs/{job_id}/file/scenes/{scene_id}/scene.mp4"

    return {
        "ok": True,
        "job_id": job_id,
        "scene_id": scene_id,
        "approved": True,
        "final_video_url": final_url,
        "scene_video_url": scene_video_url,
    }
