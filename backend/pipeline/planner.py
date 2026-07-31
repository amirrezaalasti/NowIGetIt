"""Step 1: turn a user prompt into a structured JSON scene plan."""

from __future__ import annotations

import re

from backend.languages import language_display_name, normalize_language
from backend.llm import OpenRouterClient
from backend.schemas import ScenePlan

# (min_seconds, max_seconds) of TOTAL spoken narration the final video must
# reach. This is what actually drives runtime (each scene's clip is timed to
# its narration's real TTS duration), so planning is validated against it —
# not just a vague word like "short"/"deep".
LENGTH_TARGET_SECONDS: dict[str, tuple[float, float]] = {
    "short": (45.0, 75.0),
    "standard": (75.0, 115.0),
    "deep": (150.0, 210.0),
}

# Soft floor for a useful scene; longer scenes are fine when the visual idea needs them.
MIN_SCENE_SECONDS = 7.0

# (min_scenes, max_scenes) — enough beats to reach the duration target without
# collapsing the whole video into a handful of scenes.
LENGTH_SCENE_COUNT: dict[str, tuple[int, int]] = {
    "short": (4, 6),
    "standard": (6, 9),
    "deep": (9, 14),
}

LENGTH_GUIDANCE = {
    "short": (
        f"Target {LENGTH_TARGET_SECONDS['short'][0]:.0f}-"
        f"{LENGTH_TARGET_SECONDS['short'][1]:.0f} seconds of TOTAL spoken narration "
        f"across {LENGTH_SCENE_COUNT['short'][0]}-{LENGTH_SCENE_COUNT['short'][1]} scenes. "
        "Ruthlessly cut filler."
    ),
    "standard": (
        f"Target {LENGTH_TARGET_SECONDS['standard'][0]:.0f}-"
        f"{LENGTH_TARGET_SECONDS['standard'][1]:.0f} seconds of TOTAL spoken narration "
        f"across {LENGTH_SCENE_COUNT['standard'][0]}-{LENGTH_SCENE_COUNT['standard'][1]} scenes."
    ),
    "deep": (
        f"Target {LENGTH_TARGET_SECONDS['deep'][0]:.0f}-"
        f"{LENGTH_TARGET_SECONDS['deep'][1]:.0f} seconds of TOTAL spoken narration "
        f"across {LENGTH_SCENE_COUNT['deep'][0]}-{LENGTH_SCENE_COUNT['deep'][1]} scenes "
        "with progressive depth."
    ),
}

AUDIENCE_GUIDANCE = {
    "hs": "High-school level: concrete metaphors, minimal jargon, everyday analogies.",
    "undergrad": "College intro level: precise terms OK when defined; show formal structure.",
    "general": "Curious adult audience: clear language, strong intuition, light formalism.",
}

_CJK_LANGS = {"zh", "ja", "ko"}


def estimate_narration_seconds(text: str, language: str = "en") -> float:
    """Rough spoken-duration estimate used to gate plan length before TTS runs.

    Latin/space-separated scripts: ~2.5 words/sec. CJK: ~3.3 chars/sec.
    This mirrors the pacing guidance given to the planner LLM.
    """
    text = (text or "").strip()
    if not text:
        return 0.0
    lang = normalize_language(language)
    if lang in _CJK_LANGS:
        chars = len(re.sub(r"\s+", "", text))
        return chars / 3.3
    words = len(text.split())
    return words / 2.5


def _plan_total_narration_seconds(plan: ScenePlan, language: str) -> float:
    total = 0.0
    for s in plan.scenes:
        for b in s.beats:
            total += estimate_narration_seconds(b.narration, language)
    return total


