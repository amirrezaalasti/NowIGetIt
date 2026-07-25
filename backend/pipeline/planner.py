"""Step 1: turn a user prompt into a structured JSON scene plan."""

from __future__ import annotations

from backend.llm import OpenRouterClient
from backend.schemas import ScenePlan

PLANNER_SYSTEM = """You are an expert educational animation director.
Given a learner's prompt, produce a JSON scene plan for a short explanatory video.

Rules:
- Break the explanation into an appropriate number of sequential scenes based on the complexity of the user's prompt. Keep each scene simple
  enough to implement in one short Manim class — one clear visual idea per scene.
- Each scene must include: id, title, narration (spoken voiceover), visual_description,
  animation_beats (short list), duration_seconds, camera_notes.
- Narration should be clear spoken English suitable for text-to-speech.
- Visuals should be concrete Manim-friendly elements (shapes, graphs, equations, arrows, labels).
- Keep total runtime under ~90 seconds unless the topic clearly needs more.
- Prefer progressive reveal: introduce, build intuition, then summarize.
- JSON strings must be valid: escape every backslash as \\\\ (write \\\\frac not \\frac).
  Prefer plain-text math words over LaTeX when possible (e.g. "x squared" over "x^2").

Return ONLY a JSON object with this shape:
{
  "title": string,
  "concept_summary": string,
  "style_notes": string,
  "scenes": [
    {
      "id": "scene_1",
      "title": string,
      "narration": string,
      "visual_description": string,
      "animation_beats": [string],
      "duration_seconds": number,
      "camera_notes": string
    }
  ]
}
"""


def create_scene_plan(client: OpenRouterClient, prompt: str) -> ScenePlan:
    data = client.chat_json(
        system=PLANNER_SYSTEM,
        user=f"Learner prompt:\n{prompt}",
        temperature=0.4,
        max_tokens=4096,
    )
    return ScenePlan.model_validate(data)
