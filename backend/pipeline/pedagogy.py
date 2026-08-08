"""Step 0: decide HOW to teach the concept, before any scene exists.

The planner is good at producing scenes but bad at deciding what a concept
actually requires: which quantities have to be named before an equation can be
read, which relation has to be earned before the next one means anything, what
each symbol should look like on screen. Asking for scenes first means those
decisions get improvised one scene at a time, which is what produces a video
that shows a formula nobody built up to and colors that change meaning halfway
through.

So this module runs first and produces a `TeachingBlueprint`: the question, the
running example, the notation and its fixed visual encoding, the relations in
the order they are earned, and the ladder of steps. The planner then turns that
ladder into scenes (`covers_steps` records the mapping), and the code generator
reads the notation + visual grammar so every scene draws the same thing the
same way.
"""

from __future__ import annotations

from collections.abc import Callable
from typing import Any, Optional

from backend.languages import language_display_name, normalize_language
from backend.llm import OpenRouterClient
from backend.schemas import TeachingBlueprint

ProgressCallback = Callable[[str, dict[str, Any]], None]

# A ladder shorter than this is a summary, not an explanation.
MIN_BLUEPRINT_STEPS = 3


PEDAGOGY_SYSTEM = """You are a teaching architect. Before any storyboard exists, you
decide HOW a concept should be explained so a learner genuinely understands it.

You are NOT writing scenes, narration, or shot descriptions. You are deciding the
teaching itself: what must be understood first, in what order the ideas are earned,
what each symbol means and what it looks like, and how the mathematics is built up
rather than asserted.

WORK IN THIS ORDER:

1. THE QUESTION. State the ONE question the video answers, in the learner's words —
   the thing they cannot currently do or see. Then state the payoff: what they can do
   or see once it lands. If the payoff is only "they know the definition", find a
   better question.

2. PREREQUISITES. 2-4 things the audience already knows that you will build on. These
   are your anchors — every new idea attaches to one of them.

3. THE RUNNING EXAMPLE. One concrete case worked through the WHOLE explanation, with
   real numbers you commit to now (a specific parabola and a starting x of -2; a 400W
   heater in a 20m² room; the 3-word sentence "the cat sat"). Never "some value",
   never a second unrelated example later. Every abstract claim is demonstrated on
   this one case.

4. NOTATION. Every symbol/quantity/object that will appear. For each, give the meaning
   in plain words AND its visual_encoding: the fixed visual identity it owns for the
   entire video — a color, shape, axis, or screen position (e.g. "orange dot on the
   curve = the current x", "vertical axis = loss, always"). This is a contract: the
   same quantity must look the same in every scene, and two different quantities must
   never share an encoding.

5. RELATIONS. The equations and relationships, in the order they are EARNED — never
   the order a textbook lists them. For each:
   - expression: the relation in plain text (no LaTeX; "x^2", "dL/dw", "E = mc^2").
   - reads_as: how it is spoken aloud, in words, as a sentence about the world.
   - why_true: the reason it holds — the argument, limit, balance, or definition it
     comes from. "It is the standard formula" is not a reason.
   - how_to_show: how the visual makes it obvious BEFORE the symbols appear — what
     moves, what is compared, what is measured. Build an expression term by term,
     each term appearing as the thing it stands for is shown; never drop a finished
     formula on screen and then explain it backwards.

6. MATH TREATMENT. One paragraph: how deep to go for this audience, which steps get
   derived on screen vs. stated, and which algebra is deliberately skipped. Be honest
   about the trade — a derivation nobody can follow teaches less than a clear
   special case.

7. STEPS. The ladder, 4-10 rungs. Each is ONE idea:
   - id: "step_1", "step_2", …
   - claim: the single thing the learner understands after this rung.
   - why_it_follows: what makes it true GIVEN the previous rung. This is the spine of
     the explanation — if a step does not depend on the one before it, the order is
     wrong; reorder until it does.
   - uses: the symbols/relations (by name) this step introduces or leans on. A symbol
     may not be used before the step that introduces it.
   - visual_strategy: what the picture DOES here — the motion, comparison, or change
     that carries the idea (not "show a diagram of X"). Say what accumulates on screen
     from the previous step and what is newly added.
   - checkpoint: the concrete thing the learner could now answer or predict.
   Order the rungs as a real explanation: the question made concrete → the mechanism
   one moving part at a time → the running example worked → the payoff. No
   "introduction" or "summary" rungs that teach nothing.

8. MISCONCEPTIONS. 1-3 wrong beliefs a learner actually arrives with. For each: the
   correction, and how_the_visual_prevents_it — the specific thing the animation must
   show so the wrong reading is not available.

9. VISUAL GRAMMAR. 3-6 invariant rules holding across every scene: what each axis
   means, what direction encodes, which color means "current"/"target"/"error", what
   dimming means. These make the video read as one system.

10. OUT OF SCOPE. 2-4 tempting things you deliberately leave out, so the explanation
    stays one clean line.

Write learner-facing text (claims, meanings, reads_as, checkpoints) in the requested
output language; ids, symbols, and expressions stay in their standard notation.

Return ONLY a JSON object with this shape:
{
  "core_question": string,
  "payoff": string,
  "prerequisites": [string],
  "running_example": string,
  "math_treatment": string,
  "notation": [{"symbol": string, "meaning": string, "visual_encoding": string}],
  "relations": [{"expression": string, "reads_as": string, "why_true": string,
                 "how_to_show": string}],
  "steps": [{"id": "step_1", "claim": string, "why_it_follows": string,
             "uses": [string], "visual_strategy": string, "checkpoint": string}],
  "misconceptions": [{"belief": string, "correction": string,
                      "how_the_visual_prevents_it": string}],
  "visual_grammar": [string],
  "out_of_scope": [string]
}
"""


