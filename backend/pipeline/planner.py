"""Step 1: turn a user prompt into a structured JSON scene plan."""

from __future__ import annotations

from backend.languages import language_display_name, normalize_language
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
- LANGUAGE (critical): Write title, concept_summary, narration, visual_description,
  and animation_beats in the requested output language. On-screen labels implied by
  the plan must also be in that language. Keep visual_device / style_tags in English
  (they are machine keys). Prefer progressive reveal: introduce → build intuition → summarize.
- Narration: clear spoken script for TTS in the output language. Match duration_seconds
  to spoken length (~2.5 words/sec for Latin scripts; ~3–4 syllables/sec for others).
- Visuals: concrete Manim-friendly elements (shapes, graphs, equations as Text, arrows, labels).

MOTION + LAYOUT (critical — scenes must animate the idea, not show a still poster):
- ONE primary visual idea per scene. Never pack a full multi-gate / multi-module
  system (e.g. all LSTM gates, full transformer stack) into a single scene.
- Split complex architectures across scenes: overview → component A → component B → …
- Every visual must map to the concept. Ban decorative filler (random Circle↔Square
  morphs, unexplained floating polygons).
- Each scene needs 3–6 animation_beats that describe MOTION, e.g.
  "draw axes", "Create the curve", "Dot slides to the minimum", "GrowArrow for gradient",
  "highlight the active path", "formula fades in". Avoid beats that only say "show X".
- Per beat: introduce at most ~3 new labels/objects; fade prior labels when needed.
- Prefer short UI labels (≤3 words). Formulas must stay COMPLETE. Put long prose in
  narration only (it will appear as subtitles).
- visual_description must name spatial zones AND the motion arc
  (e.g. "title top; gate box center builds internals; equation bottom").
- The FINAL beat must leave the core diagram + title on screen (never an empty frame).
- For neural nets / backprop: sparse node columns or 3 labeled boxes with path
  highlights — never full weight matrices or crowded heatmaps.

- Pick ONE visual_device per scene from:
  number_line | unit_circle | before_after | particle_flow | equation_reveal |
  axes_graph | lattice_grid | morph_transform | house_section | comparison_split |
  labeled_box_flow | gate_mechanism | annotated_diagram | path_trace | vector_field |
  angle_tracker | boolean_sets
- Use labeled_box_flow / gate_mechanism / annotated_diagram for neural nets, pipelines,
  gates, cells, and other box+arrow systems (never improvise a crowded freeform diagram).
- Prefer path_trace / vector_field / angle_tracker / boolean_sets when the concept is
  orbits, fields, angles, or set operations — samples exist for these motion patterns.
- style_tags: 2–4 lowercase keywords for template matching
  (e.g. ["particles","heatmap","house"], ["gate","sigmoid","lstm"], ["sine","orbit","trace"],
  ["vector","field"], ["boxes","pipeline"]).
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
    language: str = "en",
) -> ScenePlan:
    length = LENGTH_GUIDANCE.get(length_preset, LENGTH_GUIDANCE["standard"])
    aud = AUDIENCE_GUIDANCE.get(audience, AUDIENCE_GUIDANCE["general"])
    lang = normalize_language(language)
    lang_name = language_display_name(lang)
    user = f"""Learner prompt:
{prompt}

Length preset ({length_preset}): {length}
Audience ({audience}): {aud}
Output language ({lang}): Write ALL learner-facing text in {lang_name}.
"""
    data = client.chat_json(
        system=PLANNER_SYSTEM,
        user=user,
        temperature=0.4,
        max_tokens=4096,
    )
    return ScenePlan.model_validate(data)
