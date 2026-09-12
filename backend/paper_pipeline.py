"""Automated paper → explainer video → optional YouTube publish."""

from __future__ import annotations

from collections.abc import Iterator
from typing import Any, Optional

from backend import artifacts as store
from backend.pipeline.orchestrator import (
    JobCancelledError,
    PipelineEvent,
    PipelineEventType,
    _sse,
    run_pipeline,
)
from backend.schemas import GenerateRequest
from backend.user_settings import apply_user_settings
from backend.youtube import publish_job, public_status

DEFAULT_PAPER_PROMPT = (
    "Create a clear explainer video of the attached research paper or notes. "
    "Cover the problem, why it matters, the key idea, how the method works, "
    "and the takeaway. Stay faithful to the source: keep its claims, notation, "
    "and examples. Assume a technical but non-specialist audience unless the "
    "learner prompt says otherwise."
)


def compose_paper_prompt(prompt: str) -> str:
    text = (prompt or "").strip()
    if not text:
        return DEFAULT_PAPER_PROMPT
    return (
        f"{text}\n\n"
        "Teach FROM the attached paper/PDF. Do not invent a different topic."
    )


def iter_paper_pipeline_events(
    request: GenerateRequest,
    *,
    user_id: str,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
    auto_publish: bool = False,
    youtube_privacy: str = "unlisted",
    youtube_title: Optional[str] = None,
    youtube_description: Optional[str] = None,
) -> Iterator[str]:
    from queue import Empty, Queue
    from threading import Thread

    q: Queue[Optional[PipelineEvent]] = Queue()
    job_id_box: dict[str, str] = {}

    def on_event(event: PipelineEvent) -> None:
        data = event.data if isinstance(event.data, dict) else {}
        jid = data.get("job_id")
        if isinstance(jid, str) and jid:
            job_id_box["id"] = jid
        q.put(event)

    def worker() -> None:
        try:
            apply_user_settings(user_id)
            req = request.model_copy(
                update={
                    "prompt": compose_paper_prompt(request.prompt),
                    "plan_only": False,
                    "kind": "paper_pipeline",
                }
            )
            on_event(
                PipelineEvent(
                    type=PipelineEventType.status,
                    message="Paper pipeline: generating explainer video…",
                    data={"step": "paper.start", "auto_publish": auto_publish},
                )
            )
            run_pipeline(
                req,
                on_event=on_event,
                user_id=user_id,
                user_email=user_email,
                user_name=user_name,
            )
            job_id = job_id_box.get("id")
            if job_id:
                store.patch_job_meta(job_id, kind="paper_pipeline")
            if auto_publish:
                if not job_id:
                    raise RuntimeError("Paper pipeline finished without a job id")
                yt = public_status(user_id)
                if not yt.get("connected"):
                    on_event(
                        PipelineEvent(
                            type=PipelineEventType.status,
                            message="Video is ready. Connect YouTube in Settings to publish.",
                            data={
                                "job_id": job_id,
                                "step": "paper.needs_youtube",
                            },
                        )
                    )
                    return
                on_event(
                    PipelineEvent(
                        type=PipelineEventType.status,
                        message="Uploading to YouTube…",
                        data={"job_id": job_id, "step": "paper.publish"},
                    )
                )
                published = publish_job(
                    user_id=user_id,
                    job_id=job_id,
                    title=youtube_title,
                    description=youtube_description,
                    privacy=youtube_privacy,
                )
                on_event(
                    PipelineEvent(
                        type=PipelineEventType.complete,
                        message=f"Published to YouTube: {published.get('url')}",
                        data={
                            "job_id": job_id,
                            "step": "paper.published",
                            "youtube": published,
                        },
                    )
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
            if waited >= 900:
                yield _sse(
                    {
                        "type": PipelineEventType.error.value,
                        "message": "Paper pipeline timed out waiting for the next event",
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
