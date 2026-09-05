"""End-to-end generation pipeline with step events and durable artifacts."""

from __future__ import annotations

import asyncio
import json
import os
import re
import shutil
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path
from typing import Any, Optional

from backend import artifacts as store
from backend import job_runner
from backend import supabase_db as db
from backend.code_utils import (
    clean_manim_code,
    layout_revision_instructions,
    lint_scene_code,
    parse_layout_report,
    scene_body,
    validate_manim_code,
)
from backend.config import get_settings
from backend.llm import OpenRouterClient
from backend.pipeline.compose import (
    compose_final_video,
    mux_scene_audio,
    probe_duration,
)
from backend.pipeline.pedagogy import create_teaching_blueprint
from backend.pipeline.planner import (
    AUDIENCE_GUIDANCE,
    create_scene_plan,
    revise_scene_plan as _revise_plan_llm,
    scene_count_range,
)
from backend.pipeline.renderer import extract_review_frames, preview_scene_frame, render_scene
from backend.pipeline.scene_generator import (
    codegen_spec_payload,
    generate_scene_code,
    revise_scene_code,
)
from backend.pipeline.storyboard import create_storyboard_frame
from backend.pipeline.tts import synthesize_scene_narration
from backend.pipeline.visual_preview import create_visual_preview
from backend.pipeline.vlm_review import review_scene
from backend.languages import DEFAULT_LANGUAGE, normalize_language
from backend.tts_voices import DEFAULT_TTS_VOICE, normalize_tts_voice


def _scene_audio_file(directory: Path) -> Optional[Path]:
    """Prefer WAV (Gemini/Vercel) then legacy MP3."""
    for name in ("audio.wav", "audio.mp3"):
        path = directory / name
        if path.exists():
            return path
    return None
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
    VlmReview,
)

EventCallback = Callable[[PipelineEvent], None]


class JobCancelledError(Exception):
    """Raised when the user cancels an ongoing generation job."""
    pass


class ProductionOptionsRequired(ValueError):
    """Spoken audio / subtitles / voice must be chosen after the storyboard."""


PRODUCTION_OPTIONS_REQUIRED_MSG = (
    "Spoken audio, burned-in subtitles, and narrator voice are chosen after the "
    "storyboard. Ask the user, then save with update_video_options "
    "(PUT /api/jobs/{id}/settings) before writing Manim or rendering."
)


def _check_cancel(job_id: str) -> None:
    if job_runner.is_cancelled(job_id):
        raise JobCancelledError("Generation cancelled by user")


def _needs_visual_revision(review: Any, *, clarity_threshold: float) -> bool:
    """True when VLM/code review says the scene is cluttered, unclear, or rejected."""
    approved = bool(getattr(review, "approved", False))
    clarity = float(getattr(review, "clarity_score", 1.0) or 1.0)
    risk = float(getattr(review, "misconception_risk", 0.0) or 0.0)
    issues = list(getattr(review, "issues", None) or [])
    if not approved:
        # Require actionable signal — bare rejects with no issues/clarity hit thrash.
        return bool(issues) or clarity < clarity_threshold or risk >= 0.55
    # Approved but still messy: only revise when the reviewer flagged problems.
    if clarity < clarity_threshold and (issues or risk >= 0.65):
        return True
    return risk >= 0.75


def _review_clarity(review: Any) -> float:
    return float(getattr(review, "clarity_score", 0.0) or 0.0)


def _revision_instructions_from_review(review: Any) -> str:
    instructions = (getattr(review, "revision_instructions", None) or "").strip()
    issues = list(getattr(review, "issues", None) or [])
    parts = []
    if instructions:
        parts.append(instructions)
    if issues:
        parts.append("Issues to fix:\n- " + "\n- ".join(issues[:4]))
    # Keep boilerplate short so revises stay surgical (do NOT push formula truncation).
    parts.append(
        "Surgical layout fixes only: reposition overlaps, FadeOut prior labels before "
        "dense beats, keep one complete formula readable (smaller font / two lines OK — "
        "never truncate terms), remove decorative filler shapes, keep the core diagram "
        "visible in the final hold."
    )
    return "\n\n".join(parts)


# Cap Manim code in SSE / events.jsonl so reconnects stay responsive.
_CODE_PREVIEW_CHARS = 14_000


def _slim_data(data: Optional[dict], *, event_type: Optional[str] = None) -> Optional[dict]:
    """Keep live stream payloads small so the UI updates immediately."""
    if not data:
        return data
    slim: dict = {}
    # Drop bulky blobs; keep lightweight scene summaries for the UI.
    # Code is kept (truncated) on scene_code / scene_revise so the activity
    # panel can show what the model just wrote.
    drop = {"vlm_reviews", "section"}
    keep_code = event_type in {"scene_code", "scene_revise"}
    if not keep_code:
        drop = {*drop, "code"}
    # Plan events need beats / descriptions for the editable storyboard.
    plan_keep_full = event_type in {"plan", "plan_ready"}
    for key, value in data.items():
        if key in drop:
            continue
        if key == "code" and isinstance(value, str):
            if len(value) > _CODE_PREVIEW_CHARS:
                slim[key] = value[:_CODE_PREVIEW_CHARS] + "\n# … truncated for live preview"
                slim["code_truncated"] = True
            else:
                slim[key] = value
                slim["code_truncated"] = False
            slim["code_chars"] = len(value)
            continue
        if key == "plan" and not plan_keep_full:
            continue
        if key == "animation_beats" and not plan_keep_full:
            continue
        if key == "note" and isinstance(value, str) and len(value) > 280:
            slim[key] = value[:280] + "…"
            continue
        if key == "detail" and isinstance(value, str) and len(value) > 500:
            slim[key] = value[:500] + "…"
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


def _job_tts_voice(job_id: str, fallback: Optional[str] = None) -> str:
    try:
        meta = store.load_job(job_id).get("meta") or {}
        settings = meta.get("settings") or {}
        voice = settings.get("tts_voice")
        if isinstance(voice, str) and voice.strip():
            return normalize_tts_voice(voice)
    except Exception:  # noqa: BLE001
        pass
    if fallback:
        return normalize_tts_voice(fallback)
    return normalize_tts_voice(get_settings().tts_voice, fallback=DEFAULT_TTS_VOICE)


def _persist_job_tts_voice(job_id: str, voice: str) -> None:
    canonical = normalize_tts_voice(voice)
    try:
        meta_path = store.job_dir(job_id) / "meta.json"
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        settings = meta.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        settings["tts_voice"] = canonical
        meta["settings"] = settings
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _job_include_subtitles(job_id: str, fallback: bool = True) -> bool:
    try:
        meta = store.load_job(job_id).get("meta") or {}
        settings = meta.get("settings") or {}
        if "include_subtitles" in settings:
            return bool(settings.get("include_subtitles"))
    except Exception:  # noqa: BLE001
        pass
    return fallback


def _persist_job_include_subtitles(job_id: str, include: bool) -> None:
    try:
        meta_path = store.job_dir(job_id) / "meta.json"
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        settings = meta.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        settings["include_subtitles"] = bool(include)
        meta["settings"] = settings
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _job_include_audio(job_id: str, fallback: bool = True) -> bool:
    try:
        meta = store.load_job(job_id).get("meta") or {}
        settings = meta.get("settings") or {}
        if "include_audio" in settings:
            return bool(settings.get("include_audio"))
    except Exception:  # noqa: BLE001
        pass
    return fallback


def _persist_job_include_audio(job_id: str, include: bool) -> None:
    try:
        meta_path = store.job_dir(job_id) / "meta.json"
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        settings = meta.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        settings["include_audio"] = bool(include)
        meta["settings"] = settings
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _job_language(job_id: str, fallback: str = DEFAULT_LANGUAGE) -> str:
    try:
        meta = store.load_job(job_id).get("meta") or {}
        settings = meta.get("settings") or {}
        lang = settings.get("language")
        if isinstance(lang, str) and lang.strip():
            return normalize_language(lang)
    except Exception:  # noqa: BLE001
        pass
    return normalize_language(fallback)


def _persist_job_language(job_id: str, language: str) -> None:
    canonical = normalize_language(language)
    try:
        meta_path = store.job_dir(job_id) / "meta.json"
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        settings = meta.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        settings["language"] = canonical
        meta["settings"] = settings
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _job_production_options_confirmed(job_id: str) -> bool:
    try:
        meta = store.load_job(job_id).get("meta") or {}
        settings = meta.get("settings") or {}
        return bool(settings.get("production_options_confirmed"))
    except Exception:  # noqa: BLE001
        return False


def _persist_production_options_confirmed(job_id: str, confirmed: bool) -> None:
    try:
        meta_path = store.job_dir(job_id) / "meta.json"
        if not meta_path.exists():
            return
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        settings = meta.get("settings")
        if not isinstance(settings, dict):
            settings = {}
        settings["production_options_confirmed"] = bool(confirmed)
        meta["settings"] = settings
        meta_path.write_text(json.dumps(meta, indent=2), encoding="utf-8")
    except Exception:  # noqa: BLE001
        pass


