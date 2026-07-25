"""End-to-end generation pipeline with step events and durable artifacts."""

from __future__ import annotations

import json
import shutil
import uuid
from collections.abc import Callable, Iterator
from pathlib import Path
from typing import Any, Optional

from backend import artifacts as store
from backend import supabase_db as db
from backend.code_utils import validate_manim_code
from backend.config import get_settings
from backend.llm import OpenRouterClient
from backend.pipeline.compose import (
    compose_final_video,
    mux_scene_audio,
    probe_duration,
)
from backend.pipeline.planner import create_scene_plan
from backend.pipeline.renderer import render_scene
from backend.pipeline.scene_generator import generate_scene_code, revise_scene_code
from backend.pipeline.storyboard import create_storyboard_frame
from backend.pipeline.tts import synthesize_narration
from backend.pipeline.visual_preview import create_visual_preview
from backend.pipeline.vlm_review import review_scene
from backend.schemas import (
    ContinueRequest,
    GenerateRequest,
    GenerateResult,
    PipelineEvent,
    PipelineEventType,
    RegenerateSceneRequest,
    SceneArtifact,
    ScenePlan,
    SceneSection,
)

EventCallback = Callable[[PipelineEvent], None]


def _slim_data(data: Optional[dict], *, event_type: Optional[str] = None) -> Optional[dict]:
    """Keep live stream payloads small so the UI updates immediately."""
    if not data:
        return data
    slim: dict = {}
    # Drop bulky blobs; keep lightweight scene summaries for the UI.
    drop = {"code", "vlm_reviews", "section"}
    # Plan events need beats / descriptions for the editable storyboard.
    plan_keep_full = event_type in {"plan", "plan_ready"}
    for key, value in data.items():
        if key in drop:
            continue
        if key == "plan" and not plan_keep_full:
            continue
        if key == "animation_beats" and not plan_keep_full:
            continue
        if key == "note" and isinstance(value, str) and len(value) > 280:
            slim[key] = value[:280] + "…"
            continue
        if key == "scenes" and isinstance(value, list):
            slim[key] = [
                {
                    "id": s.get("id") or s.get("scene_id"),
                    "scene_id": s.get("scene_id") or s.get("id"),
                    "title": s.get("title"),
                    "narration": s.get("narration") if plan_keep_full else (s.get("narration") or "")[:220],
                    "visual_description": s.get("visual_description") if plan_keep_full else None,
                    "animation_beats": s.get("animation_beats") if plan_keep_full else None,
                    "duration_seconds": s.get("duration_seconds"),
                    "visual_device": s.get("visual_device"),
                    "style_tags": s.get("style_tags") if plan_keep_full else None,
                    "camera_notes": s.get("camera_notes") if plan_keep_full else None,
                    "video_url": s.get("video_url"),
                    "frame_url": s.get("frame_url"),
                    "vlm_approved": s.get("vlm_approved"),
                    "clarity_score": s.get("clarity_score"),
                }
                for s in value
                if isinstance(s, dict)
            ]
            # Strip Nones for cleaner SSE
            slim[key] = [
                {k: v for k, v in s.items() if v is not None} for s in slim[key]
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
    live_data = _slim_data(data, event_type=event_type.value)
    event = PipelineEvent(type=event_type, message=message, data=live_data)
    if job_id:
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


def _job_resolution(job_id: str, fallback: str = "720p") -> str:
    try:
        meta = store.load_job(job_id).get("meta") or {}
        settings = meta.get("settings") or {}
        res = settings.get("resolution")
        if isinstance(res, str) and res in {"480p", "720p", "1080p"}:
            return res
    except Exception:  # noqa: BLE001
        pass
    return fallback


def _load_plan(job_id: str) -> ScenePlan:
    job = store.load_job(job_id)
    plan_data = job.get("scene_plan")
    if not plan_data:
        raise ValueError(f"No scene plan for job {job_id}")
    return ScenePlan.model_validate(plan_data)


def update_scene_plan(job_id: str, plan: ScenePlan) -> ScenePlan:
    """Persist an edited plan and per-scene section.json files."""
    store.save_scene_plan(job_id, plan.model_dump())
    for scene in plan.scenes:
        store.save_scene_section(job_id, scene.id, scene.model_dump())
    # Keep meta title in sync when possible
    try:
        meta_path = store.job_dir(job_id) / "meta.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
            meta["title"] = plan.title
            meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass
    return plan


def _process_one_scene(
    *,
    client: OpenRouterClient,
    job_id: str,
    work_dir: Path,
    plan: ScenePlan,
    scene: SceneSection,
    index: int,
    total: int,
    previous_context: str,
    resolution: str,
    skip_render: bool,
    on_event: Optional[EventCallback],
    creative_direction: str = "",
) -> SceneArtifact:
    """TTS-first → codegen (timed) → render → VLM for a single scene."""
    settings = get_settings()
    store.save_scene_section(job_id, scene.id, scene.model_dump())
    _emit(
        on_event,
        PipelineEventType.scene_start,
        f"Scene {index + 1}/{total}: {scene.title}",
        data={"scene_id": scene.id, "index": index, "job_id": job_id},
        job_id=job_id,
    )

    sdir = store.scene_dir(job_id, scene.id)

    # --- TTS first so codegen can match narration length ---
    audio_path, audio_skipped = synthesize_narration(
        scene.narration,
        work_dir / "audio" / f"{scene.id}.mp3",
        settings=settings,
    )
    if audio_path and Path(audio_path).exists():
        shutil.copy2(audio_path, sdir / "audio.mp3")
        target_duration = probe_duration(Path(audio_path)) or scene.duration_seconds
    else:
        target_duration = scene.duration_seconds

    # Persist measured duration back onto the section for debugging
    scene = scene.model_copy(update={"duration_seconds": float(target_duration)})
    store.save_scene_section(job_id, scene.id, scene.model_dump())

    _emit(
        on_event,
        PipelineEventType.scene_tts,
        f"TTS for {scene.id}"
        + (" (skipped — no TTS_API_KEY)" if audio_skipped else f" · {target_duration:.1f}s"),
        data={
            "scene_id": scene.id,
            "audio_path": audio_path,
            "skipped": audio_skipped,
            "target_duration": target_duration,
            "job_id": job_id,
        },
        job_id=job_id,
    )

    code = generate_scene_code(
        client,
        plan=plan,
        scene=scene,
        previous_context=previous_context,
        target_duration_seconds=target_duration,
        creative_direction=creative_direction,
    )
    store.save_code(job_id, scene.id, code, revision=0)
    _emit(
        on_event,
        PipelineEventType.scene_code,
        f"Generated Manim code for {scene.id} (target {target_duration:.1f}s)",
        data={"scene_id": scene.id, "code_chars": len(code), "job_id": job_id},
        job_id=job_id,
    )

    video_path = None
    video_url = None
    frame_path = None
    frame_source = "none"
    frame_urls: list[str] = []
    reviews_log: list[dict] = []
    revision_count = 0
    preview_note = None

    if not skip_render:
        video_path, frame_path, render_log = render_scene(
            code,
            work_dir=work_dir / "render",
            resolution=resolution,
            scene_id=f"{scene.id}_r{revision_count}",
        )

        while not video_path and revision_count < settings.max_scene_revisions:
            # Don't burn LLM revisions on infra failures (bad worker URL, manim missing).
            infra = (render_log or "").lower()
            if any(
                marker in infra
                for marker in (
                    "http 404",
                    "http 401",
                    "http 502",
                    "http 503",
                    "not installed",
                    "render disabled",
                    "request failed",
                )
            ):
                break
            revision_count += 1
            _emit(
                on_event,
                PipelineEventType.status,
                f"Render failed, revising code for {scene.id} (attempt {revision_count})…",
                data={"scene_id": scene.id, "job_id": job_id},
                job_id=job_id,
            )
            rev_instructions = (
                f"Manim render failed with error:\n"
                f"{render_log[-500:] if render_log else 'Unknown error'}\n"
                "Please fix the code so it renders successfully."
            )
            code = revise_scene_code(
                client,
                code=code,
                scene=scene,
                revision_instructions=rev_instructions,
                target_duration_seconds=target_duration,
            )
            store.save_code(job_id, scene.id, code, revision=revision_count)
            video_path, frame_path, render_log = render_scene(
                code,
                work_dir=work_dir / "render",
                resolution=resolution,
                scene_id=f"{scene.id}_r{revision_count}",
            )

        preview_note = None if video_path else render_log
        if frame_path:
            frame_source = "manim_preview"
        _emit(
            on_event,
            PipelineEventType.scene_render,
            f"Render step for {scene.id}"
            + (" · clip rendered" if video_path else " · render failed"),
            data={
                "scene_id": scene.id,
                "ok": bool(video_path),
                "note": preview_note,
                "job_id": job_id,
            },
            job_id=job_id,
        )
    else:
        preview_note = "Render skipped by request."

    if not frame_path:
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
                "image_vlm" if frame_source == "manim_preview" else "code_only"
            ),
        }
    )
    _emit(
        on_event,
        PipelineEventType.scene_vlm,
        f"Scene check for {scene.id}"
        + (
            f" · clarity {review.clarity_score:.0%}"
            if hasattr(review, "clarity_score")
            else ""
        ),
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

    # Mux narration immediately so the UI can play a finished clip per scene
    # (don't wait for the whole pipeline / final compose).
    if video_path:
        muxed = mux_scene_audio(
            video_path,
            audio_path,
            sdir / "scene_vo.mp4",
        )
        publish_src = muxed or video_path
        video_url = store.publish_scene_video(job_id, scene.id, publish_src)
        if muxed:
            video_path = muxed

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
            "clarity_score": getattr(review, "clarity_score", None),
            "revision_count": revision_count,
        },
        job_id=job_id,
    )
    return artifact


