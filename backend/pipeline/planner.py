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

DENSITY / LAYOUT (critical — prevents messy overlapping frames):
- ONE primary visual idea per scene. Never pack a full multi-gate / multi-module
  system (e.g. all LSTM gates, full transformer stack) into a single scene.
- Split complex architectures across scenes: overview → component A → component B → …
- Per scene: at most 1 formula OR 1 dense diagram focus — not both fighting for space.
- Per animation beat: introduce at most 3 new on-screen labels/objects; fade or clear
  previous labels before the next dense beat when needed.
- Prefer short on-screen labels (≤3 words). Put long explanations in narration only.
- visual_description must name spatial zones (e.g. "title top; gate box center;
  one equation bottom") so codegen has a layout plan.
- animation_beats should say "clear previous labels" / "fade out prior formula"
  when advancing — but the FINAL beat must leave the core diagram + title on screen
  (never end on an empty frame).
- For neural nets / backprop: prefer sparse node columns or 3 labeled boxes; never
  ask for full weight matrices, many simultaneous equations, or crowded heatmaps.

- Pick ONE visual_device per scene from:
  number_line | unit_circle | before_after | particle_flow | equation_reveal |
  axes_graph | lattice_grid | morph_transform | house_section | comparison_split |
  labeled_box_flow | gate_mechanism | annotated_diagram
- Use labeled_box_flow / gate_mechanism / annotated_diagram for neural nets, pipelines,
  gates, cells, and other box+arrow systems (never improvise a crowded freeform diagram).
- style_tags: 2–4 lowercase keywords for template matching
  (e.g. ["particles","heatmap","house"], ["gate","sigmoid","lstm"], ["boxes","pipeline"]).
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