def _validate_plan_length(plan: ScenePlan, *, length_preset: str, language: str) -> None:
    """Raise ValueError (caught by the retry loop) when the plan is far from
    the target runtime for its preset — this is the #1 cause of "picked 3
    minutes but got way less": narration was simply too short/too few scenes.
    """
    min_target, max_target = LENGTH_TARGET_SECONDS.get(
        length_preset, LENGTH_TARGET_SECONDS["standard"]
    )
    min_scenes, max_scenes = LENGTH_SCENE_COUNT.get(length_preset, (3, 6))
    total_est = _plan_total_narration_seconds(plan, language)
    scene_count = len(plan.scenes)

    if scene_count < min_scenes:
        raise ValueError(
            f"Only {scene_count} scenes were planned, but the '{length_preset}' preset "
            f"needs {min_scenes}-{max_scenes} scenes to reach a "
            f"{min_target:.0f}-{max_target:.0f}s video. Add more scenes."
        )
    if total_est < min_target * 0.85:
        raise ValueError(
            f"Estimated total spoken narration is only ~{total_est:.0f}s across "
            f"{scene_count} scenes, well short of the {min_target:.0f}-{max_target:.0f}s "
            f"target for the '{length_preset}' preset. Add more scenes and/or write "
            f"longer, fuller narration per scene (aim for {min_scenes}-{max_scenes} "
            "scenes total) so the total spoken narration reaches the target."
        )
    if total_est > max_target * 1.3:
        raise ValueError(
            f"Estimated total spoken narration is ~{total_est:.0f}s across "
            f"{scene_count} scenes, well over the {min_target:.0f}-{max_target:.0f}s "
            f"target for the '{length_preset}' preset. Trim narration and/or "
            f"reduce to {min_scenes}-{max_scenes} scenes."
        )


PLANNER_SYSTEM = """You are an expert educational animation director (3Blue1Brown-caliber).
Given a learner's prompt, produce a JSON scene plan for a short explanatory video.

Rules:
- Break the explanation into sequential scenes based on complexity. Keep each scene
  simple enough for one short Manim class — one clear visual idea per scene.
- IMPORTANT: It is highly recommended to generate between 4 and 7 scenes based on the context to maintain optimal pacing.
- Each scene must include: id, title, visual_description,
  beats (a list of objects with 'visual_action' and 'narration'), duration_seconds, camera_notes, visual_device, style_tags.
- LANGUAGE (critical): Write title, concept_summary, narration (inside beats), visual_description,
  and visual_action (inside beats) in the requested output language. On-screen labels implied by
  the plan must also be in that language. Keep visual_device / style_tags in English
  (they are machine keys). Prefer progressive reveal: introduce → build intuition → summarize.
- Narration: clear spoken script for TTS in the output language. Match duration_seconds
  to the total spoken length of all beats (~2.5 words/sec for Latin scripts; ~3–4 syllables/sec for others).
- SCENE LENGTH: aim for at least __SCENE_MIN__ seconds of total narration per scene so each
  beat has room to breathe. Longer scenes are fine when one visual idea genuinely needs
  the time — do not pad with silence, pulsing shapes, or filler waits; add content or
  split into another scene only when there are two distinct visual ideas.
- Each scene's narration must name 2-4 concrete things that will get on-screen labels,
  so the coder has real content to reveal instead of animating unlabeled shapes.
- Visuals: concrete Manim-friendly elements (shapes, graphs, equations as Text, arrows, labels).
- CONTEXT & AESTHETICS (critical): Deeply understand the context and semantics of the explanation to generate vivid, highly relatable visual metaphors. Explicitly prescribe beautiful, harmonious pastel color themes (e.g., soft pinks, mint greens, baby blues, etc.) and engaging, organic animations for objects in the `style_tags` and `visual_description`. Avoid generic, harsh colors.
CONTINUITY (critical — scenes are rendered separately, so the SCRIPT AND VISUAL PLAN are
what glue them into one video; without them the video feels like disconnected clips with
mismatched, random-looking styles from scene to scene):
- Treat the whole plan as ONE continuous lecture split into scenes, not N unrelated clips.
  Pick a single through-line / metaphor / running example in concept_summary and reuse it.
- Every scene's narration (except the very first) must open by briefly linking back to the
  previous scene's idea before introducing the new one — e.g. "Now that we've seen how X
  behaves, the natural question is Y…", "That builds up to a subtler idea:", "But this
  only works when...". Never open a non-first scene with an abrupt, unconnected sentence.
- Every scene's narration (except the very last) should end on a short forward-leaning
  beat that sets up the next scene's question, instead of a flat, closed-off statement —
  e.g. "...but that raises a new problem, which we'll tackle next." Avoid final scenes
  restating "in conclusion" phrasing more than once across the plan.
- Do not repeat the exact same transition phrase across multiple scenes; vary the language.
- Keep numbering/labels/terminology for the same concept identical across scenes (do not
  rename a variable or component between scenes).
- Scene durations should ramp sensibly (short cold-open, longer builds, a tight close) —
  avoid a jarring long scene immediately followed by a very short one.
- recurring_elements (critical for VISUAL consistency, not just narration): list 2-4
  CONCRETE, literally-reusable visual anchors — a specific named object, shape, color role,
  or diagram — that must appear (in the same form) in every scene, e.g.
  ["a labeled x-y axes pair that persists across scenes", "an orange circle representing
  the current data point", "a running 'loss' counter in the top-right"]. These are handed
  to every scene's coder so scenes don't each invent their own unrelated visual language.
  Be specific enough to draw (shape + color/role), not just a topic word.

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
- recurring_elements: 2-4 concrete visual anchors reused verbatim across every scene
  (see CONTINUITY above). Every scene's coder will be told to keep these identical.
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
  "recurring_elements": [string],
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
      "visual_description": string,
      "beats": [
        {
          "visual_action": string,
          "narration": string
        }
      ],
      "duration_seconds": number,
      "camera_notes": string,
      "visual_device": string,
      "style_tags": [string]
    }
  ]
}
""".replace("__SCENE_MIN__", f"{MIN_SCENE_SECONDS:.0f}")


