"""Step 1: turn a user prompt into a structured JSON scene plan."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Optional

from backend.languages import language_display_name, normalize_language
from backend.llm import OpenRouterClient
from backend.schemas import ScenePlan

# (message, optional data) — used so the UI can show planning steps live.
ProgressCallback = Callable[[str, dict[str, Any]], None]

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

# Balanced pacing: (min_scenes, max_scenes) for each total-length preset.
LENGTH_SCENE_COUNT: dict[str, tuple[int, int]] = {
    "short": (4, 6),
    "standard": (6, 9),
    "deep": (9, 14),
}

# How to carve the same total runtime into scenes.
# short = many quick beats · balanced = default · long = fewer deeper scenes.
SCENE_PACING_VALUES = frozenset({"short", "balanced", "long"})

# Explicit (min, max) scene counts per (length_preset, scene_pacing).
# Totals stay in LENGTH_TARGET_SECONDS; only the cut structure changes.
SCENE_PACING_COUNT: dict[str, dict[str, tuple[int, int]]] = {
    "short": {
        "short": (5, 8),
        "balanced": LENGTH_SCENE_COUNT["short"],
        "long": (2, 4),
    },
    "standard": {
        "short": (8, 12),
        "balanced": LENGTH_SCENE_COUNT["standard"],
        "long": (3, 5),
    },
    "deep": {
        "short": (14, 20),
        "balanced": LENGTH_SCENE_COUNT["deep"],
        "long": (6, 9),
    },
}

SCENE_PACING_GUIDANCE = {
    "short": (
        "Prefer MANY SHORT scenes (~8–12s each): one crisp visual idea per cut. "
        "Split complex ideas aggressively; keep narration tight."
    ),
    "balanced": (
        "Prefer a balanced scene length (~12–18s each): enough room for a clear "
        "visual beat without packing a whole lecture into one scene."
    ),
    "long": (
        "Prefer FEWER LONGER scenes (~20–35s each): let one visual idea develop "
        "fully before cutting. Merge related beats; avoid choppy micro-scenes."
    ),
}


def scene_count_range(
    length_preset: str, scene_pacing: str = "balanced"
) -> tuple[int, int]:
    """Return (min_scenes, max_scenes) for a length + pacing combo."""
    pacing = scene_pacing if scene_pacing in SCENE_PACING_VALUES else "balanced"
    by_length = SCENE_PACING_COUNT.get(length_preset) or SCENE_PACING_COUNT["standard"]
    return by_length.get(pacing, by_length["balanced"])


def length_guidance(length_preset: str, scene_pacing: str = "balanced") -> str:
    """Human-readable length target including scene-count band for pacing."""
    min_target, max_target = LENGTH_TARGET_SECONDS.get(
        length_preset, LENGTH_TARGET_SECONDS["standard"]
    )
    min_scenes, max_scenes = scene_count_range(length_preset, scene_pacing)
    pacing = scene_pacing if scene_pacing in SCENE_PACING_VALUES else "balanced"
    base = (
        f"Target {min_target:.0f}-{max_target:.0f} seconds of TOTAL spoken narration "
        f"across {min_scenes}-{max_scenes} scenes."
    )
    if length_preset == "short":
        base += " Ruthlessly cut filler."
    elif length_preset == "deep":
        base += " Progressive depth."
    return f"{base} {SCENE_PACING_GUIDANCE[pacing]}"


# Back-compat aliases used by tests / callers that only pass length_preset.
LENGTH_GUIDANCE = {
    key: length_guidance(key, "balanced") for key in LENGTH_SCENE_COUNT
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
    return sum(estimate_narration_seconds(s.narration, language) for s in plan.scenes)


def _validate_plan_length(
    plan: ScenePlan,
    *,
    length_preset: str,
    language: str,
    scene_pacing: str = "balanced",
) -> None:
    """Raise ValueError (caught by the retry loop) when the plan is far from
    the target runtime for its preset — this is the #1 cause of "picked 3
    minutes but got way less": narration was simply too short/too few scenes.
    """
    min_target, max_target = LENGTH_TARGET_SECONDS.get(
        length_preset, LENGTH_TARGET_SECONDS["standard"]
    )
    min_scenes, max_scenes = scene_count_range(length_preset, scene_pacing)
    total_est = _plan_total_narration_seconds(plan, language)
    scene_count = len(plan.scenes)
    pacing = scene_pacing if scene_pacing in SCENE_PACING_VALUES else "balanced"

    if scene_count < min_scenes:
        raise ValueError(
            f"Only {scene_count} scenes were planned, but the '{length_preset}' "
            f"preset with '{pacing}' pacing needs {min_scenes}-{max_scenes} scenes "
            f"to reach a {min_target:.0f}-{max_target:.0f}s video. Add more scenes."
        )
    if scene_count > max_scenes:
        tip = (
            "Merge related beats into fewer, fuller scenes."
            if pacing == "long"
            else "Reduce the scene count."
        )
        raise ValueError(
            f"{scene_count} scenes were planned, but the '{length_preset}' preset "
            f"with '{pacing}' pacing allows at most {max_scenes} "
            f"(aim for {min_scenes}-{max_scenes}). {tip}"
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

SCENE STRUCTURE:
- Break the explanation into sequential scenes, one clear visual idea per scene —
  simple enough for one short Manim class. Split complex topics across scenes
  (overview → component A → component B → …) instead of packing a whole system
  (e.g. every LSTM gate, a full transformer stack) into one scene.
- Each scene needs: id, title, narration, visual_description, animation_beats (3-6,
  each describing MOTION — "Dot slides to the minimum", "GrowArrow for gradient" —
  never just "show X"), duration_seconds, camera_notes, visual_device, style_tags.
- Name 2-4 concrete things per scene that will get short on-screen labels (≤3 words),
  so the coder has real content to reveal instead of animating unlabeled shapes.
- The final beat of every scene must leave the core diagram + title on screen.

LANGUAGE: write narration, titles, and on-screen labels in the requested output
language (visual_device/style_tags stay in English — they're machine keys). Match
narration length to spoken pacing (~2.5 words/sec for Latin scripts, ~3-4
syllables/sec for others); do not pad with silence to hit a duration. Aim for at
least __SCENE_MIN__ seconds of narration per scene — longer is fine when one visual
idea genuinely needs it; split into another scene instead of padding.

CONTINUITY (scenes render separately — this is what glues them into one video
instead of feeling like disconnected clips):
- Pick one through-line / running example in concept_summary and reuse it throughout.
- Every non-first scene's narration opens by briefly linking back to the previous
  idea; every non-last scene ends on a forward-leaning beat that sets up the next
  one. Vary the transition phrasing — don't reuse the same line twice.
- Keep terminology/labels for the same concept identical across scenes.
- recurring_elements: list 2-4 concrete, literally-reusable visual anchors — a named
  shape + color + role (e.g. "an orange circle for the current data point", "a
  labeled x-y axes pair that persists across scenes") — that every scene's coder
  must render identically, so scenes share one visual language.

VISUAL DEVICE: pick ONE per scene from: number_line | unit_circle | before_after |
particle_flow | equation_reveal | axes_graph | lattice_grid | morph_transform |
house_section | comparison_split | labeled_box_flow | gate_mechanism |
annotated_diagram | path_trace | vector_field | angle_tracker | boolean_sets.
Use labeled_box_flow / gate_mechanism / annotated_diagram for neural nets, pipelines,
gates, and other box+arrow systems; prefer path_trace / vector_field /
angle_tracker / boolean_sets for orbits, fields, angles, or set operations.

STYLE:
- style_tags: 2-4 lowercase keywords for template matching, e.g. ["gate","sigmoid","lstm"].
- visual_identity: one sentence — the overall look (metaphor + mood).
- palette: background/accent/text/highlight as hex colors. Prefer a distinctive,
  non-default palette; dark backgrounds (#0f1115 / #0B0C10) pair well with warm accents.
- style_notes: concrete Manim direction (colors, typography feel, motion style).
- All on-screen text renders as plain Text() (no LaTeX) — plain-text math words are
  fine too (e.g. "x squared" or "x^2").
- JSON strings must be valid: escape every backslash as \\\\ (write \\\\frac not \\frac).

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
    scene_pacing: str = "balanced",
    audience: str = "general",
    language: str = "en",
    on_progress: Optional[ProgressCallback] = None,
) -> ScenePlan:
    pacing = scene_pacing if scene_pacing in SCENE_PACING_VALUES else "balanced"
    length = length_guidance(length_preset, pacing)
    aud = AUDIENCE_GUIDANCE.get(audience, AUDIENCE_GUIDANCE["general"])
    lang = normalize_language(language)
    lang_name = language_display_name(lang)
    min_target, max_target = LENGTH_TARGET_SECONDS.get(
        length_preset, LENGTH_TARGET_SECONDS["standard"]
    )
    min_scenes, max_scenes = scene_count_range(length_preset, pacing)
    max_tokens = PLANNER_MAX_TOKENS.get(length_preset, PLANNER_MAX_TOKENS["standard"])
    # Many short scenes need more JSON headroom.
    if pacing == "short":
        max_tokens = max(max_tokens, PLANNER_MAX_TOKENS["deep"])

    def _progress(message: str, **data: Any) -> None:
        if on_progress:
            on_progress(message, data)

    user = f"""Learner prompt:
{prompt}