def _compose_and_finish(
    *,
    client: OpenRouterClient,
    job_id: str,
    plan: ScenePlan,
    artifacts: list[SceneArtifact],
    prompt: str,
    resolution: str,
    skip_render: bool,
    user_id: Optional[str],
    on_event: Optional[EventCallback],
) -> GenerateResult:
    settings = get_settings()
    debug = {
        "notes": "Automated VLM revisions disabled (human-in-the-loop review active)",
        "scene_fixes": [],
    }
    store.save_final_debug(job_id, debug)
    notes = str(debug.get("notes", ""))
    _emit(
        on_event,
        PipelineEventType.final_debug,
        "Automated VLM revision pass skipped (human review mode active)",
        data={**debug, "job_id": job_id},
        job_id=job_id,
    )

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
            art.video_url = store.publish_scene_video(job_id, art.scene_id, muxed)

    final_path = compose_final_video(
        muxed_clips,
        store.job_dir(job_id) / "final.mp4",
    )
    final_url = f"/api/jobs/{job_id}/file/final.mp4" if final_path else None

    result = GenerateResult(
        title=plan.title,
        plan=plan,
        scenes=artifacts,
        final_debug_notes=notes,
        final_video_path=final_path,
        final_video_url=final_url,
        render_enabled=settings.enable_manim_render and not skip_render,
        job_id=job_id,
        artifact_url=f"/api/jobs/{job_id}",
        scene_plan_url=f"/api/jobs/{job_id}/file/scene_plan.json",
        awaiting_plan_confirm=False,
    )
    store.save_result(job_id, result.model_dump())
    if user_id:
        db.flush_client_usage(
            user_id=user_id,
            job_id=job_id,
            usage_log=client.drain_usage_log(),
        )
        db.upsert_job(
            job_id=job_id,
            user_id=user_id,
            prompt=prompt,
            title=plan.title,
            status="complete",
        )
        try:
            db.sync_job_storage(
                user_id=user_id,
                job_id=job_id,
                job_path=store.job_dir(job_id),
            )
        except db.QuotaExceededError:
            _emit(
                on_event,
                PipelineEventType.status,
                "Warning: storage quota exceeded after this job",
                data={"job_id": job_id, "quota": "STORAGE_LIMIT"},
                job_id=job_id,
            )
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


