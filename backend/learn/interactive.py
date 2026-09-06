"""Interactive labs: a parameterized visualization + learning phases."""

from __future__ import annotations

from typing import Any, Callable, Optional

from backend.languages import language_display_name, normalize_language
from backend.learn.formulas import extract_names, try_eval
from backend.learn.schemas import (
    InteractiveLesson,
    LabGoal,
    LabParameter,
    LabPhase,
    LabProgressResult,
    LabQuiz,
)
from backend.llm import OpenRouterClient
from backend.pipeline.pedagogy import format_blueprint_for_planner
from backend.schemas import TeachingBlueprint

Progress = Callable[[str, dict[str, Any]], None]

VISUAL_KINDS = (
    "function_plot",
    "projectile",
    "wave",
    "compound_growth",
    "unit_circle",
    "spring",
    "vector_2d",
    "slope_line",
    "geometry",
)

INTERACTIVE_SYSTEM = """You design an interactive learning lab: a live visualization
the learner can drive with sliders, plus a sequence of phases that turn playing
into understanding.

This is NOT a video storyboard and NOT a quiz-first worksheet. It is a tiny
game about one concept. The picture must change when parameters change.

WORK IN THIS ORDER:

1. Pick ONE visual kind from this list (no others):
   - function_plot: y = expr(x, params). Use for curves, parabolas, exponentials.
     Set visual.expr (in terms of x and parameter ids). Set x_min/x_max.
   - slope_line: y = m*x + b. Parameters should include m and b.
   - projectile: 2D throw. Parameters typically v (speed), theta (degrees), g.
     Range = v^2 * sin(2*radians(theta)) / g. Set target_x for a landing challenge.
   - wave: y = A * sin(2*pi*(x/lambda - f*t)). Parameters A, lambda, f.
   - compound_growth: bars/curve of principal*(1+rate)^periods.
     Parameters principal, rate, periods.
   - unit_circle: angle theta in degrees; show sin/cos projections.
   - spring: mass-spring. Parameters mass, k, amplitude. x = A*cos(sqrt(k/mass)*t)
   - vector_2d: arrows. Parameters vx, vy (or mag, theta).
   - geometry: points whose x/y are expressions of parameters, plus segments.
     Example triangle: points A(0,0), B(base,0), C(base/2, height).

2. PARAMETERS. 2–5 sliders. Each has id (letter-starting identifier used in
   formulas), label, min, max, step, default, unit, description. Defaults should
   make a clear, non-degenerate picture. Ids MUST be the names used in expr.

3. READOUTS. 1–4 live computed values (range, period, slope, area, …). expr uses
   only parameter ids and functions sin,cos,tan,sqrt,exp,log,abs,min,max,pow,
   radians,degrees,pi,e. No x or t in readouts (those are plot variables).

4. PHASES — the learner walks these in order. 6 or 7 phases, these kinds:
   1. orient: see the system at defaults. goal.type=observe. Lock nothing
      essential, or lock one param so the first picture is stable.
   2. explore: freely change ONE highlighted parameter. goal.type=change_param
      with param=<id> and min_delta large enough they must actually move it.
   3. predict: lock the sliders. Ask a multiple-choice question about what will
      happen if that param changes. goal MUST be:
      {"type":"quiz","quiz":{"prompt":"...?","choices":[{"id":"a","text":"..."},
      {"id":"b","text":"..."},{"id":"c","text":"..."}],"correct":"a",
      "explanation":"..."}}
      Never leave quiz.prompt empty. Put the question inside goal.quiz, not on
      the phase.
   4. test: unlock, have them try it. goal.type=observe. success text confirms
      or corrects the prediction.
   5. challenge: a game. goal.type=target — a readout must fall within
      tolerance of value (hit a range, make the slope = 2, land on a mark).
      Optionally set visual.target_x / target_y for projectile.
   6. check: another quiz that uses the mechanism, not trivia. Same quiz
      object shape as predict: goal.type=quiz AND goal.quiz.prompt + choices.
   7. reflect: name the payoff. goal.type=acknowledge.

   Each phase: id, kind, title, coach (2–5 sentences, second person, in the
   output language), locked_params (ids they cannot move), optional
   suggested_params, goal, hint, success.

5. Coach text talks about WHAT TO DO WITH THE SLIDERS, not a lecture. The
   picture carries the idea.

Return ONLY JSON:
{
  "title": string,
  "tagline": string,
  "core_question": string,
  "payoff": string,
  "running_example": string,
  "visual": {
    "kind": one of the kinds above,
    "title": string,
    "x_label": string,
    "y_label": string,
    "x_min": number, "x_max": number,
    "y_min": number|null, "y_max": number|null,
    "expr": string,
    "animate": true,
    "points": [{"id":"A","x":"0","y":"0","label":"A"}],
    "segments": [["A","B"]],
    "fills": [["A","B","C"]],
    "target_x": number|null,
    "target_y": number|null,
    "target_radius": number
  },
  "parameters": [{"id":"v","label":"Launch speed","min":5,"max":40,"step":1,
                  "default":20,"unit":"m/s","description":"..."}],
  "readouts": [{"id":"range","label":"Range","expr":"...","unit":"m","precision":2}],
  "phases": [...],
  "misconceptions": [string]
}
"""