def _validate_blueprint(blueprint: TeachingBlueprint, *, min_steps: int) -> None:
    """Reject a blueprint that skipped the parts the rest of the pipeline reads."""
    if len(blueprint.steps) < min_steps:
        raise ValueError(
            f"Only {len(blueprint.steps)} teaching steps were returned; this concept "
            f"needs at least {min_steps} rungs that each earn the next one. Break the "
            "explanation down further."
        )
    if not blueprint.core_question.strip():
        raise ValueError("core_question is empty — state the ONE question the video answers.")
    if not blueprint.running_example.strip():
        raise ValueError(
            "running_example is empty — commit to ONE concrete case with real numbers "
            "that the whole explanation works through."
        )
    thin = [
        s.id or s.claim[:40]
        for s in blueprint.steps
        if not s.visual_strategy.strip() or not s.claim.strip()
    ]
    if thin:
        raise ValueError(
            f"Steps {', '.join(thin)} are missing a claim or a visual_strategy. Every "
            "rung needs the one idea it establishes AND what the picture does to carry it."
        )
    missing_why = [s.id or s.claim[:40] for s in blueprint.steps[1:] if not s.why_it_follows.strip()]
    if missing_why:
        raise ValueError(
            f"Steps {', '.join(missing_why)} do not say why they follow from the previous "
            "step. Fill in why_it_follows for every step after the first — that chain is "
            "the explanation."
        )
    if not blueprint.notation:
        raise ValueError(
            "notation is empty — list every symbol/quantity that appears with its "
            "meaning and its fixed visual_encoding."
        )
    unencoded = [n.symbol for n in blueprint.notation if not n.visual_encoding.strip()]
    if unencoded:
        raise ValueError(
            f"Notation entries {', '.join(unencoded[:5])} have no visual_encoding. Each "
            "quantity needs the color/shape/axis/position it owns in every scene."
        )


def _normalize_step_ids(blueprint: TeachingBlueprint) -> TeachingBlueprint:
    """Give every step a stable id so scenes can reference them."""
    steps = []
    for index, step in enumerate(blueprint.steps, start=1):
        step_id = (step.id or "").strip() or f"step_{index}"
        steps.append(step.model_copy(update={"id": step_id}))
    return blueprint.model_copy(update={"steps": steps})


