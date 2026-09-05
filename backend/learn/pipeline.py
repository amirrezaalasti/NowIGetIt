"""Orchestrate podcast / quiz / interactive generation with SSE events."""

from __future__ import annotations

import json
import queue
import threading
from datetime import datetime, timezone
from typing import Any, Callable, Iterator, Optional

from backend import artifacts as base
from backend import supabase_db as db
from backend.documents.source import prepare_generation_prompt
from backend.learn import store
from backend.learn.interactive import apply_progress, generate_interactive_lesson
from backend.learn.podcast import generate_podcast_script, synthesize_podcast_audio
from backend.learn.quiz import generate_quiz_paper, grade_paper
from backend.learn.schemas import (
    InteractiveResult,
    LabProgressRequest,
    LabProgressResult,
    LearnGenerateRequest,
    LearnKind,
    PodcastResult,
    PodcastScript,
    QuizGradeRequest,
    QuizGradeResult,
    QuizResult,
)
from backend.llm import OpenRouterClient
from backend.pipeline.pedagogy import create_teaching_blueprint

EventCallback = Callable[[str, str, Optional[dict[str, Any]]], None]


def load_item(item_id: str) -> dict[str, Any]:
    payload = store.load_payload(item_id)
    urls = store.urls_for(item_id, payload)
    if urls.get("audio"):
        payload["audio_url"] = urls["audio"]
    return {
        "id": item_id,
        "kind": payload.get("kind") or store.infer_kind(item_id),
        "title": payload.get("title") or item_id,
        "status": payload.get("status") or "ready",
        "payload": payload,
        "progress": store.load_progress(item_id),
        "urls": urls,
    }


def run_learn(
    request: LearnGenerateRequest,
    *,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
    on_event: Optional[EventCallback] = None,
) -> dict[str, Any]:
    teaching_prompt, display_prompt, source_names = prepare_generation_prompt(
        request.prompt,
        request.source_doc_ids,
        user_id=user_id,
    )
    item_id = store.new_id(request.kind.value)
    settings = {**request.model_dump(), "source_filenames": source_names}
    store.init_item(
        item_id,
        kind=request.kind.value,
        prompt=display_prompt,
        settings=settings,
        user_id=user_id,
        user_email=user_email,
        user_name=user_name,
    )
    request = request.model_copy(update={"prompt": teaching_prompt})

    def emit(etype: str, message: str, data: Optional[dict[str, Any]] = None) -> None:
        event = {
            "type": etype,
            "message": message,
            "data": {"id": item_id, "kind": request.kind.value, **(data or {})},
        }
        base.append_event(item_id, event)
        if on_event:
            on_event(etype, message, event["data"])

    emit("start", "Working out how to teach this…", {"step": "blueprint.start"})
    client = OpenRouterClient()
    try:
        blueprint = create_teaching_blueprint(
            client,
            request.prompt,
            audience=request.audience,
            language=request.language,
            on_progress=lambda msg, data: emit("blueprint", msg, data),
        )
        created = datetime.now(timezone.utc).isoformat()

        if request.kind == LearnKind.podcast:
            payload = _run_podcast(
                client, request, blueprint, item_id, created, emit
            )
        elif request.kind == LearnKind.quiz:
            payload = _run_quiz(client, request, blueprint, item_id, created, emit)
        else:
            payload = _run_lab(client, request, blueprint, item_id, created, emit)

        store.save_payload(item_id, payload)
        if user_id:
            db.flush_client_usage(
                user_id=user_id,
                job_id=item_id,
                usage_log=client.drain_usage_log(),
            )
            db.sync_job_storage(
                user_id=user_id,
                job_id=item_id,
                job_path=store.item_dir(item_id),
            )
        emit("complete", "Ready.", {"step": "complete", "title": payload.get("title")})
        return load_item(item_id)
    except Exception as exc:  # noqa: BLE001
        store.patch_meta(item_id, status="error", error=str(exc))
        if user_id:
            db.upsert_job(
                job_id=item_id,
                user_id=user_id,
                prompt=display_prompt,
                status="error",
            )
            db.flush_client_usage(
                user_id=user_id,
                job_id=item_id,
                usage_log=client.drain_usage_log(),
            )
        emit("error", str(exc), {"step": "error"})
        raise