def _run_scenes_loop(
    *,
    client: OpenRouterClient,
    job_id: str,
    plan: ScenePlan,
    resolution: str,
    skip_render: bool,
    user_id: Optional[str],
    prompt: str,
    on_event: Optional[EventCallback],
) -> GenerateResult:
    work_dir = store.job_dir(job_id)
    artifacts: list[SceneArtifact] = []
    previous_context = ""

    def _flush_usage() -> None:
        if not user_id:
            return
        db.flush_client_usage(
            user_id=user_id,
            job_id=job_id,
            usage_log=client.drain_usage_log(),
        )

    for index, scene in enumerate(plan.scenes):
        artifact = _process_one_scene(
            client=client,
            job_id=job_id,
            work_dir=work_dir,
            plan=plan,
            scene=scene,
            index=index,
            total=len(plan.scenes),
            previous_context=previous_context,
            resolution=resolution,
            skip_render=skip_render,
            on_event=on_event,
        )
        artifacts.append(artifact)
        previous_context += (
            f"\n- {scene.id}: {scene.title} — {scene.visual_description[:180]}"
        )
        _flush_usage()

    return _compose_and_finish(
        client=client,
        job_id=job_id,
        plan=plan,
        artifacts=artifacts,
        prompt=prompt,
        resolution=resolution,
        skip_render=skip_render,
        user_id=user_id,
        on_event=on_event,
    )


