"""Code-first review when Manim isn't rendered; image VLM only for real frames."""

from __future__ import annotations

from pathlib import Path

from backend.llm import OpenRouterClient
from backend.schemas import SceneSection, VlmReview

CODE_REVIEW_SYSTEM = """You are a ManimGL code reviewer for educational animations.
Manim was NOT rendered — you only see Python code + the intended scene brief.
Do NOT complain about missing pixels, empty frames, or inspection overlays.
Do NOT ask to "render the frame" or "display graphical elements in the image".

Approve if the code looks complete and would plausibly produce the intended scene.
Reject only for real code problems:
- syntax errors / truncated code / non-Python commentary mixed into the file
- missing Scene class or construct()
- clear API misuse that would crash (MathTex, Wait(), hallucinated methods)
- scene clearly misses core visual beats from the brief
- dangerous/incomplete expressions cut mid-line

Also score teaching quality (0–1):
- clarity_score: how clearly the code would teach the concept
- misconception_risk: how likely a learner is to walk away confused

Return JSON:
{
  "approved": boolean,
  "issues": [string],
  "revision_instructions": string,
  "confidence": number,
  "clarity_score": number,
  "misconception_risk": number
}
"""

IMAGE_VLM_SYSTEM = """You are a strict visual QA reviewer for educational Manim animations.
A REAL rendered preview frame is attached (not a text storyboard).
Compare the frame + code against the intended scene description.

Approve only if the frame clearly shows the intended concept.
Flag: missing objects, clutter/overlap, wrong math, illegible text, uneven/broken
letter spacing inside words, empty frame, off-brief.

Also score teaching quality (0–1):
- clarity_score: how clearly the frame teaches the concept
- misconception_risk: how likely a learner is to walk away confused

Return JSON:
{
  "approved": boolean,
  "issues": [string],
  "revision_instructions": string,
  "confidence": number,
  "clarity_score": number,
  "misconception_risk": number
}
"""


def review_scene(
    client: OpenRouterClient,
    *,
    scene: SceneSection,
    code: str,
    frame_path: str | None = None,
    frame_source: str = "none",
) -> VlmReview:
    prompt = f"""Scene title: {scene.title}
Intended visual description:
{scene.visual_description}

Animation beats:
{chr(10).join(f"- {b}" for b in scene.animation_beats)}

Narration (context only):
{scene.narration}

Manim code:
```python
{code}
```
"""
    # Only use vision when we have a true Manim preview.
    if (
        frame_source == "manim_preview"
        and frame_path
        and Path(frame_path).exists()
    ):
        image_bytes = Path(frame_path).read_bytes()
        data = client.chat_with_image(
            system=IMAGE_VLM_SYSTEM,
            prompt=prompt + "\nA real rendered preview frame is attached.",
            image_bytes=image_bytes,
            mime_type="image/png" if frame_path.endswith(".png") else "image/jpeg",
            json_mode=True,
        )
        assert isinstance(data, dict)
        return VlmReview.model_validate(data)

    data = client.chat_json(
        system=CODE_REVIEW_SYSTEM,
        user=prompt
        + "\nNOTE: frame_source="
        + frame_source
        + ". Review CODE ONLY. Storyboard/plan cards are not failures.",
        temperature=0.15,
        max_tokens=2048,
    )
    return VlmReview.model_validate(data)


FINAL_DEBUG_SYSTEM = """You are the final QA editor for a multi-scene educational video.
Review the full plan and scene codes (rendering may be disabled).
Focus on code completeness, continuity across scenes, and narration coverage.
Do not request pixel-perfect frames if Manim was not rendered.
Only suggest scene_fixes for serious code defects.
Return JSON:
{
  "ok": boolean,
  "notes": string,
  "scene_fixes": [{"scene_id": string, "instructions": string}]
}
"""


def final_debug_pass(
    client: OpenRouterClient,
    *,
    plan_json: str,
    scene_summaries: str,
) -> dict:
    return client.chat_json(
        system=FINAL_DEBUG_SYSTEM,
        user=f"Scene plan JSON:\n{plan_json}\n\nBuilt scenes:\n{scene_summaries}",
        temperature=0.2,
        max_tokens=3072,
    )
