"""LLM actions on document blocks / slides."""

from __future__ import annotations

from pathlib import Path
from typing import Optional

from backend.documents.schemas import (
    DocumentAskAction,
    DocumentAskRequest,
    DocumentAskResult,
    DocumentBlock,
    DocumentManifest,
    DocumentSlide,
)
from backend.documents import store
from backend.llm import OpenRouterClient

_ACTION_PROMPTS: dict[DocumentAskAction, str] = {
    DocumentAskAction.explain: (
        "Explain the selected content clearly for a curious learner. "
        "Cover what it means, why it matters, and any key intuition."
    ),
    DocumentAskAction.explain_figure: (
        "Explain the selected figure/graph/image. Describe what it shows, "
        "axes or structure if present, the main takeaway, and any caveats."
    ),
    DocumentAskAction.comment: (
        "Respond helpfully to the user's comment about this selection. "
        "Be concrete and reference the selected content."
    ),
    DocumentAskAction.simplify: (
        "Rewrite/explain the selected content in simpler language without losing "
        "the core idea. Use short sentences and everyday analogies when useful."
    ),
    DocumentAskAction.translate: (
        "Translate and lightly clarify the selected content into the requested "
        "language. Keep technical terms accurate."
    ),
    DocumentAskAction.quiz: (
        "Create 3 short quiz questions (with brief answers) based on this "
        "selection/slide to check understanding."
    ),
    DocumentAskAction.deepen: (
        "Go deeper: add nuance, edge cases, and the next layer of understanding "
        "beyond what the slide states."
    ),
    DocumentAskAction.relate: (
        "Relate this selection to the rest of the document/slide context. "
        "How does it connect to surrounding ideas?"
    ),
    DocumentAskAction.critique: (
        "Critically review this content: gaps, ambiguities, assumptions, or "
        "places a learner might get confused. Be constructive."
    ),
    DocumentAskAction.summarize_slide: (
        "Summarize this slide in 4–7 bullets: main claim, supporting points, "
        "and one takeaway."
    ),
    DocumentAskAction.extract_formula: (
        "Identify and explain any formulas/equations/symbols in the selection. "
        "Define each symbol and state when the relation applies."
    ),
    DocumentAskAction.key_takeaways: (
        "List the key takeaways a student should remember from this selection."
    ),
    DocumentAskAction.misconceptions: (
        "List likely misconceptions a learner might form from this content, "
        "and correct each one briefly."
    ),
    DocumentAskAction.turn_into_video_prompt: (
        "Turn this selection/slide into a concise natural-language prompt for "
        "generating an educational Manim explainer video. Output ONLY the prompt."
    ),
    DocumentAskAction.freeform: (
        "Answer the user's question about the selected document content."
    ),
}