def generate_interactive_lesson(
    client: OpenRouterClient,
    prompt: str,
    blueprint: TeachingBlueprint,
    *,
    audience: str = "general",
    language: str = "en",
    on_progress: Optional[Progress] = None,
) -> InteractiveLesson:
    lang = normalize_language(language)
    lang_name = language_display_name(lang)
    user = f"""Learner prompt:
{prompt}

Audience: {audience}
Output language: write coach text, titles, questions, labels in {lang_name}.
Parameter ids, expressions, and kind stay in ASCII.

Allowed visual kinds: {", ".join(VISUAL_KINDS)}

Teaching plan (the lab must earn the same ideas, as play rather than scenes):
{format_blueprint_for_planner(blueprint)}
"""
    last_err: Optional[Exception] = None
    for attempt in range(3):
        if on_progress:
            on_progress(
                f"Designing the lab (attempt {attempt + 1}/3)…",
                {"step": "lab.llm", "attempt": attempt + 1},
            )
        try:
            data = client.chat_json(
                system=INTERACTIVE_SYSTEM,
                user=user,
                temperature=0.35 + attempt * 0.1,
                max_tokens=8192,
            )
            lesson = InteractiveLesson.model_validate(data)
            _repair_lesson(lesson)
            _validate_lesson(lesson)
            return lesson
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            user += f"\n\nERROR on last attempt: {exc}\nReturn valid JSON matching the schema."
    raise ValueError(f"Failed to design interactive lab: {last_err}") from last_err