def create_teaching_blueprint(
    client: OpenRouterClient,
    prompt: str,
    *,
    audience_guidance: str = "",
    audience: str = "general",
    language: str = "en",
    min_steps: int = MIN_BLUEPRINT_STEPS,
    max_steps: int = 10,
    on_progress: Optional[ProgressCallback] = None,
) -> TeachingBlueprint:
    """Decide how to teach the concept before any scene is written."""
    lang = normalize_language(language)
    lang_name = language_display_name(lang)

    def _progress(message: str, **data: Any) -> None:
        if on_progress:
            on_progress(message, data)

    user = f"""Learner prompt:
{prompt}

Audience ({audience}): {audience_guidance or "Curious adult audience."}
Output language ({lang}): write learner-facing text in {lang_name}.

Aim for {min_steps}-{max_steps} teaching steps — one idea per rung, each one earned
by the rung before it. The storyboard is built directly from these steps, so a rung
that teaches nothing becomes a scene that teaches nothing.
"""
    _progress(
        "Working out how to teach this — the question, the example, the order…",
        step="blueprint.prepare",
        audience=audience,
        language=lang,
    )
    last_err: Optional[Exception] = None
    for attempt in range(3):
        try:
            _progress(
                f"Designing the explanation (attempt {attempt + 1}/3)…",
                step="blueprint.llm",
                attempt=attempt + 1,
                max_attempts=3,
            )
            data = client.chat_json(
                system=PEDAGOGY_SYSTEM,
                user=user,
                temperature=0.35 + (attempt * 0.1),
                max_tokens=8192,
                model=client.manim_model,
            )
            blueprint = _normalize_step_ids(TeachingBlueprint.model_validate(data))
            _validate_blueprint(blueprint, min_steps=min_steps)
            _progress(
                f"Teaching plan ready: {len(blueprint.steps)} steps · "
                f"{blueprint.core_question[:80]}",
                step="blueprint.done",
                step_count=len(blueprint.steps),
                core_question=blueprint.core_question,
                running_example=blueprint.running_example,
            )
            return blueprint
        except Exception as e:  # noqa: BLE001 — retried with the error fed back
            last_err = e
            _progress(
                f"Teaching plan attempt {attempt + 1} needed a retry: {e}",
                step="blueprint.retry",
                attempt=attempt + 1,
                detail=str(e)[:400],
            )
            user += (
                f"\n\nERROR on last attempt: {e}\n"
                "Return a valid JSON object matching the requested schema."
            )

    raise ValueError(
        f"Failed to generate a teaching blueprint after 3 attempts: {last_err}"
    ) from last_err


def _bullets(lines: list[str]) -> str:
    return "\n".join(f"- {line}" for line in lines if line.strip())