Length preset ({length_preset}): {length}
Scene pacing ({pacing}): {SCENE_PACING_GUIDANCE[pacing]}
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
    _progress(
        f"Sketching a {length_preset} / {pacing}-paced storyboard in {lang_name} "
        f"({min_scenes}–{max_scenes} scenes, ~{min_target:.0f}–{max_target:.0f}s)…",
        step="planning.prepare",
        length_preset=length_preset,
        scene_pacing=pacing,
        audience=audience,
        language=lang,
        min_scenes=min_scenes,
        max_scenes=max_scenes,
    )
    for attempt in range(3):
        try:
            _progress(
                f"Asking the planner model (attempt {attempt + 1}/3)…",
                step="planning.llm",
                attempt=attempt + 1,
                max_attempts=3,
            )
            data = client.chat_json(
                system=PLANNER_SYSTEM,
                user=user,
                temperature=0.4 + (attempt * 0.1),
                max_tokens=max_tokens,
                model=client.manim_model,
            )
            _progress(
                "Validating scene count and narration length…",
                step="planning.validate",
                attempt=attempt + 1,
            )
            _require_scenes_payload(data)
            plan = ScenePlan.model_validate(data)
            _validate_plan_length(
                plan,
                length_preset=length_preset,
                language=lang,
                scene_pacing=pacing,
            )
            _progress(
                f"Storyboard locked: {len(plan.scenes)} scenes · {plan.title}",
                step="planning.done",
                scene_count=len(plan.scenes),
                title=plan.title,
            )
            return plan
        except Exception as e:
            last_err = e
            _progress(
                f"Plan attempt {attempt + 1} needed a retry: {e}",
                step="planning.retry",
                attempt=attempt + 1,
                detail=str(e)[:400],
            )
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
    scene_pacing: str = "balanced",
    audience: str = "general",
    language: str = "en",
    on_progress: Optional[ProgressCallback] = None,
) -> ScenePlan:
    """Apply a natural-language edit (add/remove/reorder/rewrite scenes) to an
    existing plan via the LLM, keeping continuity + visual identity intact.
    """
    pacing = scene_pacing if scene_pacing in SCENE_PACING_VALUES else "balanced"
    length = length_guidance(length_preset, pacing)
    aud = AUDIENCE_GUIDANCE.get(audience, AUDIENCE_GUIDANCE["general"])
    lang = normalize_language(language)
    lang_name = language_display_name(lang)
    min_target, max_target = LENGTH_TARGET_SECONDS.get(
        length_preset, LENGTH_TARGET_SECONDS["standard"]
    )
    min_scenes, max_scenes = scene_count_range(length_preset, pacing)
    max_tokens = PLANNER_MAX_TOKENS.get(length_preset, PLANNER_MAX_TOKENS["standard"])
    if pacing == "short":
        max_tokens = max(max_tokens, PLANNER_MAX_TOKENS["deep"])

    def _progress(message: str, **data: Any) -> None:
        if on_progress:
            on_progress(message, data)

    plan_json = plan.model_dump_json(indent=2)
    user = f"""Existing scene plan (JSON):
{plan_json}

Learner's requested change:
{instructions.strip()}

Length preset ({length_preset}): {length}
Scene pacing ({pacing}): {SCENE_PACING_GUIDANCE[pacing]}
TARGET (keep unless the learner's instruction explicitly asks to change the
overall length or pacing, e.g. "make it longer"/"fewer longer scenes" — then
honor that instruction instead): the sum of every scene's spoken narration
should stay between {min_target:.0f} and {max_target:.0f} seconds total, across
{min_scenes}-{max_scenes} scenes.
Audience ({audience}): {aud}
Output language ({lang}): Write ALL learner-facing text in {lang_name}.
CRITICAL: return the FULL updated plan JSON including a non-empty "scenes"
array — never omit scenes.
"""
    last_err = None
    _progress(
        "Revising storyboard from your instructions…",
        step="planning.revise",
        scene_count=len(plan.scenes),
    )
    for attempt in range(3):
        try:
            _progress(
                f"Planner revise attempt {attempt + 1}/3…",
                step="planning.revise_llm",
                attempt=attempt + 1,
                max_attempts=3,
            )
            data = client.chat_json(
                system=REVISE_PLAN_SYSTEM,
                user=user,
                temperature=0.35 + (attempt * 0.1),
                max_tokens=max_tokens,
                model=client.manim_model,
            )
            _require_scenes_payload(data)
            revised = ScenePlan.model_validate(data)
            _progress(
                f"Updated storyboard: {len(revised.scenes)} scenes · {revised.title}",
                step="planning.revise_done",
                scene_count=len(revised.scenes),
                title=revised.title,
            )
            return revised
        except Exception as e:
            last_err = e
            _progress(
                f"Revise attempt {attempt + 1} needed a retry: {e}",
                step="planning.revise_retry",
                attempt=attempt + 1,
                detail=str(e)[:400],
            )
            user += f"\n\nERROR on last attempt: {e}\nPlease ensure you return a valid JSON object matching the requested schema."

    raise ValueError(
        f"Failed to revise ScenePlan after 3 attempts: {last_err}"
    ) from last_err