def _repair_lesson(lesson: InteractiveLesson) -> None:
    """Fill in the shapes the model often omits so Play can still start."""
    param_ids = [p.id for p in lesson.parameters]
    extra = {"x", "t", "theta"}
    defaults = {p.id: p.default for p in lesson.parameters}
    kept = []
    for readout in lesson.readouts:
        try:
            names = extract_names(readout.expr)
        except (ValueError, SyntaxError, TypeError):
            continue
        if names - set(param_ids) - extra:
            continue
        try_eval(readout.expr, defaults)
        kept.append(readout)
    lesson.readouts = kept
    readout_ids = [r.id for r in lesson.readouts]

    vis = lesson.visual
    if vis.kind in {"function_plot", "slope_line", "wave"} and not (vis.expr or "").strip():
        if vis.kind == "slope_line":
            vis.expr = "m*x + b" if {"m", "b"} <= set(param_ids) else (
                f"{param_ids[0]}*x" if param_ids else "x"
            )
        elif vis.kind == "wave":
            vis.expr = "A*sin(x)" if "A" in param_ids else (
                f"{param_ids[0]}*sin(x)" if param_ids else "sin(x)"
            )
        else:
            vis.expr = "x"

    seen: set[str] = set()
    for i, phase in enumerate(lesson.phases):
        pid = (phase.id or phase.kind or f"phase_{i}").strip()
        if pid in seen:
            pid = f"{pid}_{i}"
        phase.id = pid
        seen.add(pid)
        goal = phase.goal
        if phase.kind in {"predict", "check"} and goal.type != "quiz":
            goal.type = "quiz"
        if goal.type == "quiz":
            prompt = (goal.quiz.prompt if goal.quiz else "") or phase.coach or phase.title
            if not goal.quiz or not (goal.quiz.prompt or "").strip():
                goal.quiz = LabQuiz(
                    prompt=(prompt or "What did the picture just show?").strip()
                )
        if goal.type == "change_param":
            if goal.param not in param_ids and param_ids:
                unlocked = [p for p in param_ids if p not in phase.locked_params]
                goal.param = (unlocked or param_ids)[0]
            if goal.min_delta <= 0 and goal.param:
                spec = next((p for p in lesson.parameters if p.id == goal.param), None)
                span = (spec.max - spec.min) if spec else 1.0
                goal.min_delta = max(abs(span) * 0.15, spec.step if spec else 0.1)
        if phase.kind == "explore" and goal.type == "observe" and param_ids:
            goal.type = "change_param"
            unlocked = [p for p in param_ids if p not in phase.locked_params]
            goal.param = (unlocked or param_ids)[0]
            spec = next((p for p in lesson.parameters if p.id == goal.param), None)
            span = (spec.max - spec.min) if spec else 1.0
            goal.min_delta = max(abs(span) * 0.15, spec.step if spec else 0.1)
        if goal.type == "target":
            if goal.readout not in readout_ids:
                if readout_ids:
                    goal.readout = readout_ids[0]
                else:
                    goal.type = "observe"
            if goal.tolerance <= 0:
                goal.tolerance = 1.0
        if phase.kind == "reflect" and goal.type == "observe":
            goal.type = "acknowledge"


def _validate_lesson(lesson: InteractiveLesson) -> None:
    if lesson.visual.kind not in VISUAL_KINDS:
        raise ValueError(f"unsupported visual kind: {lesson.visual.kind}")
    if len(lesson.parameters) < 2:
        raise ValueError("lab needs at least 2 parameters the learner can change")
    if len(lesson.phases) < 5:
        raise ValueError("lab needs at least 5 learning phases")
    ids = {p.id for p in lesson.parameters}
    kinds = [p.kind for p in lesson.phases]
    if "orient" not in kinds or "explore" not in kinds:
        raise ValueError("lab must include orient and explore phases")
    if "challenge" not in kinds and "check" not in kinds:
        raise ValueError("lab must include a challenge or a check phase")

    extra = {"x", "t", "theta"}
    for readout in lesson.readouts:
        try:
            names = extract_names(readout.expr)
        except (ValueError, SyntaxError, TypeError) as exc:
            raise ValueError(f"readout {readout.id} has a bad expression") from exc
        unknown = names - ids - extra
        if unknown:
            raise ValueError(
                f"readout {readout.id} uses unknown names: {', '.join(sorted(unknown))}"
            )
        defaults = {p.id: p.default for p in lesson.parameters}
        try_eval(readout.expr, defaults)

    vis = lesson.visual
    if vis.kind in {"function_plot", "slope_line", "wave"} and not vis.expr.strip():
        raise ValueError(f"{vis.kind} needs visual.expr")
    if vis.kind == "geometry":
        if len(vis.points) < 2 or not vis.segments:
            raise ValueError("geometry needs points and segments")
        defaults = {p.id: p.default for p in lesson.parameters}
        for pt in vis.points:
            try_eval(pt.x, defaults)
            try_eval(pt.y, defaults)

    for phase in lesson.phases:
        unknown_lock = [p for p in phase.locked_params if p not in ids]
        if unknown_lock:
            raise ValueError(f"phase {phase.id} locks unknown params: {unknown_lock}")
        _validate_goal(phase.goal, ids, {r.id for r in lesson.readouts})