def format_blueprint_for_planner(blueprint: TeachingBlueprint) -> str:
    """The full teaching plan, as the planner's brief."""
    parts: list[str] = []
    if blueprint.core_question:
        parts.append(f"Question the video answers: {blueprint.core_question}")
    if blueprint.payoff:
        parts.append(f"Payoff (what the learner can do after): {blueprint.payoff}")
    if blueprint.running_example:
        parts.append(f"Running example (use THIS one throughout): {blueprint.running_example}")
    if blueprint.prerequisites:
        parts.append("Assumed known:\n" + _bullets(blueprint.prerequisites))
    if blueprint.math_treatment:
        parts.append(f"Mathematical treatment: {blueprint.math_treatment}")
    if blueprint.notation:
        parts.append(
            "Notation — each quantity keeps this exact visual identity in EVERY scene:\n"
            + _bullets(
                [
                    f"{n.symbol} = {n.meaning} → {n.visual_encoding}"
                    for n in blueprint.notation
                ]
            )
        )
    if blueprint.relations:
        parts.append(
            "Relations, in the order they are earned (show the picture before the symbols):\n"
            + "\n".join(
                f"- {r.expression}"
                + (f" — reads as: {r.reads_as}" if r.reads_as else "")
                + (f"\n  why it holds: {r.why_true}" if r.why_true else "")
                + (f"\n  show it by: {r.how_to_show}" if r.how_to_show else "")
                for r in blueprint.relations
            )
        )
    if blueprint.steps:
        parts.append(
            "TEACHING STEPS — the spine of the video, in this order:\n"
            + "\n".join(
                f"- {s.id}: {s.claim}"
                + (f"\n  follows because: {s.why_it_follows}" if s.why_it_follows else "")
                + (f"\n  uses: {', '.join(s.uses)}" if s.uses else "")
                + (f"\n  visually: {s.visual_strategy}" if s.visual_strategy else "")
                + (f"\n  learner can then: {s.checkpoint}" if s.checkpoint else "")
                for s in blueprint.steps
            )
        )
    if blueprint.misconceptions:
        parts.append(
            "Misconceptions to pre-empt:\n"
            + "\n".join(
                f"- believes: {m.belief}"
                + (f"\n  actually: {m.correction}" if m.correction else "")
                + (
                    f"\n  the visual must: {m.how_the_visual_prevents_it}"
                    if m.how_the_visual_prevents_it
                    else ""
                )
                for m in blueprint.misconceptions
            )
        )
    if blueprint.visual_grammar:
        parts.append("Visual grammar (invariant across scenes):\n" + _bullets(blueprint.visual_grammar))
    if blueprint.out_of_scope:
        parts.append("Deliberately out of scope — do NOT add scenes for these:\n" + _bullets(blueprint.out_of_scope))
    return "\n\n".join(parts)


def format_blueprint_for_codegen(
    blueprint: Optional[TeachingBlueprint],
    *,
    covers_steps: Optional[list[str]] = None,
) -> str:
    """The slice of the teaching plan a single scene's coder needs.

    Notation and visual grammar go to every scene (they are what makes scenes
    look like one video); the step detail is narrowed to the steps this scene
    was planned to deliver, so the prompt stays focused.
    """
    if blueprint is None:
        return ""
    parts: list[str] = []
    if blueprint.notation:
        parts.append(
            "Notation → fixed visual encoding (use these EXACT visual identities; the\n"
            "same quantity must look identical in every scene of this video):\n"
            + _bullets(
                [
                    f"{n.symbol} ({n.meaning}): {n.visual_encoding}"
                    for n in blueprint.notation
                    if n.visual_encoding
                ]
            )
        )
    if blueprint.visual_grammar:
        parts.append(
            "Visual grammar — invariant rules for this video:\n"
            + _bullets(blueprint.visual_grammar)
        )

    wanted = {s.strip().lower() for s in (covers_steps or []) if s and s.strip()}
    steps = [s for s in blueprint.steps if s.id.strip().lower() in wanted]
    if steps:
        parts.append(
            "What this scene must actually teach (from the teaching plan):\n"
            + "\n".join(
                f"- {s.id}: {s.claim}"
                + (f"\n  because: {s.why_it_follows}" if s.why_it_follows else "")
                + (f"\n  carry it visually by: {s.visual_strategy}" if s.visual_strategy else "")
                + (f"\n  by the end the learner can: {s.checkpoint}" if s.checkpoint else "")
                for s in steps
            )
        )
        used = {u.strip().lower() for s in steps for u in s.uses}
        relations = [
            r
            for r in blueprint.relations
            if r.expression.strip().lower() in used
            or any(u and u in r.expression.lower() for u in used)
        ]
        if relations:
            parts.append(
                "Relations in play here — build each expression term by term as the\n"
                "thing it stands for appears; never drop a finished formula on screen:\n"
                + "\n".join(
                    f"- {r.expression}"
                    + (f" (reads as: {r.reads_as})" if r.reads_as else "")
                    + (f"\n  show it by: {r.how_to_show}" if r.how_to_show else "")
                    for r in relations
                )
            )
    if blueprint.running_example:
        parts.append(
            f"Running example for the whole video (use its real numbers, not "
            f"placeholders): {blueprint.running_example}"
        )
    return "\n\n".join(parts)
