"""Step 1: turn a user prompt into a structured JSON scene plan."""

from __future__ import annotations

from backend.llm import OpenRouterClient
from backend.schemas import ScenePlan

LENGTH_GUIDANCE = {
    "short": "Target ~45–60 seconds total. Prefer 3–4 scenes. Ruthlessly cut filler.",
    "standard": "Target under ~90 seconds unless the topic clearly needs more.",
    "deep": "Target ~2–3 minutes. Allow 5–8 scenes with progressive depth.",
}

AUDIENCE_GUIDANCE = {
    "hs": "High-school level: concrete metaphors, minimal jargon, everyday analogies.",
    "undergrad": "College intro level: precise terms OK when defined; show formal structure.",
    "general": "Curious adult audience: clear language, strong intuition, light formalism.",
}

PLANNER_SYSTEM = """You are an expert educational animation director (3Blue1Brown-caliber).
Given a learner's prompt, produce a JSON scene plan for a short explanatory video.

Rules:
- Break the explanation into sequential scenes based on complexity. Keep each scene
  simple enough for one short Manim class — one clear visual idea per scene.
- Each scene must include: id, title, narration, visual_description,
  animation_beats, duration_seconds, camera_notes, visual_device, style_tags.
- Narration: clear spoken English for TTS. Match duration_seconds to spoken length
  (~2.5 words/sec). Prefer progressive reveal: introduce → build intuition → summarize.
- Visuals: concrete Manim-friendly elements (shapes, graphs, equations as Text, arrows, labels).
- Pick ONE visual_device per scene from:
  number_line | unit_circle | before_after | particle_flow | equation_reveal |
  axes_graph | lattice_grid | morph_transform | house_section | comparison_split
- style_tags: 2–4 lowercase keywords for template matching
  (e.g. ["particles","heatmap","house"], ["axes","parabola","tangent"]).
- visual_identity: one sentence describing the overall look (metaphor + mood).
- palette: object with background, accent, text, highlight as hex colors.
  Prefer a distinctive non-default palette (avoid generic purple). Dark educational
  backgrounds like #0f1115 / #0B0C10 work well with warm accents.
- style_notes: concrete Manim direction (colors to use, typography feel, motion style).
- JSON strings must be valid: escape every backslash as \\\\ (write \\\\frac not \\frac).
  Prefer plain-text math words over LaTeX (e.g. "x squared" over "x^2").

Return ONLY a JSON object with this shape:
{
  "title": string,
  "concept_summary": string,
  "style_notes": string,
  "visual_identity": string,
  "palette": {
    "background": "#0f1115",
    "accent": "#e8a87c",
    "text": "#f2f2f2",
    "highlight": "#85dcb8"
  },
  "scenes": [
    {
      "id": "scene_1",
      "title": string,
      "narration": string,
      "visual_description": string,
      "animation_beats": [string],
      "duration_seconds": number,
      "camera_notes": string,
      "visual_device": string,
      "style_tags": [string]
    }
  ]
}
"""


def create_scene_plan(
    client: OpenRouterClient,
    prompt: str,
    *,
    length_preset: str = "standard",
    audience: str = "general",
) -> ScenePlan:
    length = LENGTH_GUIDANCE.get(length_preset, LENGTH_GUIDANCE["standard"])
    aud = AUDIENCE_GUIDANCE.get(audience, AUDIENCE_GUIDANCE["general"])
    user = f"""Learner prompt:
{prompt}

Length preset ({length_preset}): {length}
Audience ({audience}): {aud}
"""
    data = client.chat_json(
        system=PLANNER_SYSTEM,
        user=user,
        temperature=0.4,
        max_tokens=4096,
    )
    return ScenePlan.model_validate(data)