def _validate_goal(goal: LabGoal, param_ids: set[str], readout_ids: set[str]) -> None:
    if goal.type == "change_param":
        if goal.param not in param_ids:
            raise ValueError(f"change_param goal needs a known param (got {goal.param!r})")
        if goal.min_delta <= 0:
            raise ValueError("change_param min_delta must be > 0")
    elif goal.type == "target":
        if goal.readout not in readout_ids:
            raise ValueError(f"target goal needs a known readout (got {goal.readout!r})")
    elif goal.type == "quiz":
        if not goal.quiz or not (goal.quiz.prompt or "").strip():
            raise ValueError("quiz goal is missing a question")
        if goal.quiz.choices and goal.quiz.correct not in {c.id for c in goal.quiz.choices}:
            raise ValueError("quiz correct id is not a choice")


def default_params(parameters: list[LabParameter]) -> dict[str, float]:
    return {p.id: float(p.default) for p in parameters}


def compute_readouts(
    lesson: InteractiveLesson, params: dict[str, float]
) -> dict[str, float]:
    merged = default_params(lesson.parameters)
    merged.update({k: float(v) for k, v in params.items() if k in merged})
    out: dict[str, float] = {}
    for readout in lesson.readouts:
        out[readout.id] = try_eval(readout.expr, merged)
    return out


def evaluate_goal(
    lesson: InteractiveLesson,
    phase: LabPhase,
    *,
    params: dict[str, float],
    answers: dict[str, str],
    baseline: Optional[dict[str, float]] = None,
) -> tuple[bool, str, dict[str, float]]:
    readouts = compute_readouts(lesson, params)
    goal = phase.goal
    if goal.type == "observe" or goal.type == "acknowledge":
        return True, phase.success or "Onward.", readouts
    if goal.type == "change_param":
        current = float(params.get(goal.param, 0.0))
        start = float((baseline or {}).get(goal.param, current))
        if abs(current - start) + 1e-9 >= float(goal.min_delta):
            return True, phase.success or "You changed it — watch what the picture did.", readouts
        return False, phase.hint or f"Move {goal.param} more — the picture has to change.", readouts
    if goal.type == "target":
        got = readouts.get(goal.readout)
        if got is None:
            return False, "That readout isn't available.", readouts
        if abs(got - float(goal.value)) <= float(goal.tolerance):
            return True, phase.success or "Hit the mark.", readouts
        return (
            False,
            phase.hint
            or f"{goal.readout} is {got:.3g}; aim for {goal.value:g} ± {goal.tolerance:g}.",
            readouts,
        )
    if goal.type == "quiz" and goal.quiz:
        given = (answers.get(phase.id) or answers.get(goal.quiz.prompt) or "").strip().lower()
        expected = (goal.quiz.correct or "").strip().lower()
        if not expected and not goal.quiz.choices:
            return True, goal.quiz.explanation or phase.success or "Onward.", readouts
        if given and given == expected:
            return True, goal.quiz.explanation or phase.success or "That's it.", readouts
        if given:
            return False, goal.quiz.explanation or phase.hint or "Not quite — try again.", readouts
        return False, phase.hint or "Answer the question to continue.", readouts
    return False, phase.hint or "Keep going.", readouts


def apply_progress(
    lesson: InteractiveLesson,
    *,
    phase_id: str,
    params: dict[str, float],
    answers: dict[str, str],
    completed_phases: list[str],
    baseline: Optional[dict[str, float]] = None,
) -> LabProgressResult:
    phase = next((p for p in lesson.phases if p.id == phase_id), None)
    if phase is None:
        raise ValueError(f"unknown phase: {phase_id}")
    met, message, readouts = evaluate_goal(
        lesson,
        phase,
        params=params,
        answers=answers,
        baseline=baseline,
    )
    done = list(completed_phases)
    if met and phase.id not in done:
        done.append(phase.id)
    return LabProgressResult(
        id="",
        phase_id=phase.id,
        goal_met=met,
        message=message,
        readouts=readouts,
        completed_phases=done,
    )