# Full multi-scene plans (esp. non-English) routinely exceed 4k completion
# tokens; truncating mid-JSON yields metadata-only objects missing `scenes`.
PLANNER_MAX_TOKENS: dict[str, int] = {
    "short": 8192,
    "standard": 12288,
    "deep": 16384,
}


def _require_scenes_payload(data: dict) -> None:
    """Fail fast when the model truncated before emitting the scenes array."""
    scenes = data.get("scenes") if isinstance(data, dict) else None
    if isinstance(scenes, list) and scenes:
        return
    keys = sorted(data.keys()) if isinstance(data, dict) else []
    raise ValueError(
        "JSON is missing a non-empty 'scenes' array "
        f"(got keys {keys}). The previous response was likely truncated — "
        "return the COMPLETE object including every scene, and keep each "
        "scene's narration concise enough to fit."
    )


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
    min_target, max_target = LENGTH_TARGET_SECONDS.get(
        length_preset, LENGTH_TARGET_SECONDS["standard"]
    )
    min_scenes, max_scenes = LENGTH_SCENE_COUNT.get(length_preset, (3, 6))
    max_tokens = PLANNER_MAX_TOKENS.get(length_preset, PLANNER_MAX_TOKENS["standard"])
    user = f"""Learner prompt:
{prompt}

Length preset ({length_preset}): {length}
HARD REQUIREMENT (checked programmatically — the plan will be rejected and
retried if this is not met): the sum of every scene's spoken narration must
land between {min_target:.0f} and {max_target:.0f} seconds total, across
{min_scenes}-{max_scenes} scenes. Write full, complete narration sentences —
not short filler lines — so the natural spoken duration reaches this target;
padding with silence/wait time does not count, only actual narration length.
Individual scenes may run longer when the idea needs it.
Audience ({audience}): {aud}
Output language ({lang}): Write ALL learner-facing text in {lang_name}.
CRITICAL: the JSON MUST include a top-level "scenes" array with
{min_scenes}-{max_scenes} scene objects. Do not stop after title/summary/
palette — emit every scene before ending the response.
"""
    last_err = None
    for attempt in range(3):
        try:
            data = client.chat_json(
                system=PLANNER_SYSTEM,
                user=user,
                temperature=0.4 + (attempt * 0.1),
                max_tokens=max_tokens,
                model=client.manim_model,
            )
            _require_scenes_payload(data)
            plan = ScenePlan.model_validate(data)
            _validate_plan_length(plan, length_preset=length_preset, language=lang)
            return plan
        except Exception as e:
            last_err = e
            user += f"\n\nERROR on last attempt: {e}\nPlease ensure you return a valid JSON object matching the requested schema."

    raise ValueError(f"Failed to generate valid ScenePlan after 3 attempts: {last_err}") from last_err