def ask_on_manifest(
    client: OpenRouterClient,
    manifest: DocumentManifest,
    request: DocumentAskRequest,
    *,
    root: Path,
) -> DocumentAskResult:
    slide = _find_slide(manifest, request.slide_id)
    block: Optional[DocumentBlock] = None
    if request.block_id:
        block = manifest.blocks.get(request.block_id)

    action = request.action
    if (
        action == DocumentAskAction.explain
        and block
        and block.type.value == "figure"
    ):
        action = DocumentAskAction.explain_figure

    is_follow_up = bool(
        (request.prior_reply and request.prior_reply.strip())
        or any(t.role == "assistant" for t in request.conversation)
    )
    system = (
        "You are NowIGetIt's document tutor. The user is studying an interactive "
        "HTML slide deck converted from a PDF/PPT/document. Be accurate, concise, "
        "and pedagogical. Prefer markdown.\n"
        "For mathematics, ALWAYS use LaTeX delimiters the UI can render: "
        "inline as $...$ and display as $$...$$ (never bare Unicode-only equations "
        "when a formula matters). If information is insufficient, say so."
    )
    if is_follow_up:
        system += (
            " The user is asking a FOLLOW-UP about your previous answer and/or the "
            "slide. Answer the new question directly; quote or refine prior points "
            "only when needed."
        )

    instruction = (
        "Answer the user's follow-up question using the prior answer and slide "
        "context."
        if is_follow_up and action == DocumentAskAction.freeform
        else _ACTION_PROMPTS[action]
    )
    user_bits = [
        f"Document title: {manifest.title}",
        f"Source file: {manifest.source_filename}",
        f"Slide: {slide.id} — {slide.title}",
        f"Action: {action.value}",
        f"Language for the reply: {request.language}",
        "",
        f"Instruction: {instruction}",
    ]
    if request.message.strip():
        user_bits.extend(["", f"User message: {request.message.strip()}"])

    if block:
        user_bits.extend(
            [
                "",
                f"Selected block id: {block.id}",
                f"Selected block type: {block.type.value}",
                f"Selected text:\n{block.text or '(empty)'}",
            ]
        )
    else:
        user_bits.extend(
            [
                "",
                "No specific block selected — use the whole slide.",
                f"Slide text:\n{slide.plain_text[:8000] or '(empty)'}",
            ]
        )

    # Light slide context always helps
    if block and slide.plain_text:
        user_bits.extend(
            ["", f"Full slide context (truncated):\n{slide.plain_text[:3500]}"]
        )

    if request.conversation:
        user_bits.append("")
        user_bits.append("Conversation so far:")
        for turn in request.conversation[-10:]:
            label = "User" if turn.role == "user" else "Assistant"
            user_bits.append(f"{label}: {turn.content[:6000]}")
    elif request.prior_reply and request.prior_reply.strip():
        user_bits.extend(
            [
                "",
                "Previous assistant answer the user is following up on:",
                request.prior_reply.strip()[:8000],
            ]
        )

    image_path = _resolve_image_path(root, block)
    use_vlm = action == DocumentAskAction.explain_figure or (
        image_path is not None
        and action
        in {
            DocumentAskAction.explain,
            DocumentAskAction.critique,
            DocumentAskAction.deepen,
            DocumentAskAction.freeform,
            DocumentAskAction.comment,
        }
    )

    if use_vlm and image_path and image_path.exists():
        mime = "image/png"
        if image_path.suffix.lower() in {".jpg", ".jpeg"}:
            mime = "image/jpeg"
        elif image_path.suffix.lower() == ".webp":
            mime = "image/webp"
        reply_raw = client.chat_with_image(
            system=system,
            prompt="\n".join(user_bits),
            image_bytes=image_path.read_bytes(),
            mime_type=mime,
            temperature=0.35,
            max_tokens=2500,
            json_mode=False,
        )
        reply = reply_raw if isinstance(reply_raw, str) else str(reply_raw)
    else:
        reply = client.chat(
            system=system,
            user="\n".join(user_bits),
            temperature=0.35,
            max_tokens=2500,
        )

    video_prompt = None
    if action == DocumentAskAction.turn_into_video_prompt:
        video_prompt = reply.strip()

    comment_id = None
    if request.save_as_comment:
        ann = store.add_annotation(
            manifest.doc_id,
            slide_id=slide.id,
            block_id=block.id if block else None,
            action=action.value,
            message=request.message,
            reply=reply,
            author="user+llm",
            pinned=True,
        )
        comment_id = ann.id

    return DocumentAskResult(
        doc_id=manifest.doc_id,
        slide_id=slide.id,
        block_id=block.id if block else None,
        action=action,
        reply=reply,
        comment_id=comment_id,
        video_prompt=video_prompt,
        user_message=request.message.strip(),
    )


def _find_slide(manifest: DocumentManifest, slide_id: str) -> DocumentSlide:
    for slide in manifest.slides:
        if slide.id == slide_id:
            return slide
    raise ValueError(f"Unknown slide_id: {slide_id}")


def _resolve_image_path(root: Path, block: Optional[DocumentBlock]) -> Optional[Path]:
    if not block:
        return None
    if block.image_path:
        path = root / block.image_path
        if path.exists():
            return path
    if block.image_url and "/file/assets/" in block.image_url:
        name = block.image_url.rsplit("/file/assets/", 1)[-1]
        path = root / "assets" / Path(name).name
        if path.exists():
            return path
    # Embedded data-URI images: materialize under assets/ for the VLM call
    if block.image_url and block.image_url.startswith("data:image/"):
        try:
            import base64
            import re

            m = re.match(
                r"data:image/(png|jpeg|jpg|gif|webp);base64,(.+)",
                block.image_url,
                flags=re.I | re.S,
            )
            if not m:
                return None
            ext = m.group(1).lower()
            if ext == "jpeg":
                ext = "jpg"
            raw = base64.b64decode(m.group(2))
            assets = root / "assets"
            assets.mkdir(parents=True, exist_ok=True)
            path = assets / f"ask_{block.id}.{ext}"
            path.write_bytes(raw)
            return path
        except Exception:  # noqa: BLE001
            return None
    return None
