"""End-to-end generation pipeline with step events and durable artifacts."""

from __future__ import annotations

import json
import uuid
from collections.abc import Callable, Iterator
from typing import Optional

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

        revision_count = 0
        video_path = None
        video_url = None
        preview_note = None
        approved = False
        issues: list[str] = []
        frame_urls: list[str] = []
        reviews_log: list[dict] = []

        while True:
            frame_path = None
            frame_source = "none"

            if not request.skip_render:
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

            # When Manim isn't available, draw a real concept still (not a text card).
            # Keep a plan card alongside for the written brief.
            if not frame_path:
                sdir = store.scene_dir(job_id, scene.id)
                create_storyboard_frame(
                    scene,
                    output_path=sdir / f"vlm_r{revision_count}_plan_card.png",
                )
                frame_path = create_visual_preview(
                    scene,
                    output_path=sdir / f"vlm_r{revision_count}_preview.png",
                )
                frame_source = "visual_preview"

            # Local syntax gate before / alongside model review
            syntax_ok, syntax_err = validate_manim_code(code)
            # Image VLM for Manim frames; code-only for matplotlib previews / plan cards
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
                        "revision_instructions": (
                            f"Fix invalid Python ({syntax_err}). "
                            "Rewrite a complete valid Manim Community Scene covering the beats."
                        ),
                    }
                )

            saved = store.save_vlm_review(
                job_id,
                scene.id,
                revision=revision_count,
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
                    "revision": revision_count,
                    "frame_source": frame_source,
                    "frame_url": saved.get("frame_url"),
                    "review_mode": (
                        "image_vlm"
                        if frame_source == "manim_preview"
                        else "code_only"
                    ),
                }
            )
            mode = "image VLM" if frame_source == "manim_preview" else "code review"
            _emit(
                on_event,
                PipelineEventType.scene_vlm,
                f"{mode} for {scene.id}: "
                f"{'approved' if approved else 'needs revision'}",
                data={
                    **review.model_dump(),
                    "scene_id": scene.id,
                    "job_id": job_id,
                    "frame_url": saved.get("frame_url"),
                    "frame_source": frame_source,
                    "revision": revision_count,
                    "review_mode": (
                        "image_vlm"
                        if frame_source == "manim_preview"
                        else "code_only"
                    ),
                },
                job_id=job_id,
            )

            if approved or revision_count >= settings.max_scene_revisions:
                break

            revision_count += 1
            _emit(
                on_event,
                PipelineEventType.scene_revise,
                f"Revising {scene.id} (attempt {revision_count})",
                data={
                    "scene_id": scene.id,
                    "instructions": review.revision_instructions,
                    "job_id": job_id,
                },
                job_id=job_id,
            )
            previous_code = code
            candidate = revise_scene_code(
                client,
                code=code,
                scene=scene,
                revision_instructions=review.revision_instructions,
                # Don't feed "Manim disabled" as a render error — it causes bad revisions.
                render_error=""
                if frame_source in {"storyboard", "visual_preview"}
                else (preview_note or ""),
            )
            cand_ok, _ = validate_manim_code(candidate)
            # Keep prior code if the model returns garbage / truncated junk
            code = candidate if cand_ok else previous_code
            store.save_code(job_id, scene.id, code, revision=revision_count)

        audio_path, audio_skipped = synthesize_narration(
            scene.narration,
            work_dir / "audio" / f"{scene.id}.mp3",
            settings=settings,
        )
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
    debug = final_debug_pass(
        client,
        plan_json=plan.model_dump_json(indent=2),
        scene_summaries=scene_summaries,
    )
    store.save_final_debug(job_id, debug)
    notes = str(debug.get("notes", ""))
    _emit(
        on_event,
        PipelineEventType.final_debug,
        "Final debug pass complete",
        data={**debug, "job_id": job_id},
        job_id=job_id,
    )

    for fix in debug.get("scene_fixes") or []:
        scene_id = fix.get("scene_id")
        instructions = fix.get("instructions") or ""
        if not scene_id or not instructions:
            continue
        # Ignore pixel/render asks when we never rendered
        lowered = instructions.lower()
        if not settings.enable_manim_render and any(
            k in lowered
            for k in ("render", "frame", "pixel", "inspection overlay", "storyboard")
        ):
            continue
        match = next((a for a in artifacts if a.scene_id == scene_id), None)
        plan_scene = next((s for s in plan.scenes if s.id == scene_id), None)
        if not match or not plan_scene:
            continue
        candidate = revise_scene_code(
            client,
            code=match.code,
            scene=plan_scene,
            revision_instructions=instructions,
        )
        ok, _ = validate_manim_code(candidate)
        if not ok:
            continue
        match.code = candidate
        match.revision_count += 1
        store.save_code(
            job_id, scene_id, match.code, revision=match.revision_count
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