def _mux_scene_vo(
    video_path: str,
    audio_path: Optional[str],
    output_path: Path,
    *,
    job_id: str,
    narration: str = "",
) -> Optional[str]:
    """Mux narration + burn-in subtitles (defaults from job settings).

    Muxes to a scratch file and swaps it in, so a compose running in parallel
    (from another scene's edit) can never read a half-written clip.
    """
    if not _job_include_audio(job_id, fallback=True):
        audio_path = None
    output_path = Path(output_path)
    staged = output_path.with_name(
        f"{output_path.stem}.{uuid.uuid4().hex[:8]}.staging{output_path.suffix}"
    )
    try:
        muxed = mux_scene_audio(
            video_path,
            audio_path,
            staged,
            subtitle_text=narration,
            burn_subtitles=_job_include_subtitles(job_id, fallback=True),
        )
        if not muxed or not staged.exists() or staged.stat().st_size == 0:
            return None
        os.replace(staged, output_path)
        return str(output_path)
    finally:
        staged.unlink(missing_ok=True)
        staged.with_suffix(".srt").unlink(missing_ok=True)


def _job_length_preset(job_id: str, fallback: str = "standard") -> str:
    try:
        meta = store.load_job(job_id).get("meta") or {}
        settings = meta.get("settings") or {}
        preset = settings.get("length_preset")
        if isinstance(preset, str) and preset in {"short", "standard", "deep"}:
            return preset
    except Exception:  # noqa: BLE001
        pass
    return fallback


def _job_scene_pacing(job_id: str, fallback: str = "balanced") -> str:
    try:
        meta = store.load_job(job_id).get("meta") or {}
        settings = meta.get("settings") or {}
        pacing = settings.get("scene_pacing")
        if isinstance(pacing, str) and pacing in {"short", "balanced", "long"}:
            return pacing
    except Exception:  # noqa: BLE001
        pass
    return fallback


def _job_audience(job_id: str, fallback: str = "general") -> str:
    try:
        meta = store.load_job(job_id).get("meta") or {}
        settings = meta.get("settings") or {}
        audience = settings.get("audience")
        if isinstance(audience, str) and audience in {"hs", "undergrad", "general"}:
            return audience
    except Exception:  # noqa: BLE001
        pass
    return fallback


def _load_plan(job_id: str) -> ScenePlan:
    job = store.load_job(job_id)
    plan_data = job.get("scene_plan")
    if not plan_data:
        raise ValueError(f"No scene plan for job {job_id}")
    return ScenePlan.model_validate(plan_data)


def _carry_forward_plan_fields(job_id: str, plan: ScenePlan) -> ScenePlan:
    """Restore fields an editing client omitted rather than deliberately cleared.

    The storyboard editor sends back the scene fields it renders, so a plan that
    round-trips through it arrives with no blueprint, no recurring_elements, and
    no covers_steps. Those drive codegen's visual consistency and the teaching
    each scene owes, so losing them on a title edit quietly degrades every scene
    generated afterwards.
    """
    try:
        stored = _load_plan(job_id)
    except Exception:  # noqa: BLE001 — first save, nothing to carry forward
        return plan

    update: dict[str, Any] = {}
    if plan.blueprint is None and stored.blueprint is not None:
        update["blueprint"] = stored.blueprint
    if not plan.recurring_elements and stored.recurring_elements:
        update["recurring_elements"] = stored.recurring_elements

    prior_steps = {s.id: s.covers_steps for s in stored.scenes if s.covers_steps}
    if prior_steps:
        scenes = [
            scene
            if scene.covers_steps or scene.id not in prior_steps
            else scene.model_copy(update={"covers_steps": prior_steps[scene.id]})
            for scene in plan.scenes
        ]
        if any(a is not b for a, b in zip(scenes, plan.scenes)):
            update["scenes"] = scenes
    return plan.model_copy(update=update) if update else plan


def update_scene_plan(job_id: str, plan: ScenePlan) -> ScenePlan:
    """Persist an edited plan and per-scene section.json files."""
    with job_runner.plan_lock(job_id):
        plan = _carry_forward_plan_fields(job_id, plan)
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


def update_scene_section(
    job_id: str,
    scene_id: str,
    section: SceneSection,
) -> ScenePlan:
    """Replace one scene in the saved plan, leaving every other scene alone.

    Scene edits run concurrently with each other and with the main pipeline, so
    a read-modify-write of the whole plan would silently revert a sibling
    scene's edit. Only the named scene is touched, and the whole cycle happens
    under the plan lock.
    """
    with job_runner.plan_lock(job_id):
        plan = _load_plan(job_id)
        scenes = [s for s in plan.scenes]
        replaced = False
        for i, existing in enumerate(scenes):
            if existing.id == scene_id:
                # The editor doesn't render covers_steps; an edit that omits it
                # is not a request to detach the scene from the teaching plan.
                if not section.covers_steps and existing.covers_steps:
                    section = section.model_copy(
                        update={"covers_steps": existing.covers_steps}
                    )
                scenes[i] = section
                replaced = True
                break
        if not replaced:
            scenes.append(section)
        plan = plan.model_copy(update={"scenes": scenes})
        store.save_scene_plan(job_id, plan.model_dump())
        store.save_scene_section(job_id, scene_id, section.model_dump())
    return plan


def patch_scene_section(
    job_id: str,
    scene_id: str,
    *,
    title: Optional[str] = None,
    narration: Optional[str] = None,
    visual_description: Optional[str] = None,
    duration_seconds: Optional[float] = None,
    visual_device: Optional[str] = None,
    camera_notes: Optional[str] = None,
    beats: Optional[list[dict[str, Any]]] = None,
) -> ScenePlan:
    """Apply a partial edit to one scene; every other scene stays as-is."""
    plan = _load_plan(job_id)
    existing = next((s for s in plan.scenes if s.id == scene_id), None)
    if existing is None:
        raise ValueError(f"Scene {scene_id} not found")
    data = existing.model_dump()
    if title is not None:
        data["title"] = title
    if visual_description is not None:
        data["visual_description"] = visual_description
    if duration_seconds is not None:
        data["duration_seconds"] = duration_seconds
    if visual_device is not None:
        data["visual_device"] = visual_device
    if camera_notes is not None:
        data["camera_notes"] = camera_notes
    if beats is not None:
        data["beats"] = beats
    elif narration is not None:
        data["narration"] = narration
        data["animation_beats"] = existing.animation_beats
        data.pop("beats", None)
    section = SceneSection.model_validate(data)
    return update_scene_section(job_id, scene_id, section)


def update_job_settings(
    job_id: str,
    *,
    tts_voice: Optional[str] = None,
    language: Optional[str] = None,
    include_audio: Optional[bool] = None,
    include_subtitles: Optional[bool] = None,
) -> dict[str, Any]:
    """Persist narrator / language / mux flags on the job before render."""
    if tts_voice is not None:
        _persist_job_tts_voice(job_id, tts_voice)
    if language is not None:
        _persist_job_language(job_id, language)
    if include_audio is not None:
        _persist_job_include_audio(job_id, include_audio)
    if include_subtitles is not None:
        _persist_job_include_subtitles(job_id, include_subtitles)
    if include_audio is not None and include_subtitles is not None:
        _persist_production_options_confirmed(job_id, True)
    confirmed = _job_production_options_confirmed(job_id)
    return {
        "job_id": job_id,
        "tts_voice": _job_tts_voice(job_id),
        "language": _job_language(job_id),
        "include_audio": _job_include_audio(job_id),
        "include_subtitles": _job_include_subtitles(job_id),
        "production_options_confirmed": confirmed,
    }


def require_production_options(job_id: str) -> None:
    if not _job_production_options_confirmed(job_id):
        raise ProductionOptionsRequired(PRODUCTION_OPTIONS_REQUIRED_MSG)


def prepare_production_options(
    job_id: str, request: Optional[ContinueRequest] = None
) -> None:
    """Persist continue-body flags, then refuse if the user has not chosen yet."""
    if request is not None:
        if request.tts_voice:
            _persist_job_tts_voice(job_id, request.tts_voice)
        if request.language:
            _persist_job_language(job_id, request.language)
        if request.include_audio is not None:
            _persist_job_include_audio(job_id, request.include_audio)
        if request.include_subtitles is not None:
            _persist_job_include_subtitles(job_id, request.include_subtitles)
        if request.include_audio is not None and request.include_subtitles is not None:
            _persist_production_options_confirmed(job_id, True)
    require_production_options(job_id)


def job_codegen_spec(job_id: str, scene_id: str) -> dict[str, Any]:
    """Prompt pack so a host LLM can write Manim for one scene (no OpenRouter)."""
    require_production_options(job_id)
    plan = _load_plan(job_id)
    index = next((i for i, s in enumerate(plan.scenes) if s.id == scene_id), None)
    if index is None:
        raise ValueError(f"Scene {scene_id} not found")
    scene = plan.scenes[index]
    return codegen_spec_payload(
        plan=plan,
        scene=scene,
        previous_context=_plan_previous_context(plan, index),
        next_context=_plan_next_context(plan, index),
        language=_job_language(job_id),
    )


