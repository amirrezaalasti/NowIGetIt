"""Step 1: turn a user prompt into a structured JSON scene plan."""

from __future__ import annotations

import re
from collections.abc import Callable
from typing import Any, Optional

from backend.languages import language_display_name, normalize_language
from backend.llm import OpenRouterClient
from backend.pipeline.pedagogy import format_blueprint_for_planner
from backend.schemas import ScenePlan, TeachingBlueprint

# (message, optional data) — used so the UI can show planning steps live.
ProgressCallback = Callable[[str, dict[str, Any]], None]

# (min_seconds, max_seconds) of TOTAL spoken narration the final video must
# reach. This is what actually drives runtime (each scene's clip is timed to
# its narration's real TTS duration), so planning is validated against it —
# not just a vague word like "short"/"deep".
LENGTH_TARGET_SECONDS: dict[str, tuple[float, float]] = {
    "clip": (6.0, 16.0),
    "short": (45.0, 75.0),
    "standard": (75.0, 115.0),
    "deep": (150.0, 210.0),
}

# Soft floor for a useful scene; longer scenes are fine when the visual idea needs them.
MIN_SCENE_SECONDS = 7.0

# Balanced pacing: (min_scenes, max_scenes) for each total-length preset.
LENGTH_SCENE_COUNT: dict[str, tuple[int, int]] = {
    "clip": (1, 2),
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
    "clip": {
        "short": (1, 2),
        "balanced": LENGTH_SCENE_COUNT["clip"],
        "long": (1, 2),
    },
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


def is_clip_preset(length_preset: str) -> bool:
    return length_preset == "clip"


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
    if length_preset == "clip":
        return (
            "Looping GIF clip: 1–2 scenes, 8–15 seconds total. ONE visual idea, "
            "ONE motion. First and last frames should match so it loops. Narration "
            "is a few short on-screen labels or one sentence per beat — not a lecture. "
            "The picture has to make the idea obvious without a long voiceover."
        )
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
    total = 0.0
    for s in plan.scenes:
        for b in s.beats:
            total += estimate_narration_seconds(b.narration, language)
    return total


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

    if length_preset == "clip":
        if scene_count < min_scenes or scene_count > max_scenes:
            raise ValueError(
                f"A GIF clip needs {min_scenes}-{max_scenes} scenes (got {scene_count}). "
                "One motion, one idea — do not turn this into a lecture."
            )
        total_dur = sum(float(s.duration_seconds or 0) for s in plan.scenes)
        if total_dur and (total_dur < 6.0 or total_dur > 22.0):
            raise ValueError(
                f"Clip duration is ~{total_dur:.0f}s; keep the GIF between 8 and 15 seconds "
                f"({min_scenes}-{max_scenes} scenes)."
            )
        if total_est > max_target * 1.4:
            raise ValueError(
                f"Spoken narration is ~{total_est:.0f}s — too long for a looping GIF. "
                "Cut it to a few short labels."
            )
        return

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


def _validate_beat_narration(plan: ScenePlan) -> None:
    """Reject plans that dump a scene's whole script onto one beat.

    Codegen renders beats as a timeline ("at 4.1s-7.8s animate X while the voice
    says Y"), so narration bunched on a single beat costs the animation its sync
    with the voiceover. This is checked only on early attempts — a plan that is
    otherwise good is still far better than no plan at all.
    """
    offenders: list[str] = []
    for scene in plan.scenes:
        if len(scene.beats) < 2:
            continue
        with_narration = sum(1 for b in scene.beats if b.narration.strip())
        if with_narration < 2:
            offenders.append(scene.id)
    if offenders:
        raise ValueError(
            f"Scenes {', '.join(offenders)} put all their narration on a single "
            "beat. Split each scene's narration ACROSS its beats: every beat needs "
            "the one or two sentences spoken while that beat's visual_action is on "
            "screen, so the animation stays in sync with the voiceover."
        )


def _validate_step_coverage(plan: ScenePlan, blueprint: TeachingBlueprint) -> None:
    """Reject a storyboard that quietly dropped or reordered teaching steps.

    The blueprint is the explanation; scenes are only its staging. A plan that
    skips step 4 or teaches step 6 before step 5 is exactly the "sequence of
    pretty clips that never adds up" failure the blueprint exists to prevent.
    """
    step_ids = [s.id for s in blueprint.steps]
    if not step_ids:
        return
    known = {sid.lower(): sid for sid in step_ids}
    covered: list[str] = []
    unknown: list[str] = []
    for scene in plan.scenes:
        for raw in scene.covers_steps:
            key = str(raw).strip().lower()
            if key in known:
                covered.append(known[key])
            elif key:
                unknown.append(str(raw))

    if not covered:
        raise ValueError(
            "No scene recorded which teaching steps it delivers. Set `covers_steps` on "
            f"every scene using the plan's step ids ({', '.join(step_ids)}) so the "
            "storyboard provably covers the explanation."
        )
    if unknown:
        raise ValueError(
            f"covers_steps references unknown step ids: {', '.join(sorted(set(unknown))[:5])}. "
            f"Use only the ids from the teaching plan: {', '.join(step_ids)}."
        )
    missing = [sid for sid in step_ids if sid not in covered]
    if missing:
        raise ValueError(
            f"Teaching steps {', '.join(missing)} are not delivered by any scene. Every "
            "step is a rung the next one depends on — add or extend scenes so all of "
            f"{', '.join(step_ids)} are covered."
        )
    off_plan = [s.id for s in plan.scenes if not [c for c in s.covers_steps if str(c).strip()]]
    if off_plan:
        raise ValueError(
            f"Scenes {', '.join(off_plan)} do not deliver any teaching step. Every scene "
            "must stage part of the plan — give each one the step id(s) it delivers in "
            "`covers_steps`, or drop the scene."
        )
    # A step may span consecutive scenes (a big idea split in two); it may not
    # come back after the explanation has moved on.
    order = [step_ids.index(sid) for sid in covered]
    if order != sorted(order):
        raise ValueError(
            "Scenes deliver the teaching steps out of order "
            f"({' → '.join(covered)}). Each step is earned by the one before it, so the "
            f"scenes must follow the plan's order: {' → '.join(step_ids)}."
        )


PLANNER_SYSTEM = """You are an expert educational animation director (3Blue1Brown-caliber).
Given a learner's prompt, produce a JSON scene plan for a short explanatory video.

TEACH SOMETHING — the video must leave the learner able to do or see something they
could not before. Before writing scenes, decide:
- the ONE question the video answers (put it in concept_summary);
- the concrete running example you will actually work through — with real numbers,
  not "some value" (e.g. a specific parabola and a starting x of -2, one 3-word
  sentence being tokenized, a 400W heater in a 20m² room);
- the misconception you are pre-empting.
Then order the scenes as a real explanation, not a table of contents: hook the
question → build the mechanism one moving part at a time → work the example →
land the payoff. Never open with "In this video we will…" — open on the problem.

WHEN A TEACHING PLAN IS PROVIDED, those decisions are already made — your job is to
STAGE it, not to re-derive it:
- Walk its steps in the given order. Each scene delivers one step, or two adjacent
  steps when they are small; split one step across consecutive scenes when it is too
  big for a single visual idea. Never reorder steps, never skip one, never add a
  scene teaching something outside the plan.
- Record which steps each scene delivers in that scene's `covers_steps` (e.g.
  ["step_3"]). Every scene needs at least one step id, every step id must appear in
  at least one scene, and the ids must run in order across the scenes — a step split
  across two scenes uses consecutive scenes, and an idea is never revisited after the
  explanation has moved past it.
- A step's `visual_strategy` is the scene's visual_description and the source of its
  beats; its `why_it_follows` is what the narration must actually say; its
  `checkpoint` is what the scene must leave the learner able to do.
- Use the plan's notation with its stated visual_encoding for every on-screen label,
  and put those encodings into recurring_elements so every scene renders them the
  same way. Never introduce a symbol before the step that introduces it.
- Introduce each relation the way its `how_to_show` says: the picture makes it
  obvious first, then the expression appears, built term by term. The running example
  and its real numbers carry through every scene.

SCENE STRUCTURE:
- Break the explanation into sequential scenes, one clear visual idea per scene —
  simple enough for one short Manim class. Split complex topics across scenes
  (overview → component A → component B → …) instead of packing a whole system
  (e.g. every LSTM gate, a full transformer stack) into one scene.
- Each scene needs: id, title, visual_description, beats (3-6), duration_seconds,
  camera_notes, visual_device, style_tags.
- BEATS ARE THE CORE OF THE PLAN. Each beat pairs ONE `visual_action` with the exact
  `narration` spoken while that action is on screen. The two are rendered together:
  the animator receives "at 4.1s–7.8s, animate <visual_action> while the voice says
  <narration>" and follows it literally. So:
  * Split the narration ACROSS the beats — never write the whole paragraph into one
    beat and leave the rest empty. Each beat carries the one or two sentences said
    during it, and those sentences must describe what that beat shows.
  * `visual_action` describes MOTION with a subject — "The orange dot slides down the
    curve to the minimum", "GrowArrow from the dot along the tangent" — never "show
    gradient descent" and never a static "display X".
  * Beat N+1 builds on the frame beat N left behind; the diagram accumulates rather
    than being wiped and redrawn.
- Name 2-4 concrete things per scene that will get short on-screen labels (≤3 words),
  so the coder has real content to reveal instead of animating unlabeled shapes.
- The final beat of every scene must leave the core diagram + title on screen.

NARRATION QUALITY (this is the script — it is what the learner hears):
- Explain causally, in the order the visual builds: state the thing, then why it
  follows. Prefer "because", "which means", "so" over listing facts.
- Say the concrete numbers out loud when the visual shows them.
- No filler ("let's dive in", "as we can see", "it's important to note"), no naming
  the format ("in this scene"), no promises about later scenes beyond one hand-off
  clause. Every sentence must carry information.

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
      "style_tags": [string],
      "covers_steps": [string]
    }
  ]
}
""".replace("__SCENE_MIN__", f"{MIN_SCENE_SECONDS:.0f}")


# Full multi-scene plans (esp. non-English) routinely exceed 4k completion
# tokens; truncating mid-JSON yields metadata-only objects missing `scenes`.
PLANNER_MAX_TOKENS: dict[str, int] = {
    "clip": 4096,
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
    blueprint: Optional[TeachingBlueprint] = None,
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

    blueprint_block = (
        f"""TEACHING PLAN (already decided — STAGE it, do not re-derive or reorder it.
Every step below must be delivered, in this order, and every scene must record the
step id(s) it delivers in its `covers_steps` field):

{format_blueprint_for_planner(blueprint)}

"""
        if blueprint is not None and blueprint.steps
        else ""
    )
    user = f"""Learner prompt:
{prompt}

{blueprint_block}Length preset ({length_preset}): {length}
Scene pacing ({pacing}): {SCENE_PACING_GUIDANCE[pacing]}
"""
    if length_preset == "clip":
        user += f"""HARD REQUIREMENT: {min_scenes}-{max_scenes} scenes, each with duration_seconds
so the TOTAL is 8–15 seconds. This is a looping GIF, not a lecture. Put the
idea in the MOTION. Narration is optional and short (labels / one line).
The opening pose should match the closing pose so the loop is invisible.
"""
    else:
        user += f"""HARD REQUIREMENT (checked programmatically — the plan will be rejected and
retried if this is not met): the sum of every scene's spoken narration must
land between {min_target:.0f} and {max_target:.0f} seconds total, across
{min_scenes}-{max_scenes} scenes. Write full, complete narration sentences —
not short filler lines — so the natural spoken duration reaches this target;
padding with silence/wait time does not count, only actual narration length.
Individual scenes may run longer when the idea needs it.
"""
    user += f"""Audience ({audience}): {aud}
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
            # Soft checks: worth a retry, never worth failing the whole job —
            # an imperfect plan still beats no video at all.
            if attempt < 2:
                _validate_beat_narration(plan)
                if blueprint is not None:
                    _validate_step_coverage(plan, blueprint)
            if blueprint is not None:
                # Carry the teaching plan on the plan itself: codegen reads its
                # notation/visual grammar, and it must survive the round trip
                # through scene_plan.json and the storyboard editor.
                plan = plan.model_copy(update={"blueprint": blueprint})
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
- Keeping each surviving scene's `covers_steps` as it was, and giving any scene
  you add the step id(s) of the teaching plan it sits between (leave it empty
  only when the learner asked for something genuinely outside the plan).
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
            if plan.blueprint is not None:
                # The teaching plan is not the reviser's to rewrite — a scene
                # edit must never silently drop the notation/visual grammar the
                # already-generated scenes were built against.
                revised = revised.model_copy(update={"blueprint": plan.blueprint})
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


def planning_spec_payload() -> dict[str, Any]:
    """Constraints + ScenePlan JSON schema for a host LLM (MCP) to author the plan."""
    from backend.schemas import ScenePlan

    return {
        "role": "You write the storyboard. Now I Get It only validates, renders Manim, and stitches audio.",
        "length_target_seconds": {
            key: {"min": lo, "max": hi} for key, (lo, hi) in LENGTH_TARGET_SECONDS.items()
        },
        "scene_count": {
            length: {
                pacing: {"min": lo, "max": hi}
                for pacing, (lo, hi) in counts.items()
            }
            for length, counts in SCENE_PACING_COUNT.items()
        },
        "min_scene_seconds": MIN_SCENE_SECONDS,
        "audience_guidance": AUDIENCE_GUIDANCE,
        "pacing_guidance": SCENE_PACING_GUIDANCE,
        "rules": [
            "Every scene needs an id (scene_1, scene_2, …), title, duration_seconds, and beats.",
            "Each beat has visual_action (what moves on screen) and narration (spoken, not on-screen dump).",
            "Narration language must match the requested language. Keep on-screen text sparse.",
            "Reuse palette + recurring_elements so scenes look like one video.",
            "Do not use MathTex/LaTeX in later Manim code — plan visuals that work with plain Text().",
            "Total spoken duration should land inside length_target_seconds for the chosen preset.",
            "If length_preset is clip: 1–2 scenes totaling 8–15 seconds, looping GIF. One motion, one idea. Match the opening and closing pose. Narration is optional short labels — not a lecture.",
        ],
        "plan_schema": ScenePlan.model_json_schema(),
        "example_scene": {
            "id": "scene_1",
            "title": "The question",
            "duration_seconds": 12,
            "visual_description": "A simple two-node network; an arrow labeled error points backward.",
            "visual_device": "equation_reveal",
            "beats": [
                {
                    "visual_action": "Fade in two circles labeled input and output, then grow an arrow between them.",
                    "narration": "A neural net turns inputs into a prediction.",
                },
                {
                    "visual_action": "Show a small number next to the arrow, then reverse the arrow in a contrasting color.",
                    "narration": "Backpropagation sends the error backward so each weight can take a share of the blame.",
                },
            ],
        },
    }