def run_pipeline(
    request: GenerateRequest,
    *,
    on_event: Optional[EventCallback] = None,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
) -> GenerateResult:
    """
    Pipeline:
      1) Prompt → JSON scene plan (saved)
      2) If plan_only: emit plan_ready and return (UI edits, then continue)
      3) Else: TTS → generate → render → VLM → compose
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
            "length_preset": request.length_preset,
            "audience": request.audience,
            "plan_only": request.plan_only,
        },
        user_id=user_id,
        user_email=user_email,
        user_name=user_name,
    )
    del work_dir  # init_job side-effect is enough here

    if user_id:
        db.ensure_user(
            user_id=user_id,
            email=user_email,
            name=user_name,
        )
        db.upsert_job(
            job_id=job_id,
            user_id=user_id,
            prompt=request.prompt,
            status="running",
        )

    def _flush_usage() -> None:
        if not user_id:
            return
        db.flush_client_usage(
            user_id=user_id,
            job_id=job_id,
            usage_log=client.drain_usage_log(),
        )

    _emit(
        on_event,
        PipelineEventType.status,
        f"Planning scenes from prompt… (job {job_id})",
        data={"job_id": job_id},
        job_id=job_id,
    )
    plan = create_scene_plan(
        client,
        request.prompt,
        length_preset=request.length_preset,
        audience=request.audience,
    )
    plan_path = store.save_scene_plan(job_id, plan.model_dump())
    for scene in plan.scenes:
        store.save_scene_section(job_id, scene.id, scene.model_dump())
    _flush_usage()
    if user_id:
        db.upsert_job(
            job_id=job_id,
            user_id=user_id,
            prompt=request.prompt,
            title=plan.title,
            status="awaiting_plan" if request.plan_only else "running",
        )

    plan_payload = {
        **plan.model_dump(),
        "job_id": job_id,
        "scene_plan_url": f"/api/jobs/{job_id}/file/scene_plan.json",
        "saved_path": plan_path,
        "awaiting_confirm": request.plan_only,
        "length_preset": request.length_preset,
        "audience": request.audience,
    }
    _emit(
        on_event,
        PipelineEventType.plan,
        f"Planned {len(plan.scenes)} scenes: {plan.title}",
        data=plan_payload,
        job_id=job_id,
    )

    if request.plan_only:
        _emit(
            on_event,
            PipelineEventType.plan_ready,
            "Storyboard ready — edit scenes, then confirm to generate video",
            data=plan_payload,
            job_id=job_id,
        )
        return GenerateResult(
            title=plan.title,
            plan=plan,
            scenes=[],
            final_debug_notes="Awaiting plan confirmation",
            job_id=job_id,
            artifact_url=f"/api/jobs/{job_id}",
            scene_plan_url=f"/api/jobs/{job_id}/file/scene_plan.json",
            awaiting_plan_confirm=True,
            render_enabled=False,
        )

    return _run_scenes_loop(
        client=client,
        job_id=job_id,
        plan=plan,
        resolution=request.resolution,
        skip_render=request.skip_render,
        user_id=user_id,
        prompt=request.prompt,
        on_event=on_event,
    )


def continue_pipeline(
    job_id: str,
    request: Optional[ContinueRequest] = None,
    *,
    on_event: Optional[EventCallback] = None,
    user_id: Optional[str] = None,
) -> GenerateResult:
    """Resume a plan_only job: run scenes from the (possibly edited) plan."""
    request = request or ContinueRequest()
    settings = get_settings()
    client = OpenRouterClient(settings)
    job = store.load_job(job_id)
    meta = job.get("meta") or {}
    prompt = str(meta.get("prompt") or "")
    owner = meta.get("user_id") if isinstance(meta, dict) else None
    if user_id and owner and owner != user_id:
        raise PermissionError("Not job owner")

    plan = _load_plan(job_id)
    resolution = request.resolution or _job_resolution(job_id)
    skip_render = request.skip_render

    if user_id:
        db.upsert_job(
            job_id=job_id,
            user_id=user_id,
            prompt=prompt,
            title=plan.title,
            status="running",
        )

    _emit(
        on_event,
        PipelineEventType.status,
        f"Generating {len(plan.scenes)} scenes from storyboard…",
        data={"job_id": job_id, "title": plan.title},
        job_id=job_id,
    )
    return _run_scenes_loop(
        client=client,
        job_id=job_id,
        plan=plan,
        resolution=resolution,
        skip_render=skip_render,
        user_id=user_id or (owner if isinstance(owner, str) else None),
        prompt=prompt,
        on_event=on_event,
    )


def regenerate_scene(
    job_id: str,
    scene_id: str,
    request: Optional[RegenerateSceneRequest] = None,
    *,
    on_event: Optional[EventCallback] = None,
) -> dict[str, Any]:
    """Regenerate a single scene from scratch (not a comment retouch)."""
    request = request or RegenerateSceneRequest()
    settings = get_settings()
    client = OpenRouterClient(settings=settings)
    job = store.load_job(job_id)
    meta = job.get("meta") or {}
    owner_id = meta.get("user_id") if isinstance(meta, dict) else None
    if isinstance(owner_id, str) and owner_id:
        db.assert_within_quotas(owner_id, need_tokens=8_000)

    plan = _load_plan(job_id)
    scene = request.section
    if scene is None:
        match = next((s for s in plan.scenes if s.id == scene_id), None)
        if not match:
            # Fall back to section.json
            job_scenes = job.get("scenes") or []
            match_scene = next(
                (s for s in job_scenes if s["scene_id"] == scene_id), None
            )
            if not match_scene or not match_scene.get("section"):
                raise ValueError(f"Scene {scene_id} not found")
            scene = SceneSection.model_validate(match_scene["section"])
        else:
            scene = match
    else:
        scene = scene.model_copy(update={"id": scene_id})

    # Keep plan in sync if section was edited
    new_scenes = []
    found = False
    for s in plan.scenes:
        if s.id == scene_id:
            new_scenes.append(scene)
            found = True
        else:
            new_scenes.append(s)
    if not found:
        new_scenes.append(scene)
    plan = plan.model_copy(update={"scenes": new_scenes})
    update_scene_plan(job_id, plan)

    resolution = _job_resolution(job_id)
    prev_parts = [
        f"- {s.id}: {s.title}" for s in plan.scenes if s.id != scene_id
    ]
    index = next(
        (i for i, s in enumerate(plan.scenes) if s.id == scene_id), 0
    )

    artifact = _process_one_scene(
        client=client,
        job_id=job_id,
        work_dir=store.job_dir(job_id),
        plan=plan,
        scene=scene,
        index=index,
        total=len(plan.scenes),
        previous_context="\n".join(prev_parts),
        resolution=resolution,
        skip_render=request.skip_render,
        on_event=on_event,
        creative_direction=request.direction,
    )

    # Mux + refresh final if we have video
    video_url = artifact.video_url
    if artifact.video_path:
        muxed = mux_scene_audio(
            artifact.video_path,
            artifact.audio_path,
            store.scene_dir(job_id, scene_id) / "scene_vo.mp4",
        )
        if muxed:
            video_url = store.publish_scene_video(job_id, scene_id, muxed)

    # Recompose final from all available scene clips
    muxed_clips: list[str] = []
    for s in plan.scenes:
        cand = store.scene_dir(job_id, s.id) / "scene_vo.mp4"
        if not cand.exists():
            cand = store.scene_dir(job_id, s.id) / "scene.mp4"
        if cand.exists():
            muxed_clips.append(str(cand))
    final_url = None
    if muxed_clips:
        compose_final_video(muxed_clips, store.job_dir(job_id) / "final.mp4")
        final_url = f"/api/jobs/{job_id}/file/final.mp4"

    if isinstance(owner_id, str) and owner_id:
        db.flush_client_usage(
            user_id=owner_id,
            job_id=job_id,
            usage_log=client.drain_usage_log(),
        )

    result = {
        "ok": True,
        "job_id": job_id,
        "scene_id": scene_id,
        "video_url": video_url,
        "frame_url": artifact.vlm_frame_urls[-1] if artifact.vlm_frame_urls else None,
        "final_video_url": final_url,
        "vlm_approved": artifact.vlm_approved,
        "title": scene.title,
    }
    _emit(
        on_event,
        PipelineEventType.complete,
        f"Regenerated {scene_id}",
        data=result,
        job_id=job_id,
    )
    return result


def retouch_scene(
    job_id: str,
    scene_id: str,
    human_instructions: str,
    timestamp: Optional[float] = None,
    on_event: Optional[Any] = None,
) -> dict[str, Any]:
    """Retouch/revise ONLY a specific scene based on human feedback."""
    settings = get_settings()
    client = OpenRouterClient(settings=settings)

    def emit(msg: str, data: Optional[dict] = None) -> None:
        if on_event:
            on_event(
                PipelineEvent(
                    type=PipelineEventType.status, message=msg, data=data or {}
                )
            )

    emit(f"Loading scene data for '{scene_id}'…", {"scene_id": scene_id, "job_id": job_id})

    job_data = store.load_job(job_id)
    meta = job_data.get("meta") or {}
    owner_id = meta.get("user_id") if isinstance(meta, dict) else None
    if isinstance(owner_id, str) and owner_id:
        db.assert_within_quotas(owner_id, need_tokens=5_000)
    scenes = job_data.get("scenes") or []
    match_scene = next((s for s in scenes if s["scene_id"] == scene_id), None)
    if not match_scene:
        raise ValueError(f"Scene {scene_id} not found in job {job_id}")

    section_data = match_scene.get("section") or {}
    scene_sec = SceneSection.model_validate(
        {**section_data, "id": scene_id}
    )

    current_code = match_scene.get("code_final", "")
    rev_instructions = human_instructions
    if timestamp is not None:
        rev_instructions = (
            f"[At timestamp {timestamp:.1f}s in the scene]: {human_instructions}. "
            "Adjust the animation beat closest to that moment."
        )

    emit(
        f"AI is reading your feedback and revising the Manim code for '{scene_sec.title}'…",
        {"scene_id": scene_id, "instructions": rev_instructions},
    )

    retry_count = 0
    max_retries = settings.max_scene_revisions
    target_duration = scene_sec.duration_seconds
    audio_file = store.scene_dir(job_id, scene_id) / "audio.mp3"
    if audio_file.exists():
        target_duration = probe_duration(audio_file) or target_duration

    new_code = revise_scene_code(
        client,
        code=current_code,
        scene=scene_sec,
        revision_instructions=rev_instructions,
        target_duration_seconds=target_duration,
    )

    ok, err = validate_manim_code(new_code)
    while not ok and retry_count < max_retries:
        retry_count += 1
        emit(
            f"Syntax error in revised code: {err} — retrying ({retry_count}/{max_retries}).",
            {"error": err},
        )
        new_code = revise_scene_code(
            client,
            code=new_code,
            scene=scene_sec,
            revision_instructions=(
                f"Previous revision had a syntax error:\n{err}\nPlease fix it."
            ),
            target_duration_seconds=target_duration,
        )
        ok, err = validate_manim_code(new_code)

    if not ok:
        emit(f"Syntax error in revised code: {err} — aborting.", {"error": err})
        raise ValueError(f"Generated retouched code invalid: {err}")

    emit("Code revision complete. Saving new code…", {"code_chars": len(new_code)})

    sdir = store.scene_dir(job_id, scene_id)
    rev_count = len(list(sdir.glob("code_r*.py")))
    store.save_code(job_id, scene_id, new_code, revision=rev_count)

    resolution = _job_resolution(job_id)
    emit(
        f"Rendering scene '{scene_sec.title}' (revision {rev_count})…",
        {"revision": rev_count},
    )

    work_dir = store.job_dir(job_id) / "work"
    video_path, frame_path, render_log = render_scene(
        new_code,
        work_dir=work_dir / "render",
        resolution=resolution,
        scene_id=f"{scene_id}_retouch_{rev_count}",
    )

    while not video_path and retry_count < max_retries:
        retry_count += 1
        emit(
            f"Render failed, revising code for {scene_id} "
            f"(attempt {retry_count}/{max_retries})…"
        )
        rev_instructions_err = (
            f"Manim render failed with error:\n"
            f"{render_log[-500:] if render_log else 'Unknown error'}\n"
            "Please fix the code so it renders successfully."
        )
        new_code = revise_scene_code(
            client,
            code=new_code,
            scene=scene_sec,
            revision_instructions=rev_instructions_err,
            target_duration_seconds=target_duration,
        )
        rev_count = len(list(sdir.glob("code_r*.py")))
        store.save_code(job_id, scene_id, new_code, revision=rev_count)
        video_path, frame_path, render_log = render_scene(
            new_code,
            work_dir=work_dir / "render",
            resolution=resolution,
            scene_id=f"{scene_id}_retouch_{rev_count}",
        )

    frame_source = "none"
    if frame_path:
        frame_source = "manim_preview"
        emit("Render complete! Video frame captured.", {"has_video": True})
    else:
        log_snippet = render_log[-300:] if render_log else ""
        emit(
            f"Manim render failed: {log_snippet}"
            if render_log
            else "Manim render not enabled — generating concept preview…",
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

    saved_review = store.save_vlm_review(
        job_id,
        scene_id,
        revision=rev_count,
        review={
            "approved": True,
            "issues": [],
            "revision_instructions": f"Human retouch ({human_instructions})",
            "confidence": 1.0,
            "clarity_score": 0.8,
            "misconception_risk": 0.2,
        },
        frame_path=frame_path,
        frame_source=frame_source,
    )

    video_url = None
    if video_path:
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

    if isinstance(owner_id, str) and owner_id:
        db.flush_client_usage(
            user_id=owner_id,
            job_id=job_id,
            usage_log=client.drain_usage_log(),
        )
        try:
            db.sync_job_storage(
                user_id=owner_id,
                job_id=job_id,
                job_path=store.job_dir(job_id),
            )
        except db.QuotaExceededError:
            emit(
                "Warning: storage quota exceeded after this retouch",
                {"quota": "STORAGE_LIMIT"},
            )

    emit(
        "Retouch complete! Review the concept preview and approve to update the final video.",
        result,
    )
    return result


def iter_retouch_scene(
    job_id: str,
    scene_id: str,
    human_instructions: str,
    timestamp: Optional[float] = None,
) -> Iterator[str]:
    """SSE stream of retouch progress events for a single scene."""
    from queue import Empty, Queue
    from threading import Thread

    q: Queue[PipelineEvent | None] = Queue()

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


def iter_pipeline_events(
    request: GenerateRequest,
    *,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
) -> Iterator[str]:
    """SSE event stream that emits progress as steps complete."""
    from queue import Empty, Queue
    from threading import Thread

    q: Queue[PipelineEvent | None] = Queue()

    def on_event(event: PipelineEvent) -> None:
        q.put(event)

    def worker() -> None:
        try:
            run_pipeline(
                request,
                on_event=on_event,
                user_id=user_id,
                user_email=user_email,
                user_name=user_name,
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


def iter_continue_events(
    job_id: str,
    request: Optional[ContinueRequest] = None,
    *,
    user_id: Optional[str] = None,
) -> Iterator[str]:
    from queue import Empty, Queue
    from threading import Thread

    q: Queue[PipelineEvent | None] = Queue()

    def on_event(event: PipelineEvent) -> None:
        q.put(event)

    def worker() -> None:
        try:
            continue_pipeline(
                job_id, request, on_event=on_event, user_id=user_id
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
            item = q.get(timeout=600)
        except Empty:
            yield _sse(
                {
                    "type": "error",
                    "message": "Continue pipeline timed out",
                    "data": None,
                }
            )
            break
        if item is None:
            break
        yield _sse(item.model_dump())


def iter_regenerate_scene(
    job_id: str,
    scene_id: str,
    request: Optional[RegenerateSceneRequest] = None,
) -> Iterator[str]:
    from queue import Empty, Queue
    from threading import Thread

    q: Queue[PipelineEvent | None] = Queue()

    def on_event(event: PipelineEvent) -> None:
        q.put(event)

    def worker() -> None:
        try:
            regenerate_scene(
                job_id, scene_id, request, on_event=on_event
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
            item = q.get(timeout=400)
        except Empty:
            yield _sse(
                {"type": "error", "message": "Regenerate timed out", "data": None}
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
    """
    job_data = store.load_job(job_id)
    scenes = job_data.get("scenes") or []

    sdir = store.scene_dir(job_id, scene_id)
    job_dir = store.job_dir(job_id)

    scene_video = sdir / "scene.mp4"
    if not scene_video.exists():
        return {
            "ok": True,
            "job_id": job_id,
            "scene_id": scene_id,
            "approved": True,
            "final_video_url": None,
            "scene_video_url": None,
            "note": (
                "No rendered video available yet. Run locally with "
                "ENABLE_MANIM_RENDER=true to produce video."
            ),
        }

    audio_p = sdir / "audio.mp3"
    audio_str = str(audio_p) if audio_p.exists() else None
    muxed_path = sdir / "scene_vo.mp4"
    muxed = mux_scene_audio(str(scene_video), audio_str, muxed_path)

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
        final_url = f"/api/jobs/{job_id}/file/final.mp4"

    scene_video_url = (
        f"/api/jobs/{job_id}/file/scenes/{scene_id}/scene_vo.mp4"
        if muxed
        else f"/api/jobs/{job_id}/file/scenes/{scene_id}/scene.mp4"
    )

    return {
        "ok": True,
        "job_id": job_id,
        "scene_id": scene_id,
        "approved": True,
        "final_video_url": final_url,
        "scene_video_url": scene_video_url,
    }