REVISE_PLAN_SYSTEM = (
    PLANNER_SYSTEM
    + """

REVISION MODE: you are given an EXISTING scene plan (as JSON) and a learner's
follow-up instruction (e.g. "add a scene about X", "remove scene 3", "make it
shorter", "merge the last two scenes"). Apply the requested change while:
- Keeping every untouched scene's narration/visuals unchanged unless the
  instruction implies otherwise.
- Preserving concept_summary, visual_identity, recurring_elements, and palette
  so newly added/edited scenes still look and sound like part of the same
  video (reuse the SAME palette hex values and recurring_elements).
- Re-numbering scene ids sequentially as scene_1, scene_2, … after any
  add/remove/reorder so there are no gaps or duplicates.
- Keeping the CONTINUITY rules above intact for the new scene order (fix the
  opening/closing transition lines of scenes adjacent to any change so the
  narration still flows as one continuous lecture).
- Respecting the total-narration-length TARGET given in the user message,
  unless the learner's instruction explicitly asks to change it.
Return the FULL updated plan as a JSON object in the exact same shape as
before (not a diff, not just the changed scenes).
"""
)


def revise_scene_plan(
    client: OpenRouterClient,
    plan: ScenePlan,
    instructions: str,
    *,
    length_preset: str = "standard",
    audience: str = "general",
    language: str = "en",
) -> ScenePlan:
    """Apply a natural-language edit (add/remove/reorder/rewrite scenes) to an
    existing plan via the LLM, keeping continuity + visual identity intact.
    """
    length = LENGTH_GUIDANCE.get(length_preset, LENGTH_GUIDANCE["standard"])
    aud = AUDIENCE_GUIDANCE.get(audience, AUDIENCE_GUIDANCE["general"])
    lang = normalize_language(language)
    lang_name = language_display_name(lang)
    min_target, max_target = LENGTH_TARGET_SECONDS.get(
        length_preset, LENGTH_TARGET_SECONDS["standard"]
    )
    min_scenes, max_scenes = LENGTH_SCENE_COUNT.get(length_preset, (3, 6))
    max_tokens = PLANNER_MAX_TOKENS.get(length_preset, PLANNER_MAX_TOKENS["standard"])
    plan_json = plan.model_dump_json(indent=2)
    user = f"""Existing scene plan (JSON):
{plan_json}

Learner's requested change:
{instructions.strip()}

Length preset ({length_preset}): {length}
TARGET (keep unless the learner's instruction explicitly asks to change the
overall length, e.g. "make it longer"/"make it shorter" — then honor that
instruction instead): the sum of every scene's spoken narration should stay
between {min_target:.0f} and {max_target:.0f} seconds total, across
{min_scenes}-{max_scenes} scenes.
Audience ({audience}): {aud}
Output language ({lang}): Write ALL learner-facing text in {lang_name}.
CRITICAL: return the FULL updated plan JSON including a non-empty "scenes"
array — never omit scenes.
"""
    last_err = None
    for attempt in range(3):
        try:
            data = client.chat_json(
                system=REVISE_PLAN_SYSTEM,
                user=user,
                temperature=0.35 + (attempt * 0.1),
                max_tokens=max_tokens,
                model=client.manim_model,
            )
            _require_scenes_payload(data)
            revised = ScenePlan.model_validate(data)
            return revised
        except Exception as e:
            last_err = e
            user += f"\n\nERROR on last attempt: {e}\nPlease ensure you return a valid JSON object matching the requested schema."

    raise ValueError(
        f"Failed to revise ScenePlan after 3 attempts: {last_err}"
    ) from last_err