def _preview_host_scene(job_id: str, scene_id: str, code: str) -> dict[str, Any]:
    """Last-frame still + layout-guard notes. Never fails the code save."""
    work = store.scene_dir(job_id, scene_id) / "_preview"
    work.mkdir(parents=True, exist_ok=True)
    frame_path: Optional[str] = None
    log = ""
    try:
        frame_path, log = preview_scene_frame(
            code, work_dir=work, scene_id=scene_id
        )
    except Exception as exc:  # noqa: BLE001
        log = str(exc)
    layout_issues = parse_layout_report(log or "")
    preview_path: Optional[str] = None
    if frame_path and Path(frame_path).exists():
        saved = store.save_vlm_review(
            job_id,
            scene_id,
            revision=0,
            review={
                "approved": not layout_issues,
                "issues": layout_issues[:8],
                "clarity_score": None,
                "notes": (
                    "Last-frame preview for the host model. Describe this image "
                    "to the user before writing the next scene."
                ),
                "review_mode": "host_preview",
            },
            frame_path=frame_path,
            frame_source="host_preview",
        )
        preview_path = saved.get("frame_url")
    shutil.rmtree(work, ignore_errors=True)
    return {
        "preview_path": preview_path,
        "layout_issues": layout_issues,
        "preview_error": None
        if preview_path
        else (log or "No preview frame")[-800:],
    }


def submit_host_scene_code(job_id: str, scene_id: str, code: str) -> dict[str, Any]:
    """Validate and persist host-authored Manim for a scene, then still-preview it."""
    require_production_options(job_id)
    plan = _load_plan(job_id)
    scene = next((s for s in plan.scenes if s.id == scene_id), None)
    if scene is None:
        raise ValueError(f"Scene {scene_id} not found")
    cleaned = clean_manim_code(code)
    ok, err = validate_manim_code(cleaned)
    if not ok:
        raise ValueError(err)
    store.save_code(job_id, scene_id, cleaned, revision=0)
    warnings = lint_scene_code(cleaned, target_duration=float(scene.duration_seconds))
    preview = _preview_host_scene(job_id, scene_id, cleaned)
    with_code = [s.id for s in plan.scenes if store.load_code(job_id, s.id)]
    missing = [s.id for s in plan.scenes if s.id not in with_code]
    return {
        "ok": True,
        "job_id": job_id,
        "scene_id": scene_id,
        "lint_warnings": warnings,
        "scenes_with_code": with_code,
        "scenes_missing_code": missing,
        "ready_to_render": not missing,
        "saved_count": len(with_code),
        "total_scenes": len(plan.scenes),
        **preview,
    }


def revise_scene_plan(job_id: str, instructions: str) -> ScenePlan:
    """Ask the AI planner to add/remove/reorder/rewrite scenes in an existing
    plan based on a free-text instruction, then persist the result.

    Used from the storyboard editor before generation starts (job is still
    `awaiting_plan`); does not touch any already-rendered scene artifacts.
    """
    settings = get_settings()
    client = OpenRouterClient(settings)
    job = store.load_job(job_id)
    meta = job.get("meta") or {}
    owner_id = meta.get("user_id") if isinstance(meta, dict) else None
    if isinstance(owner_id, str) and owner_id:
        db.assert_within_quotas(owner_id, need_tokens=6_000)

    plan = _load_plan(job_id)
    revised = _revise_plan_llm(
        client,
        plan,
        instructions,
        length_preset=_job_length_preset(job_id),
        scene_pacing=_job_scene_pacing(job_id),
        audience=_job_audience(job_id),
        language=_job_language(job_id),
    )
    update_scene_plan(job_id, revised)

    if isinstance(owner_id, str) and owner_id:
        db.flush_client_usage(
            user_id=owner_id,
            job_id=job_id,
            usage_log=client.drain_usage_log(),
        )
    return revised


# Render/syntax failures get a much bigger dedicated retry budget than
# timing/VLM-clarity revisions: a scene that raises e.g. SyntaxError must
# keep getting fixed rather than being dropped from the final video.
MAX_RENDER_FIX_ATTEMPTS = 10