def _run_podcast(
    client: OpenRouterClient,
    request: LearnGenerateRequest,
    blueprint: Any,
    item_id: str,
    created: str,
    emit: EventCallback,
) -> dict[str, Any]:
    emit("script", "Writing the episode…", {"step": "podcast.script"})
    script = generate_podcast_script(
        client,
        request.prompt,
        blueprint,
        audience=request.audience,
        language=request.language,
        length_preset=request.length_preset,
        style=request.style,
        on_progress=lambda msg, data: emit("script", msg, data),
    )
    emit("tts", "Recording narration…", {"step": "podcast.tts"})
    audio_path, skipped, chapters = synthesize_podcast_audio(
        script,
        store.item_dir(item_id) / "podcast.wav",
        host_voice=request.partner_voice if request.style == "dialogue" else request.tts_voice,
        guide_voice=request.tts_voice,
        on_progress=lambda msg, data: emit("tts", msg, data),
    )
    script = PodcastScript.model_validate(
        {**script.model_dump(), "chapters": [c.model_dump() for c in chapters]}
    )
    duration = sum(c.duration_seconds for c in script.chapters)
    audio_url = None
    if audio_path:
        suffix = ".mp3" if str(audio_path).endswith(".mp3") else ".wav"
        audio_url = f"/api/jobs/{item_id}/file/podcast{suffix}"
    result = PodcastResult(
        id=item_id,
        title=script.title,
        prompt=request.prompt,
        status="ready",
        language=request.language,
        tts_voice=request.tts_voice,
        partner_voice=request.partner_voice,
        style=request.style,
        duration_seconds=duration,
        audio_url=audio_url,
        audio_skipped=skipped,
        script=script,
        blueprint=blueprint,
        takeaways=script.takeaways,
        created_at=created,
    )
    return result.model_dump()


def _run_quiz(
    client: OpenRouterClient,
    request: LearnGenerateRequest,
    blueprint: Any,
    item_id: str,
    created: str,
    emit: EventCallback,
) -> dict[str, Any]:
    emit("quiz", "Writing questions…", {"step": "quiz.llm"})
    paper = generate_quiz_paper(
        client,
        request.prompt,
        blueprint,
        audience=request.audience,
        language=request.language,
        question_count=request.question_count,
        difficulty=request.difficulty,
        on_progress=lambda msg, data: emit("quiz", msg, data),
    )
    result = QuizResult(
        id=item_id,
        title=paper.title,
        prompt=request.prompt,
        status="ready",
        language=request.language,
        difficulty=request.difficulty,
        paper=paper,
        blueprint=blueprint,
        created_at=created,
    )
    return result.model_dump()


def _run_lab(
    client: OpenRouterClient,
    request: LearnGenerateRequest,
    blueprint: Any,
    item_id: str,
    created: str,
    emit: EventCallback,
) -> dict[str, Any]:
    emit("lab", "Designing the lab…", {"step": "lab.llm"})
    lesson = generate_interactive_lesson(
        client,
        request.prompt,
        blueprint,
        audience=request.audience,
        language=request.language,
        on_progress=lambda msg, data: emit("lab", msg, data),
    )
    result = InteractiveResult(
        id=item_id,
        title=lesson.title,
        prompt=request.prompt,
        status="ready",
        language=request.language,
        lesson=lesson,
        blueprint=blueprint,
        created_at=created,
    )
    return result.model_dump()


def iter_learn_events(
    request: LearnGenerateRequest,
    *,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
) -> Iterator[str]:
    q: queue.Queue[Optional[str]] = queue.Queue()

    def encode(etype: str, message: str, data: Optional[dict[str, Any]] = None) -> str:
        return (
            f"data: {json.dumps({'type': etype, 'message': message, 'data': data})}\n\n"
        )

    def on_event(etype: str, message: str, data: Optional[dict[str, Any]] = None) -> None:
        q.put(encode(etype, message, data))

    def worker() -> None:
        try:
            item = run_learn(
                request,
                user_id=user_id,
                user_email=user_email,
                user_name=user_name,
                on_event=on_event,
            )
            q.put(encode("result", "Ready.", item))
        except Exception as exc:  # noqa: BLE001
            q.put(encode("error", str(exc), None))
        finally:
            q.put(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while True:
        item = q.get()
        if item is None:
            break
        yield item
    thread.join(timeout=1.0)


def grade_quiz_item(item_id: str, body: QuizGradeRequest) -> QuizGradeResult:
    payload = store.load_payload(item_id)
    if payload.get("kind") != "quiz":
        raise ValueError("not a quiz")
    quiz = QuizResult.model_validate(payload)
    result = grade_paper(quiz.paper, body.answers)
    result.id = item_id
    attempts = store.load_attempts(item_id)
    attempts.append(
        {
            "score": result.score,
            "correct_count": result.correct_count,
            "total": result.total,
            "passed": result.passed,
            "answers": [a.model_dump() for a in body.answers],
        }
    )
    store.save_attempts(item_id, attempts)
    return result


def check_lab_progress(item_id: str, body: LabProgressRequest) -> LabProgressResult:
    payload = store.load_payload(item_id)
    if payload.get("kind") != "interactive":
        raise ValueError("not an interactive lab")
    lab = InteractiveResult.model_validate(payload)
    saved = store.load_progress(item_id)
    baseline = saved.get("baseline") if isinstance(saved.get("baseline"), dict) else None
    result = apply_progress(
        lab.lesson,
        phase_id=body.phase_id or (lab.lesson.phases[0].id if lab.lesson.phases else ""),
        params=body.params,
        answers=body.answers,
        completed_phases=body.completed_phases or list(saved.get("completed_phases") or []),
        baseline=baseline,
    )
    result.id = item_id
    store.save_progress(
        item_id,
        {
            "phase_id": result.phase_id,
            "params": body.params,
            "answers": body.answers,
            "completed_phases": result.completed_phases,
            "baseline": baseline or body.params,
            "goal_met": result.goal_met,
        },
    )
    return result