def _process_one_scene(
    *,
    client: Optional[OpenRouterClient],
    job_id: str,
    work_dir: Path,
    plan: ScenePlan,
    scene: SceneSection,
    index: int,
    total: int,
    previous_context: str,
    next_context: str = "",
    resolution: str,
    skip_render: bool,
    on_event: Optional[EventCallback],
    creative_direction: str = "",
    tts_voice: Optional[str] = None,
    skip_vlm_review: bool = False,
    provided_code: Optional[str] = None,
) -> SceneArtifact:
    """TTS-first → codegen (timed) → render → optional VLM for a single scene."""
    settings = get_settings()
    voice = tts_voice or _job_tts_voice(job_id)
    language = _job_language(job_id)
    include_audio = _job_include_audio(job_id, fallback=True)
    store.save_scene_section(job_id, scene.id, scene.model_dump())
    _emit(
        on_event,
        PipelineEventType.scene_start,
        f"Scene {index + 1}/{total}: {scene.title}",
        data={
            "scene_id": scene.id,
            "index": index,
            "job_id": job_id,
            "step": "scene.start",
            "title": scene.title,
            "detail": (scene.visual_description or "")[:280] or None,
        },
        job_id=job_id,
    )

    sdir = store.scene_dir(job_id, scene.id)

    _check_cancel(job_id)

    # --- TTS first so codegen can match narration length (unless audio disabled) ---
    # Gemini returns PCM→WAV (no ffmpeg); other providers may return MP3.
    audio_path: Optional[str] = None
    audio_skipped = False
    beat_seconds: list[float] = []
    if include_audio:
        _emit(
            on_event,
            PipelineEventType.status,
            f"Recording narration for {scene.id}…",
            data={
                "scene_id": scene.id,
                "job_id": job_id,
                "step": "scene.tts",
                "detail": (scene.narration or "")[:220],
            },
            job_id=job_id,
        )
        audio_path, audio_skipped, beat_seconds = synthesize_scene_narration(
            [b.narration for b in scene.beats],
            work_dir / "audio" / f"{scene.id}.wav",
            settings=settings,
            voice=voice,
        )
    else:
        audio_skipped = True
    if audio_path and Path(audio_path).exists():
        dest = sdir / f"audio{Path(audio_path).suffix.lower()}"
        shutil.copy2(audio_path, dest)
        target_duration = probe_duration(Path(audio_path)) or scene.duration_seconds
    else:
        target_duration = scene.duration_seconds

    # Persist the measured duration back onto the section — both the scene total
    # and, when TTS rendered each beat separately, how long each beat's own line
    # actually took. Codegen times the animation off these numbers, so measured
    # values here are the difference between the picture tracking the voiceover
    # and merely averaging it.
    scene_update: dict[str, Any] = {"duration_seconds": float(target_duration)}
    if beat_seconds and len(beat_seconds) == len(scene.beats):
        scene_update["beats"] = [
            b.model_copy(update={"audio_duration_seconds": float(seconds)})
            for b, seconds in zip(scene.beats, beat_seconds)
        ]
    scene = scene.model_copy(update=scene_update)
    store.save_scene_section(job_id, scene.id, scene.model_dump())

    if include_audio:
        tts_msg = (
            f"TTS for {scene.id}"
            + (
                " (skipped — TTS not configured)"
                if audio_skipped
                else f" · {target_duration:.1f}s"
            )
        )
    else:
        tts_msg = f"Audio disabled for {scene.id} · {target_duration:.1f}s from plan"
    _emit(
        on_event,
        PipelineEventType.scene_tts,
        tts_msg,
        data={
            "scene_id": scene.id,
            "audio_path": audio_path,
            "skipped": audio_skipped,
            "include_audio": include_audio,
            "target_duration": target_duration,
            "tts_voice": voice,
            "language": language,
            "job_id": job_id,
        },
        job_id=job_id,
    )

    _emit(
        on_event,
        PipelineEventType.status,
        (
            f"Using submitted Manim code for {scene.id} ({target_duration:.1f}s)…"
            if provided_code
            else f"Writing Manim code for {scene.id} ({target_duration:.1f}s)…"
        ),
        data={
            "scene_id": scene.id,
            "job_id": job_id,
            "step": "scene.codegen",
            "detail": (
                f"{scene.visual_device or 'animation'} · "
                f"{len(scene.animation_beats)} beats"
            ),
            "host_authored": bool(provided_code),
        },
        job_id=job_id,
    )
    host_code = bool((provided_code or "").strip())
    if host_code:
        skip_vlm_review = True
        code = clean_manim_code(provided_code or "")
        ok, err = validate_manim_code(code)
        if not ok:
            raise ValueError(f"Submitted Manim code for {scene.id} is invalid: {err}")
    else:
        if client is None:
            raise ValueError(
                f"No Manim code on disk for {scene.id}. Submit scene code first."
            )
        code = generate_scene_code(
            client,
            plan=plan,
            scene=scene,
            previous_context=previous_context,
            next_context=next_context,
            target_duration_seconds=target_duration,
            creative_direction=creative_direction,
            language=language,
        )
    store.save_code(job_id, scene.id, code, revision=0)
    _emit(
        on_event,
        PipelineEventType.scene_code,
        f"Generated Manim code for {scene.id} (target {target_duration:.1f}s)",
        data={
            "scene_id": scene.id,
            "code": code,
            "code_chars": len(code),
            "revision": 0,
            "job_id": job_id,
            "step": "scene.code_ready",
        },
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
    render_log = ""

    if not skip_render:
        _emit(
            on_event,
            PipelineEventType.status,
            f"Rendering {scene.id} with Manim…",
            data={
                "scene_id": scene.id,
                "job_id": job_id,
                "step": "scene.render",
                "revision": revision_count,
            },
            job_id=job_id,
        )
        video_path, frame_path, render_log = render_scene(
            code,
            work_dir=work_dir / "render" / scene.id,
            resolution=resolution,
            scene_id=f"{scene.id}_r{revision_count}",
        )

        while not host_code and not video_path and revision_count < MAX_RENDER_FIX_ATTEMPTS:
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
            _check_cancel(job_id)
            revision_count += 1
            _emit(
                on_event,
                PipelineEventType.scene_revise,
                f"Render failed, revising code for {scene.id} (attempt {revision_count})…",
                data={
                    "scene_id": scene.id,
                    "job_id": job_id,
                    "step": "scene.revise_render",
                    "revision": revision_count,
                    "detail": (render_log or "Unknown error")[-280:],
                },
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
                language=language,
            )
            store.save_code(job_id, scene.id, code, revision=revision_count)
            _emit(
                on_event,
                PipelineEventType.scene_code,
                f"Revised Manim code for {scene.id} (r{revision_count})",
                data={
                    "scene_id": scene.id,
                    "code": code,
                    "code_chars": len(code),
                    "revision": revision_count,
                    "job_id": job_id,
                    "step": "scene.code_ready",
                },
                job_id=job_id,
            )
            _emit(
                on_event,
                PipelineEventType.status,
                f"Re-rendering {scene.id} (r{revision_count})…",
                data={
                    "scene_id": scene.id,
                    "job_id": job_id,
                    "step": "scene.render",
                    "revision": revision_count,
                },
                job_id=job_id,
            )
            video_path, frame_path, render_log = render_scene(
                code,
                work_dir=work_dir / "render" / scene.id,
                resolution=resolution,
                scene_id=f"{scene.id}_r{revision_count}",
            )

        preview_note = None if video_path else render_log
        if host_code and not video_path and not skip_render:
            raise ValueError(
                f"Manim render failed for {scene.id}. Fix the submitted code and "
                f"call submit_scene_code again.\n{render_log[-1500:] if render_log else 'Unknown error'}"
            )
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

        # --- Resync animation timing against the actual narration length ---
        # A clean render whose PACING drifts from the audio is exactly what
        # produces "video freezes / goes silent while narration keeps talking".
        # Fix this BEFORE spending VLM-review budget on a mistimed clip.
        mismatch = None if host_code else _duration_mismatch(video_path, target_duration)
        resync_budget = max(0, settings.max_scene_revisions - revision_count)
        resync_attempts = 0
        while (not host_code) and mismatch is not None and resync_attempts < min(2, resync_budget):
            _check_cancel(job_id)
            resync_attempts += 1
            revision_count += 1
            diff = mismatch - target_duration
            _emit(
                on_event,
                PipelineEventType.scene_revise,
                f"Resyncing timing for {scene.id}: rendered {mismatch:.1f}s vs "
                f"narration {target_duration:.1f}s (attempt {resync_attempts})…",
                data={
                    "scene_id": scene.id,
                    "job_id": job_id,
                    "revision": revision_count,
                    "rendered_duration": mismatch,
                    "target_duration": target_duration,
                    "step": "scene.revise_timing",
                    "detail": (
                        f"Clip is {abs(diff):.1f}s too "
                        f"{'long' if diff > 0 else 'short'} — retiming beats."
                    ),
                },
                job_id=job_id,
            )
            rev_instructions = (
                f"TIMING MISMATCH (audio/video out of sync): the rendered clip runs "
                f"{mismatch:.1f}s but the fixed narration audio is {target_duration:.1f}s "
                f"({abs(diff):.1f}s too {'long' if diff > 0 else 'short'}). "
                f"{'Shorten' if diff > 0 else 'Lengthen'} the animation so TOTAL "
                f"self.play(run_time=...) + self.wait(...) time (excluding the final "
                f"0.5s hold) lands within 0.5s of {target_duration:.1f}s. Spread the "
                "change proportionally across every beat's run_time — never solve this "
                "with waits, pulse/opacity loops, repeated plays, or by deleting a "
                "beat. If run_time alone cannot cover it, add a substantive step (a new "
                "labeled annotation the narration mentions), not decorative motion. "
                "Keep the same visuals, layout, and beat order; only retime them."
            )
            prev_good = (code, video_path, frame_path, frame_source)
            code = revise_scene_code(
                client,
                code=code,
                scene=scene,
                revision_instructions=rev_instructions,
                target_duration_seconds=target_duration,
                surgical=True,
                language=language,
            )
            store.save_code(job_id, scene.id, code, revision=revision_count)
            _emit(
                on_event,
                PipelineEventType.scene_code,
                f"Retimed Manim code for {scene.id} (r{revision_count})",
                data={
                    "scene_id": scene.id,
                    "code": code,
                    "code_chars": len(code),
                    "revision": revision_count,
                    "job_id": job_id,
                    "step": "scene.code_ready",
                },
                job_id=job_id,
            )
            new_video_path, new_frame_path, render_log = render_scene(
                code,
                work_dir=work_dir / "render" / scene.id,
                resolution=resolution,
                scene_id=f"{scene.id}_r{revision_count}",
            )
            if new_video_path:
                video_path, frame_path = new_video_path, new_frame_path
                if frame_path:
                    frame_source = "manim_preview"
                preview_note = None
                mismatch = _duration_mismatch(video_path, target_duration)
            else:
                # Retiming broke the render — keep the last playable clip and stop.
                code, video_path, frame_path, frame_source = prev_good
                mismatch = None
    else:
        preview_note = "Render skipped by request."

    # HITL regenerate: human is the reviewer — skip VLM + clarity auto-revise.
    if skip_vlm_review:
        review = VlmReview(
            approved=True,
            issues=[],
            revision_instructions="Skipped (HITL regenerate)",
            confidence=1.0,
            clarity_score=0.8,
            misconception_risk=0.2,
        )
        saved = store.save_vlm_review(
            job_id,
            scene.id,
            revision=revision_count,
            review=review.model_dump(),
            frame_path=frame_path,
            frame_source=frame_source,
        )
        if saved.get("frame_url"):
            frame_urls.append(saved["frame_url"])
        reviews_log.append(
            {
                **review.model_dump(),
                "revision": revision_count,
                "frame_source": frame_source,
                "frame_url": saved.get("frame_url"),
                "review_mode": "hitl_skip",
            }
        )
        store.save_code(job_id, scene.id, code, revision=revision_count)
    else:
        review_frame_paths: list[str] = []

        def _ensure_preview_frame(rev: int) -> tuple[Optional[str], str]:
            """Return (frame_path, frame_source) for review; fall back to storyboard."""
            nonlocal frame_path, frame_source, review_frame_paths
            if video_path and Path(video_path).exists():
                review_frame_paths = extract_review_frames(
                    video_path, sdir / f"vlm_frames_r{rev}"
                )
                if review_frame_paths:
                    frame_path = review_frame_paths[-1]
                    frame_source = "manim_preview"
                    return frame_path, frame_source
            if frame_path and frame_source == "manim_preview":
                review_frame_paths = [frame_path]
                return frame_path, frame_source
            create_storyboard_frame(
                scene,
                output_path=sdir / f"vlm_r{rev}_plan_card.png",
            )
            frame_path = create_visual_preview(
                scene,
                output_path=sdir / f"vlm_r{rev}_preview.png",
            )
            frame_source = "visual_preview"
            review_frame_paths = [frame_path] if frame_path else []
            return frame_path, frame_source

        def _run_review(rev: int) -> Any:
            nonlocal frame_path, frame_source, review_frame_paths
            _ensure_preview_frame(rev)
            syntax_ok, syntax_err = validate_manim_code(code)
            use_image_vlm = frame_source == "manim_preview"
            result = review_scene(
                client,
                scene=scene,
                code=code,
                frame_path=frame_path if use_image_vlm else None,
                frame_paths=review_frame_paths if use_image_vlm else None,
                frame_source=frame_source if use_image_vlm else "visual_preview",
            )
            if not syntax_ok:
                result = result.model_copy(
                    update={
                        "approved": False,
                        "issues": [syntax_err, *result.issues],
                        "revision_instructions": f"Fix invalid Python ({syntax_err}).",
                    }
                )
            else:
                # Geometry the render actually measured. The reviewer only sees
                # two sampled frames and routinely misses a label that collides
                # or a panel that leaves the frame mid-scene; these are facts,
                # so they override an approval.
                layout_issues = parse_layout_report(render_log)
                if layout_issues:
                    result = result.model_copy(
                        update={
                            "approved": False,
                            "issues": [*layout_issues, *result.issues],
                            "revision_instructions": "\n\n".join(
                                part
                                for part in (
                                    layout_revision_instructions(layout_issues),
                                    result.revision_instructions,
                                )
                                if part.strip()
                            ),
                        }
                    )
            saved = store.save_vlm_review(
                job_id,
                scene.id,
                revision=rev,
                review=result.model_dump(),
                frame_path=frame_path,
                frame_source=frame_source,
            )
            if saved.get("frame_url"):
                frame_urls.append(saved["frame_url"])
            reviews_log.append(
                {
                    **result.model_dump(),
                    "revision": rev,
                    "frame_source": frame_source,
                    "frame_url": saved.get("frame_url"),
                    "frame_count": len(review_frame_paths),
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
                f"Scene check for {scene.id}"
                + (
                    f" · clarity {result.clarity_score:.0%}"
                    if hasattr(result, "clarity_score")
                    else ""
                )
                + (f" · r{rev}" if rev else ""),
                data={
                    **result.model_dump(),
                    "scene_id": scene.id,
                    "job_id": job_id,
                    "frame_url": saved.get("frame_url"),
                    "frame_source": frame_source,
                    "revision": rev,
                },
                job_id=job_id,
            )
            return result

        review = _run_review(0)

        # Keep-best: never ship a revision that scores worse than a prior attempt.
        best: dict[str, Any] = {
            "code": code,
            "video_path": video_path,
            "frame_path": frame_path,
            "frame_source": frame_source,
            "review": review,
            "clarity": _review_clarity(review),
            "preview_note": preview_note,
            "revision": 0,
        }
        stagnant = 0
        max_stagnant = 1

        # Auto-revise cluttered / rejected scenes (shares MAX_SCENE_REVISIONS budget).
        while (
            settings.enable_auto_vlm_revise
            and revision_count < settings.max_scene_revisions
            and _needs_visual_revision(
                review, clarity_threshold=settings.vlm_clarity_threshold
            )
        ):
            revision_count += 1
            rev_instructions = _revision_instructions_from_review(review)
            _emit(
                on_event,
                PipelineEventType.scene_revise,
                f"Auto-revising {scene.id} for clarity (attempt {revision_count})…",
                data={
                    "scene_id": scene.id,
                    "job_id": job_id,
                    "revision": revision_count,
                    "clarity_score": getattr(review, "clarity_score", None),
                    "best_clarity": best["clarity"],
                    "step": "scene.revise_clarity",
                    "detail": (rev_instructions or "")[:280],
                },
                job_id=job_id,
            )
            # Always revise from the best known code — not a worse intermediate rewrite.
            code = revise_scene_code(
                client,
                code=best["code"],
                scene=scene,
                revision_instructions=rev_instructions,
                target_duration_seconds=target_duration,
                surgical=True,
                language=language,
            )
            store.save_code(job_id, scene.id, code, revision=revision_count)
            _emit(
                on_event,
                PipelineEventType.scene_code,
                f"Clarity-revised Manim code for {scene.id} (r{revision_count})",
                data={
                    "scene_id": scene.id,
                    "code": code,
                    "code_chars": len(code),
                    "revision": revision_count,
                    "job_id": job_id,
                    "step": "scene.code_ready",
                },
                job_id=job_id,
            )

            if not skip_render:
                prev_video, prev_frame, prev_source = (
                    video_path,
                    frame_path,
                    frame_source,
                )
                video_path, frame_path, render_log = render_scene(
                    code,
                    work_dir=work_dir / "render" / scene.id,
                    resolution=resolution,
                    scene_id=f"{scene.id}_r{revision_count}",
                )
                if frame_path:
                    frame_source = "manim_preview"
                elif video_path is None:
                    # Render broke after a visual revise — try one render-focused fix
                    # if budget remains, else keep the last playable clip.
                    preview_note = render_log
                    if revision_count < settings.max_scene_revisions:
                        revision_count += 1
                        _emit(
                            on_event,
                            PipelineEventType.scene_revise,
                            f"Render broke after clarity fix — repairing {scene.id} "
                            f"(r{revision_count})…",
                            data={
                                "scene_id": scene.id,
                                "job_id": job_id,
                                "revision": revision_count,
                                "step": "scene.revise_render",
                                "detail": (render_log or "")[-280:],
                            },
                            job_id=job_id,
                        )
                        code = revise_scene_code(
                            client,
                            code=code,
                            scene=scene,
                            revision_instructions=(
                                "Manim render failed after a clarity fix. "
                                f"Error:\n{(render_log or '')[-500:]}\n"
                                "Fix so it renders; keep layout sparse and non-overlapping."
                            ),
                            target_duration_seconds=target_duration,
                            surgical=False,
                            render_error=(render_log or "")[-500:],
                            language=language,
                        )
                        store.save_code(
                            job_id, scene.id, code, revision=revision_count
                        )
                        _emit(
                            on_event,
                            PipelineEventType.scene_code,
                            f"Repaired Manim code for {scene.id} (r{revision_count})",
                            data={
                                "scene_id": scene.id,
                                "code": code,
                                "code_chars": len(code),
                                "revision": revision_count,
                                "job_id": job_id,
                                "step": "scene.code_ready",
                            },
                            job_id=job_id,
                        )
                        video_path, frame_path, render_log = render_scene(
                            code,
                            work_dir=work_dir / "render" / scene.id,
                            resolution=resolution,
                            scene_id=f"{scene.id}_r{revision_count}",
                        )
                        if frame_path:
                            frame_source = "manim_preview"
                        preview_note = None if video_path else render_log
                    if video_path is None and prev_video:
                        video_path, frame_path, frame_source = (
                            prev_video,
                            prev_frame,
                            prev_source,
                        )

            review = _run_review(revision_count)
            new_clarity = _review_clarity(review)
            if new_clarity > best["clarity"] + 0.02:
                best = {
                    "code": code,
                    "video_path": video_path,
                    "frame_path": frame_path,
                    "frame_source": frame_source,
                    "review": review,
                    "clarity": new_clarity,
                    "preview_note": preview_note,
                    "revision": revision_count,
                }
                stagnant = 0
            else:
                stagnant += 1
                # Restore best artifacts so the next attempt (or ship) uses them.
                code = best["code"]
                video_path = best["video_path"]
                frame_path = best["frame_path"]
                frame_source = best["frame_source"]
                preview_note = best["preview_note"]
                review = best["review"]
                _emit(
                    on_event,
                    PipelineEventType.status,
                    f"Kept best {scene.id} at clarity {best['clarity']:.0%} "
                    f"(r{best['revision']}; attempt {revision_count} did not improve)",
                    data={
                        "scene_id": scene.id,
                        "job_id": job_id,
                        "best_clarity": best["clarity"],
                        "attempt_clarity": new_clarity,
                        "revision": revision_count,
                    },
                    job_id=job_id,
                )
                if stagnant > max_stagnant:
                    break

        # Ship the best revision we saw (may be r0).
        code = best["code"]
        video_path = best["video_path"]
        frame_path = best["frame_path"]
        frame_source = best["frame_source"]
        preview_note = best["preview_note"]
        review = best["review"]
        store.save_code(job_id, scene.id, code, revision=best["revision"])

    approved = bool(getattr(review, "approved", False))
    issues = list(getattr(review, "issues", None) or [])

    # Mux narration immediately so the UI can play a finished clip per scene
    # (don't wait for the whole pipeline / final compose).
    if video_path:
        muxed = _mux_scene_vo(
            video_path,
            audio_path,
            sdir / "scene_vo.mp4",
            job_id=job_id,
            narration=scene.narration,
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
    client: Optional[OpenRouterClient],
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
    revised = [
        a.scene_id
        for a in artifacts
        if a.revision_count > 0
    ]
    unapproved = [a.scene_id for a in artifacts if not a.vlm_approved]
    if settings.enable_auto_vlm_revise:
        notes = (
            f"Auto VLM revise enabled (clarity < {settings.vlm_clarity_threshold:.0%}). "
            f"Scenes revised: {', '.join(revised) or 'none'}. "
            f"Still unapproved: {', '.join(unapproved) or 'none'}."
        )
    else:
        notes = "Automated VLM revisions disabled (ENABLE_AUTO_VLM_REVISE=false)."
    debug = {"notes": notes, "scene_fixes": [], "revised_scenes": revised}
    store.save_final_debug(job_id, debug)
    _emit(
        on_event,
        PipelineEventType.final_debug,
        notes,
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
        # Take each scene's lock in turn so a user edit that lands mid-compose
        # is either fully included or fully excluded — never half-written.
        with job_runner.scene_lock(job_id, art.scene_id):
            vo_path = store.scene_dir(job_id, art.scene_id) / "scene_vo.mp4"
            # Prefer an already-muxed VO clip so we don't burn subtitles twice.
            if vo_path.exists() and vo_path.stat().st_size > 0:
                muxed_clips.append(str(vo_path))
                art.video_url = store.publish_scene_video(
                    job_id, art.scene_id, str(vo_path)
                )
                continue
            muxed = _mux_scene_vo(
                art.video_path,
                art.audio_path,
                vo_path,
                job_id=job_id,
                narration=art.narration,
            )
            if muxed:
                muxed_clips.append(muxed)
                art.video_url = store.publish_scene_video(job_id, art.scene_id, muxed)

    with job_runner.compose_lock(job_id):
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
        if client is not None:
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


_HEX_COLOR_RE = re.compile(r"#[0-9A-Fa-f]{6}\b")
_TEXT_LABEL_RE = re.compile(r"""\bText\(\s*["']([^"'\n]{1,40})["']""")


def _extract_visual_summary(code: str, *, max_items: int = 6) -> str:
    """Deterministic fingerprint of what a scene's REAL code actually rendered:
    hex colors used and on-screen Text labels. This is cheaper and more
    reliable for cross-scene continuity than pasting a raw code excerpt into
    the next scene's prompt and hoping the model parses it correctly.
    """
    if not code:
        return ""
    body = scene_body(code)
    colors = list(dict.fromkeys(_HEX_COLOR_RE.findall(body)))[:max_items]
    labels = list(dict.fromkeys(_TEXT_LABEL_RE.findall(body)))[:max_items]
    bits = []
    if colors:
        bits.append("colors used: " + ", ".join(colors))
    if labels:
        bits.append("on-screen labels used: " + ", ".join(f'"{l}"' for l in labels))
    return "; ".join(bits)


def _plan_previous_context(
    plan: ScenePlan,
    index: int,
    artifacts: Optional[dict[int, SceneArtifact]] = None,
) -> str:
    """Continuity context for codegen.

    Gives a brief plan-level history of every earlier scene, plus — since
    generation is sequential — a compact, deterministic fingerprint (colors +
    on-screen labels actually rendered) of the scene immediately before this
    one. That reflects what really rendered, not just what the plan intended,
    without the bulk/ambiguity of pasting a raw code excerpt.
    """
    parts: list[str] = []
    for scene in plan.scenes[:index]:
        desc = (scene.visual_description or "")[:180]
        parts.append(f"- {scene.id}: {scene.title} — {desc}")
    history = "\n".join(parts)

    prev = artifacts.get(index - 1) if artifacts and index > 0 else None
    if not prev or not (prev.code or "").strip():
        return history

    summary = _extract_visual_summary(prev.code)
    last_line = (prev.narration or "").strip()[-220:]
    detail_lines = [
        "\n\nImmediately previous scene — what was ACTUALLY rendered for "
        f"{prev.scene_id} (match this, not just the plan, so this scene continues "
        "it naturally instead of starting from an unrelated state):",
        f'Ended narration on: "...{last_line}"',
    ]
    if summary:
        detail_lines.append(summary[0].upper() + summary[1:] + ".")
    detail = "\n".join(detail_lines)
    return (history + detail) if history else detail.lstrip("\n")


def _plan_next_context(plan: ScenePlan, index: int) -> str:
    """Brief look-ahead at the following scene, for a smoother hand-off beat."""
    if index + 1 >= len(plan.scenes):
        return ""
    nxt = plan.scenes[index + 1]
    desc = (nxt.visual_description or "")[:160]
    opener = (nxt.narration or "")[:120]
    return f"- {nxt.id}: {nxt.title} — {desc}\n  opens with: \"{opener}\""


def _duration_mismatch(
    video_path: Optional[str],
    target_duration: float,
    *,
    abs_tol: float = 1.2,
    rel_tol: float = 0.12,
) -> Optional[float]:
    """Return the actual rendered duration if it drifts too far from the
    narration's target duration, else None. Drift here is exactly what causes
    the video to freeze on a stale frame or run silently past the voiceover.
    """
    if not video_path or not Path(video_path).exists() or target_duration <= 0:
        return None
    actual = probe_duration(Path(video_path))
    if actual <= 0:
        return None
    tolerance = max(abs_tol, target_duration * rel_tol)
    if abs(actual - target_duration) > tolerance:
        return actual
    return None


def _load_existing_scene_artifact(
    job_id: str, scene: SceneSection
) -> Optional[SceneArtifact]:
    """Reuse a finished scene so resume/reconnect does not burn tokens again."""
    sdir = store.scene_dir(job_id, scene.id)
    code_path = sdir / "code_final.py"
    vo = sdir / "scene_vo.mp4"
    raw = sdir / "scene.mp4"
    video_path = vo if vo.exists() else (raw if raw.exists() else None)
    if not code_path.exists() or video_path is None:
        return None
    frame_url = None
    for frame in sorted(sdir.glob("vlm_r*_frame.*"), reverse=True):
        frame_url = f"/api/jobs/{job_id}/file/scenes/{scene.id}/{frame.name}"
        break
    video_url = f"/api/jobs/{job_id}/file/scenes/{scene.id}/{video_path.name}"
    return SceneArtifact(
        scene_id=scene.id,
        title=scene.title,
        narration=scene.narration,
        code=code_path.read_text(encoding="utf-8"),
        revision_count=0,
        vlm_approved=True,
        vlm_issues=[],
        video_path=str(video_path),
        video_url=video_url,
        preview_note="Reused existing scene artifact",
        audio_path=(
            str(p) if (p := _scene_audio_file(sdir)) is not None else None
        ),
        vlm_frame_urls=[frame_url] if frame_url else [],
        artifact_dir=str(sdir),
    )


def _run_scenes_loop(
    *,
    client: Optional[OpenRouterClient],
    job_id: str,
    plan: ScenePlan,
    resolution: str,
    skip_render: bool,
    user_id: Optional[str],
    prompt: str,
    on_event: Optional[EventCallback],
    tts_voice: Optional[str] = None,
    skip_codegen: bool = False,
    skip_vlm: bool = False,
) -> GenerateResult:
    settings = get_settings()
    voice = tts_voice or _job_tts_voice(job_id)
    work_dir = store.job_dir(job_id)
    total = len(plan.scenes)
    results: dict[int, SceneArtifact] = {}
    to_run: list[tuple[int, SceneSection]] = []

    for index, scene in enumerate(plan.scenes):
        existing = None if skip_render else _load_existing_scene_artifact(job_id, scene)
        if existing is not None:
            results[index] = existing
            _emit(
                on_event,
                PipelineEventType.scene_done,
                f"Reusing finished {scene.id}",
                data={
                    "scene_id": scene.id,
                    "title": scene.title,
                    "job_id": job_id,
                    "video_url": existing.video_url,
                    "frame_url": (
                        existing.vlm_frame_urls[-1]
                        if existing.vlm_frame_urls
                        else None
                    ),
                    "vlm_approved": existing.vlm_approved,
                    "revision_count": existing.revision_count,
                    "reused": True,
                },
                job_id=job_id,
            )
        else:
            to_run.append((index, scene))

    def _flush_client(c: Optional[OpenRouterClient]) -> None:
        if not user_id or c is None:
            return
        db.flush_client_usage(
            user_id=user_id,
            job_id=job_id,
            usage_log=c.drain_usage_log(),
        )

    if skip_codegen:
        missing = [
            scene.id
            for _, scene in to_run
            if not store.load_code(job_id, scene.id)
        ]
        if missing:
            raise ValueError(
                "Submit Manim code for every scene before rendering. Missing: "
                + ", ".join(missing)
            )

    if to_run:
        _emit(
            on_event,
            PipelineEventType.status,
            f"Generating {len(to_run)} scene(s) in order — each builds on the "
            "one before it…",
            data={
                "job_id": job_id,
                "pending": [s.id for _, s in to_run],
                "reused": [plan.scenes[i].id for i in sorted(results)],
                "tts_voice": voice,
            },
            job_id=job_id,
        )

    # Strictly sequential: scenes are narratively/visually dependent on one
    # another, so scene N+1's codegen needs scene N's ACTUAL generated code
    # and narration (see _plan_previous_context) — running them in parallel
    # would mean every scene only ever sees the static plan, never what its
    # predecessor really produced.
    for index, scene in to_run:
        _check_cancel(job_id)
        # Claim the scene so a user edit on *this* scene is rejected while it is
        # being built. Scenes already finished stay unlocked and editable.
        with job_runner.scene_lock(job_id, scene.id):
            artifact = _process_one_scene(
                client=client,
                job_id=job_id,
                work_dir=work_dir,
                plan=plan,
                scene=scene,
                index=index,
                total=total,
                previous_context=_plan_previous_context(plan, index, results),
                next_context=_plan_next_context(plan, index),
                resolution=resolution,
                skip_render=skip_render,
                on_event=on_event,
                tts_voice=voice,
                skip_vlm_review=skip_vlm or skip_codegen,
                provided_code=store.load_code(job_id, scene.id) if skip_codegen else None,
            )
        results[index] = artifact
        _flush_client(client)

    artifacts = [results[i] for i in range(total)]
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
    host_plan = request.scene_plan
    need_llm = host_plan is None or not request.plan_only
    client = OpenRouterClient(settings) if need_llm else None
    job_id = uuid.uuid4().hex[:12]
    work_dir = store.init_job(
        job_id,
        prompt=request.prompt,
        settings_snapshot={
            "model": settings.openrouter_model_manim,
            "vlm_model": settings.openrouter_vlm_model,
            "enable_manim_render": settings.enable_manim_render,
            "max_scene_revisions": settings.max_scene_revisions,
            "enable_auto_vlm_revise": settings.enable_auto_vlm_revise,
            "vlm_clarity_threshold": settings.vlm_clarity_threshold,
            "resolution": request.resolution,
            "skip_render": request.skip_render,
            "length_preset": request.length_preset,
            "scene_pacing": request.scene_pacing,
            "audience": request.audience,
            "language": request.language,
            "plan_only": request.plan_only,
            "production_options_confirmed": not request.plan_only,
            "host_authored": host_plan is not None,
            **(
                {
                    "tts_voice": request.tts_voice,
                    "include_audio": request.include_audio,
                    "include_subtitles": request.include_subtitles,
                }
                if not request.plan_only
                else {}
            ),
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
        if not user_id or client is None:
            return
        db.flush_client_usage(
            user_id=user_id,
            job_id=job_id,
            usage_log=client.drain_usage_log(),
        )

    def _plan_progress(message: str, data: dict[str, Any]) -> None:
        _emit(
            on_event,
            PipelineEventType.status,
            message,
            data={"job_id": job_id, **data},
            job_id=job_id,
        )

    if host_plan is not None:
        plan = host_plan
        _emit(
            on_event,
            PipelineEventType.status,
            f"Using host-authored storyboard ({len(plan.scenes)} scenes)…",
            data={"job_id": job_id, "step": "planning.host", "scene_count": len(plan.scenes)},
            job_id=job_id,
        )
    else:
        _emit(
            on_event,
            PipelineEventType.status,
            f"Working out how to explain this… (job {job_id})",
            data={"job_id": job_id, "step": "blueprint.start"},
            job_id=job_id,
        )

        # Step 0 — decide the teaching itself (question, running example, notation and
        # its visual encoding, the order the relations are earned) before any scene
        # exists. Planning straight to scenes improvises those choices one scene at a
        # time, which is what makes a video look right and still explain nothing.
        min_scenes, max_scenes = scene_count_range(
            request.length_preset, request.scene_pacing
        )
        try:
            blueprint = create_teaching_blueprint(
                client,
                request.prompt,
                audience=request.audience,
                audience_guidance=AUDIENCE_GUIDANCE.get(
                    request.audience, AUDIENCE_GUIDANCE["general"]
                ),
                language=request.language,
                # One step per scene is the target: the planner may merge two small
                # steps or split a big one, but a blueprint far off the scene budget
                # forces it into an awkward staging.
                min_steps=max(3, min_scenes),
                max_steps=max(4, max_scenes),
                on_progress=_plan_progress,
            )
        except Exception as e:  # noqa: BLE001
            # The planner still teaches on its own — a video planned without the
            # blueprint beats no video, so this degrades rather than fails.
            blueprint = None
            _emit(
                on_event,
                PipelineEventType.status,
                "Could not build a teaching plan — planning scenes directly.",
                data={"job_id": job_id, "step": "blueprint.failed", "detail": str(e)[:400]},
                job_id=job_id,
            )
        _flush_usage()
        _emit(
            on_event,
            PipelineEventType.status,
            (
                f"Storyboarding {len(blueprint.steps)} teaching steps into scenes…"
                if blueprint
                else "Planning scenes from prompt…"
            ),
            data={
                "job_id": job_id,
                "step": "planning.start",
                "step_count": len(blueprint.steps) if blueprint else 0,
                "core_question": blueprint.core_question if blueprint else None,
                "teaching_steps": (
                    [f"{s.id}: {s.claim}" for s in blueprint.steps] if blueprint else None
                ),
            },
            job_id=job_id,
        )

        plan = create_scene_plan(
            client,
            request.prompt,
            length_preset=request.length_preset,
            scene_pacing=request.scene_pacing,
            audience=request.audience,
            language=request.language,
            blueprint=blueprint,
            on_progress=_plan_progress,
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
        "scene_pacing": request.scene_pacing,
        "audience": request.audience,
        "language": request.language,
        "production_options_confirmed": not request.plan_only,
    }
    if not request.plan_only:
        plan_payload["tts_voice"] = request.tts_voice
        plan_payload["include_audio"] = request.include_audio
        plan_payload["include_subtitles"] = request.include_subtitles
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
        tts_voice=request.tts_voice,
    )


def job_is_host_authored(job_id: str) -> bool:
    """True when the storyboard (and usually Manim) came from the MCP host LLM."""
    try:
        job = store.load_job(job_id)
    except FileNotFoundError:
        return False
    meta = job.get("meta") or {}
    snap = meta.get("settings") if isinstance(meta, dict) else {}
    return bool(isinstance(snap, dict) and snap.get("host_authored"))


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
    job = store.load_job(job_id)
    meta = job.get("meta") or {}
    snap = meta.get("settings") if isinstance(meta, dict) else {}
    host_authored = bool(isinstance(snap, dict) and snap.get("host_authored"))
    prepare_production_options(job_id, request)
    # MCP host already wrote the Manim. Never construct OpenRouter on that path,
    # even if the continue body omitted skip_codegen (FastAPI default body).
    skip_codegen = bool(request.skip_codegen or host_authored)
    skip_vlm = bool(request.skip_vlm or host_authored or skip_codegen)
    client = None if skip_codegen else OpenRouterClient(settings)
    prompt = str(meta.get("prompt") or "")
    owner = meta.get("user_id") if isinstance(meta, dict) else None
    if user_id and owner and owner != user_id:
        raise PermissionError("Not job owner")

    plan = _load_plan(job_id)
    resolution = request.resolution or _job_resolution(job_id)
    skip_render = request.skip_render
    tts_voice = _job_tts_voice(job_id, fallback=request.tts_voice)

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
        data={"job_id": job_id, "title": plan.title, "tts_voice": tts_voice},
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
        tts_voice=tts_voice,
        skip_codegen=skip_codegen,
        skip_vlm=skip_vlm,
    )


def _recompose_final(
    job_id: str,
    plan: ScenePlan,
    *,
    on_event: Optional[EventCallback] = None,
) -> Optional[str]:
    """Restitch final.mp4 from whatever scene clips are on disk right now.

    Called after a single-scene edit. Skipped while the main pipeline is still
    building scenes: it would stitch a half-finished video, and the pipeline
    composes the real one from the same clips when it finishes anyway.
    """
    if job_runner.is_pipeline_running(job_id):
        _emit(
            on_event,
            PipelineEventType.status,
            "Scene updated — the full video will refresh once generation finishes.",
            data={"job_id": job_id, "final_deferred": True},
        )
        return None

    with job_runner.compose_lock(job_id):
        muxed_clips: list[str] = []
        for s in plan.scenes:
            # A sibling scene mid-edit still contributes its current clip —
            # scene clips are swapped in atomically, so this reads either the
            # old or the new one, and that editor recomposes when it lands.
            cand = store.scene_dir(job_id, s.id) / "scene_vo.mp4"
            if not cand.exists():
                cand = store.scene_dir(job_id, s.id) / "scene.mp4"
            if cand.exists():
                muxed_clips.append(str(cand))
        if not muxed_clips:
            return None
        compose_final_video(muxed_clips, store.job_dir(job_id) / "final.mp4")
    return f"/api/jobs/{job_id}/file/final.mp4"


def regenerate_scene(
    job_id: str,
    scene_id: str,
    request: Optional[RegenerateSceneRequest] = None,
    *,
    on_event: Optional[EventCallback] = None,
) -> dict[str, Any]:
    """Regenerate a single scene from scratch (not a comment retouch).

    Skips VLM review and clarity auto-revise — the human is the reviewer.
    """
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

    # Keep the plan in sync if the section was edited — scene-scoped so a
    # sibling scene being edited in parallel keeps its own changes.
    plan = update_scene_section(job_id, scene_id, scene)

    resolution = _job_resolution(job_id)
    prev_parts = [
        f"- {s.id}: {s.title}" for s in plan.scenes if s.id != scene_id
    ]
    index = next(
        (i for i, s in enumerate(plan.scenes) if s.id == scene_id), 0
    )

    with job_runner.scene_lock(job_id, scene_id):
        artifact = _process_one_scene(
            client=client,
            job_id=job_id,
            work_dir=store.job_dir(job_id),
            plan=plan,
            scene=scene,
            index=index,
            total=len(plan.scenes),
            previous_context="\n".join(prev_parts),
            next_context=_plan_next_context(plan, index),
            resolution=resolution,
            skip_render=request.skip_render,
            on_event=on_event,
            creative_direction=request.direction,
            tts_voice=_job_tts_voice(job_id),
            skip_vlm_review=True,
        )

        # Mux + refresh final if we have video
        video_url = artifact.video_url
        if artifact.video_path:
            muxed = _mux_scene_vo(
                artifact.video_path,
                artifact.audio_path,
                store.scene_dir(job_id, scene_id) / "scene_vo.mp4",
                job_id=job_id,
                narration=artifact.narration,
            )
            if muxed:
                video_url = store.publish_scene_video(job_id, scene_id, muxed)

    final_url = _recompose_final(job_id, plan, on_event=on_event)

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
    comment_id: Optional[str] = None,
    on_event: Optional[Any] = None,
) -> dict[str, Any]:
    """Retouch/revise ONLY a specific scene based on human feedback.

    Holds only *this* scene's lock, so retouching scene 1 runs happily beside a
    retouch of scene 2 or the pipeline still building scene 4.
    """
    with job_runner.scene_lock(job_id, scene_id):
        return _retouch_scene_locked(
            job_id,
            scene_id,
            human_instructions,
            timestamp=timestamp,
            comment_id=comment_id,
            on_event=on_event,
        )


def _retouch_scene_locked(
    job_id: str,
    scene_id: str,
    human_instructions: str,
    *,
    timestamp: Optional[float] = None,
    comment_id: Optional[str] = None,
    on_event: Optional[Any] = None,
) -> dict[str, Any]:
    settings = get_settings()
    client = OpenRouterClient(settings=settings)

    def emit(msg: str, data: Optional[dict] = None) -> None:
        if on_event:
            # Every event carries scene_id so a UI watching several concurrent
            # edits can route each line to the right scene.
            on_event(
                PipelineEvent(
                    type=PipelineEventType.status,
                    message=msg,
                    data={"scene_id": scene_id, "job_id": job_id, **(data or {})},
                )
            )

    emit(f"Loading scene data for '{scene_id}'…")

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
    marked_frame = store.load_comment_frame_bytes(job_id, scene_id, comment_id)
    rev_instructions = human_instructions
    if timestamp is not None:
        rev_instructions = (
            f"[At timestamp {timestamp:.1f}s in the scene]: {human_instructions}. "
            "Adjust the animation beat closest to that moment."
        )
    if marked_frame:
        rev_instructions += (
            " The learner marked the attached screenshot — that is the exact "
            "frame they want changed."
        )

    emit(
        f"AI is reading your feedback and revising the Manim code for '{scene_sec.title}'…",
        {"scene_id": scene_id, "instructions": rev_instructions},
    )

    retry_count = 0
    max_retries = settings.max_scene_revisions
    target_duration = scene_sec.duration_seconds
    audio_file = _scene_audio_file(store.scene_dir(job_id, scene_id))
    if audio_file is not None:
        target_duration = probe_duration(audio_file) or target_duration

    language = _job_language(job_id)
    image_bytes = marked_frame[0] if marked_frame else None
    image_mime = marked_frame[1] if marked_frame else "image/jpeg"
    new_code = revise_scene_code(
        client,
        code=current_code,
        scene=scene_sec,
        revision_instructions=rev_instructions,
        target_duration_seconds=target_duration,
        language=language,
        image_bytes=image_bytes,
        image_mime=image_mime,
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
            language=language,
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
            language=language,
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
        if audio_file is None or not audio_file.exists():
            for candidate in (
                work_dir / "audio" / f"{scene_id}.wav",
                work_dir / "audio" / f"{scene_id}.mp3",
            ):
                if candidate.exists():
                    audio_file = candidate
                    break

        final_video_path = video_path
        muxed_path = sdir / "scene_vo.mp4"
        muxed = _mux_scene_vo(
            video_path,
            str(audio_file) if audio_file is not None and audio_file.exists() else None,
            muxed_path,
            job_id=job_id,
            narration=scene_sec.narration,
        )
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


def _iter_scene_task(
    job_id: str,
    scene_id: str,
    run: Callable[[EventCallback], None],
    *,
    label: str,
    timeout_seconds: float,
) -> Iterator[str]:
    """Run one scene edit on a tracked background task and stream its events.

    Each scene gets its own task key, so edits to different scenes run in
    parallel while a second edit of the *same* scene is refused instead of
    racing the first one's code revisions and renders.
    """
    from queue import Empty, Queue

    q: Queue[Optional[PipelineEvent]] = Queue()

    def on_event(event: PipelineEvent) -> None:
        q.put(event)

    def worker() -> None:
        try:
            run(on_event)
        except job_runner.SceneBusyError as exc:
            q.put(
                PipelineEvent(
                    type=PipelineEventType.error,
                    message=str(exc),
                    data={"error": "scene_busy", "scene_id": scene_id},
                )
            )
        except JobCancelledError as exc:
            q.put(
                PipelineEvent(
                    type=PipelineEventType.error,
                    message=str(exc),
                    data={"error": "cancelled", "scene_id": scene_id},
                )
            )
        except Exception as exc:  # noqa: BLE001
            q.put(
                PipelineEvent(
                    type=PipelineEventType.error,
                    message=str(exc),
                    data={"error": str(exc), "scene_id": scene_id},
                )
            )
        finally:
            q.put(None)

    started = job_runner.start_task(job_id, job_runner.scene_task_key(scene_id), worker)
    if not started:
        yield _sse(
            {
                "type": PipelineEventType.error.value,
                "message": (
                    f"Scene {scene_id} is already being edited — wait for that "
                    "change to finish before starting another."
                ),
                "data": {"error": "scene_busy", "scene_id": scene_id, "job_id": job_id},
            }
        )
        return

    # Short queue waits + SSE comments so Starlette's iterate_in_threadpool
    # releases the worker between polls (long .get() timeouts wedge the API).
    waited = 0.0
    while True:
        try:
            item = q.get(timeout=0.35)
        except Empty:
            waited += 0.35
            if waited >= timeout_seconds:
                yield _sse(
                    {
                        "type": PipelineEventType.error.value,
                        "message": f"{label} timed out",
                        "data": {"scene_id": scene_id, "job_id": job_id},
                    }
                )
                break
            yield ":\n\n"
            continue
        waited = 0.0
        if item is None:
            break
        yield _sse(item.model_dump())


def iter_retouch_scene(
    job_id: str,
    scene_id: str,
    human_instructions: str,
    timestamp: Optional[float] = None,
    comment_id: Optional[str] = None,
) -> Iterator[str]:
    """SSE stream of retouch progress events for a single scene."""

    def run(on_event: EventCallback) -> None:
        retouch_scene(
            job_id,
            scene_id,
            human_instructions,
            timestamp=timestamp,
            comment_id=comment_id,
            on_event=on_event,
        )

    yield from _iter_scene_task(
        job_id,
        scene_id,
        run,
        label="Retouch",
        timeout_seconds=300,
    )


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

    q: Queue[Optional[PipelineEvent]] = Queue()

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
        except JobCancelledError as exc:
            q.put(
                PipelineEvent(
                    type=PipelineEventType.error,
                    message=str(exc),
                    data={"error": "cancelled"},
                )
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
    waited = 0.0
    while True:
        try:
            item = q.get(timeout=0.35)
        except Empty:
            waited += 0.35
            if waited >= 600:
                yield _sse(
                    {
                        "type": PipelineEventType.error.value,
                        "message": "Pipeline timed out waiting for the next event",
                        "data": None,
                    }
                )
                break
            yield ":\n\n"
            continue
        waited = 0.0
        if item is None:
            break
        yield _sse(item.model_dump())


def iter_continue_events(
    job_id: str,
    request: Optional[ContinueRequest] = None,
    *,
    user_id: Optional[str] = None,
    after: Optional[int] = None,
) -> Iterator[str]:
    """
    Start (or attach to) scene generation detached from this SSE connection.
    Clients may disconnect and reconnect via iter_job_event_stream.
    """
    request = request or ContinueRequest()
    # Only stream events produced after this continue kickoff (unless attaching).
    start_after = job_runner.event_count(job_id) if after is None else max(0, after)

    def target() -> None:
        continue_pipeline(
            job_id, request, on_event=None, user_id=user_id
        )

    started = job_runner.start_job(job_id, target)
    yield _sse(
        {
            "type": PipelineEventType.status.value,
            "message": (
                f"Started scene generation for {job_id}"
                if started
                else f"Attached to in-flight job {job_id}"
            ),
            "data": {
                "job_id": job_id,
                "started": started,
                "running": job_runner.is_running(job_id),
                "after": start_after,
            },
        }
    )
    yield from iter_job_event_stream(job_id, after=start_after)


async def aiter_continue_events(
    job_id: str,
    request: Optional[ContinueRequest] = None,
    *,
    user_id: Optional[str] = None,
    after: Optional[int] = None,
) -> AsyncIterator[str]:
    """Async continue stream — job work stays on a daemon thread; SSE polls async."""
    request = request or ContinueRequest()
    start_after = (
        await asyncio.to_thread(job_runner.event_count, job_id)
        if after is None
        else max(0, after)
    )

    def target() -> None:
        continue_pipeline(job_id, request, on_event=None, user_id=user_id)

    started = await asyncio.to_thread(job_runner.start_job, job_id, target)
    yield _sse(
        {
            "type": PipelineEventType.status.value,
            "message": (
                f"Started scene generation for {job_id}"
                if started
                else f"Attached to in-flight job {job_id}"
            ),
            "data": {
                "job_id": job_id,
                "started": started,
                "running": job_runner.is_running(job_id),
                "after": start_after,
            },
        }
    )
    async for chunk in aiter_job_event_stream(job_id, after=start_after):
        yield chunk


def iter_job_event_stream(job_id: str, *, after: int = 0) -> Iterator[str]:
    """Tail durable job events (works across refresh / page changes)."""
    for ev in job_runner.iter_event_tail(job_id, after=after):
        yield _sse(ev)


def iter_regenerate_scene(
    job_id: str,
    scene_id: str,
    request: Optional[RegenerateSceneRequest] = None,
) -> Iterator[str]:
    def run(on_event: EventCallback) -> None:
        regenerate_scene(job_id, scene_id, request, on_event=on_event)

    yield from _iter_scene_task(
        job_id,
        scene_id,
        run,
        label="Regenerate",
        timeout_seconds=400,
    )


async def aiter_job_event_stream(job_id: str, *, after: int = 0) -> AsyncIterator[str]:
    """Async SSE tail — keeps the event loop free during idle polls."""
    async for ev in job_runner.aiter_event_tail(job_id, after=after):
        yield _sse(ev)


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

    narration = ""
    for s in scenes:
        if s.get("scene_id") == scene_id:
            narration = str(s.get("narration") or "")
            section = s.get("section") or {}
            if not narration and isinstance(section, dict):
                narration = str(section.get("narration") or "")
            break

    # Mux under this scene's lock only; the final stitch happens after it is
    # released so approvals of two different scenes never deadlock on each other.
    with job_runner.scene_lock(job_id, scene_id):
        audio_p = _scene_audio_file(sdir)
        muxed = _mux_scene_vo(
            str(scene_video),
            str(audio_p) if audio_p is not None else None,
            sdir / "scene_vo.mp4",
            job_id=job_id,
            narration=narration,
        )

    final_url = None
    if job_runner.is_pipeline_running(job_id):
        # Generation is still producing later scenes — it composes the final
        # video itself when it finishes, and this scene's clip is already in.
        pass
    else:
        with job_runner.compose_lock(job_id):
            muxed_clips: list[str] = []
            for s in scenes:
                sid = s["scene_id"]
                candidate = sdir.parent / sid / "scene_vo.mp4"
                if not candidate.exists():
                    candidate = sdir.parent / sid / "scene.mp4"
                if candidate.exists():
                    muxed_clips.append(str(candidate))
            if muxed_clips:
                compose_final_video(muxed_clips, store.job_dir(job_id) / "final.mp4")
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
