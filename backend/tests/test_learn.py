"""Podcast / quiz / interactive lab helpers."""

from __future__ import annotations

from backend.learn.formulas import eval_expr, extract_names, try_eval
from backend.learn.interactive import apply_progress, evaluate_goal, _validate_lesson
from backend.learn.quiz import grade_paper
from backend.learn.schemas import (
    InteractiveLesson,
    LabGoal,
    LabParameter,
    LabPhase,
    LabQuiz,
    LabReadout,
    LabVisual,
    QuizAnswer,
    QuizChoice,
    QuizPaper,
    QuizQuestion,
)


def _parabola_lab() -> InteractiveLesson:
    return InteractiveLesson(
        title="Gradient on a parabola",
        core_question="Where does the next step land?",
        visual=LabVisual(
            kind="function_plot",
            expr="a*x**2 + b*x + c",
            x_min=-4,
            x_max=4,
        ),
        parameters=[
            LabParameter(id="a", label="a", min=0.2, max=2.0, step=0.1, default=1.0),
            LabParameter(id="b", label="b", min=-2.0, max=2.0, step=0.1, default=0.0),
            LabParameter(id="c", label="c", min=-2.0, max=2.0, step=0.1, default=0.0),
        ],
        readouts=[
            LabReadout(id="vertex", label="Vertex x", expr="-b/(2*a)", unit=""),
        ],
        phases=[
            LabPhase(
                id="orient",
                kind="orient",
                title="Meet the curve",
                coach="This is y = a x^2 + b x + c.",
                goal=LabGoal(type="observe"),
            ),
            LabPhase(
                id="explore",
                kind="explore",
                title="Bend it",
                coach="Drag a.",
                goal=LabGoal(type="change_param", param="a", min_delta=0.3),
            ),
            LabPhase(
                id="predict",
                kind="predict",
                title="Guess the vertex",
                coach="If b is 0, where is the bottom?",
                goal=LabGoal(
                    type="quiz",
                    quiz=LabQuiz(
                        prompt="If b = 0, the vertex x is",
                        choices=[
                            QuizChoice(id="a", text="0"),
                            QuizChoice(id="b", text="1"),
                        ],
                        correct="a",
                        explanation="−b / 2a is 0 when b is 0.",
                    ),
                ),
            ),
            LabPhase(
                id="test",
                kind="test",
                title="Try it",
                coach="Set b to 0.",
                goal=LabGoal(type="observe"),
            ),
            LabPhase(
                id="challenge",
                kind="challenge",
                title="Park the vertex",
                coach="Make the vertex sit at x = 1.",
                goal=LabGoal(type="target", readout="vertex", value=1.0, tolerance=0.15),
            ),
            LabPhase(
                id="reflect",
                kind="reflect",
                title="Payoff",
                coach="You can now move the bottom by choosing a and b.",
                goal=LabGoal(type="acknowledge"),
            ),
        ],
    )


def test_eval_expr_and_names() -> None:
    assert abs(eval_expr("a*x**2 + b", {"a": 2, "x": 3, "b": 1}) - 19) < 1e-9
    assert abs(eval_expr("sin(pi/2)", {}) - 1) < 1e-9
    assert extract_names("v^2 * sin(2*radians(theta)) / g") == {"v", "theta", "g"}
    assert try_eval("1/0", {}) == 0.0


def test_eval_rejects_attribute_access() -> None:
    import pytest

    with pytest.raises(ValueError):
        eval_expr("__import__('os').system('pwd')", {})


def test_quiz_grading_numeric_and_mc() -> None:
    paper = QuizPaper(
        title="t",
        questions=[
            QuizQuestion(
                id="q1",
                type="multiple_choice",
                prompt="pick",
                choices=[
                    QuizChoice(id="a", text="one"),
                    QuizChoice(id="b", text="two"),
                    QuizChoice(id="c", text="three"),
                ],
                correct="b",
            ),
            QuizQuestion(
                id="q2",
                type="numeric",
                prompt="half",
                correct="0.5",
                numeric_tolerance=0.02,
            ),
            QuizQuestion(
                id="q3",
                type="short_answer",
                prompt="name",
                correct="vertex",
            ),
        ],
    )
    result = grade_paper(
        paper,
        [
            QuizAnswer(question_id="q1", answer="b"),
            QuizAnswer(question_id="q2", answer="0.49"),
            QuizAnswer(question_id="q3", answer="the vertex"),
        ],
    )
    assert result.correct_count == 3
    assert result.passed


def test_lab_change_param_and_target() -> None:
    lesson = _parabola_lab()
    _validate_lesson(lesson)
    explore = lesson.phases[1]
    met, _, _ = evaluate_goal(
        lesson,
        explore,
        params={"a": 1.0, "b": 0.0, "c": 0.0},
        answers={},
        baseline={"a": 1.0, "b": 0.0, "c": 0.0},
    )
    assert met is False
    met, _, _ = evaluate_goal(
        lesson,
        explore,
        params={"a": 1.5, "b": 0.0, "c": 0.0},
        answers={},
        baseline={"a": 1.0, "b": 0.0, "c": 0.0},
    )
    assert met is True

    challenge = lesson.phases[4]
    # vertex = -b/(2a) = 1 → b = -2a. a=1, b=-2.
    progress = apply_progress(
        lesson,
        phase_id="challenge",
        params={"a": 1.0, "b": -2.0, "c": 0.0},
        answers={},
        completed_phases=["orient", "explore"],
    )
    assert progress.goal_met
    assert "challenge" in progress.completed_phases
    met, _, _ = evaluate_goal(
        lesson,
        challenge,
        params={"a": 1.0, "b": 0.0, "c": 0.0},
        answers={},
    )
    assert met is False


def test_lab_quiz_phase() -> None:
    lesson = _parabola_lab()
    predict = lesson.phases[2]
    met, _, _ = evaluate_goal(lesson, predict, params={}, answers={"predict": "a"})
    assert met is True
    met, _, _ = evaluate_goal(lesson, predict, params={}, answers={"predict": "b"})
    assert met is False


def test_lab_accepts_flat_quiz_goal() -> None:
    """Models often put prompt/choices on the goal instead of goal.quiz."""
    from backend.learn.interactive import _repair_lesson

    lesson = InteractiveLesson.model_validate(
        {
            "title": "Flat quiz",
            "visual": {"kind": "function_plot", "expr": "a*x + b"},
            "parameters": [
                {"id": "a", "label": "a", "min": 0.2, "max": 2, "default": 1},
                {"id": "b", "label": "b", "min": -2, "max": 2, "default": 0},
            ],
            "readouts": [{"id": "slope", "label": "Slope", "expr": "a"}],
            "phases": [
                {
                    "id": "orient",
                    "kind": "orient",
                    "title": "Look",
                    "coach": "This is a line.",
                    "goal": {"type": "observe"},
                },
                {
                    "id": "explore",
                    "kind": "explore",
                    "title": "Tilt",
                    "coach": "Move a.",
                    "goal": {"type": "change_param", "param": "a"},
                },
                {
                    "id": "predict",
                    "kind": "predict",
                    "title": "Guess",
                    "coach": "What happens if a grows?",
                    "goal": {
                        "type": "quiz",
                        "prompt": "If a increases, the line",
                        "choices": ["gets steeper", "gets flatter", "does not change"],
                        "correct": "gets steeper",
                    },
                },
                {
                    "id": "test",
                    "kind": "test",
                    "title": "Try",
                    "coach": "Drag a.",
                    "goal": {"type": "observe"},
                },
                {
                    "id": "challenge",
                    "kind": "challenge",
                    "title": "Hit 2",
                    "coach": "Make the slope 2.",
                    "goal": {"type": "target", "readout": "slope", "value": 2},
                },
                {
                    "id": "check",
                    "kind": "check",
                    "title": "Check",
                    "coach": "The slope of y = a x + b is a. True or not?",
                },
            ],
        }
    )
    _repair_lesson(lesson)
    _validate_lesson(lesson)
    predict = next(p for p in lesson.phases if p.kind == "predict")
    assert predict.goal.quiz is not None
    assert "increases" in predict.goal.quiz.prompt
    assert any("steeper" in c.text for c in predict.goal.quiz.choices)
    assert predict.goal.quiz.correct in {c.id for c in predict.goal.quiz.choices}
    check = next(p for p in lesson.phases if p.kind == "check")
    assert check.goal.type == "quiz"
    assert check.goal.quiz and check.goal.quiz.prompt
    explore = next(p for p in lesson.phases if p.kind == "explore")
    assert explore.goal.min_delta > 0


def test_lab_quiz_goal_without_nested_question_uses_coach() -> None:
    from backend.learn.interactive import _repair_lesson

    lesson = InteractiveLesson.model_validate(
        {
            "title": "Empty quiz",
            "visual": {"kind": "function_plot", "expr": "a*x"},
            "parameters": [
                {"id": "a", "label": "a", "min": 0.5, "max": 2, "default": 1},
                {"id": "b", "label": "b", "min": 0, "max": 1, "default": 0.5},
            ],
            "phases": [
                {
                    "id": "orient",
                    "kind": "orient",
                    "title": "Look",
                    "coach": "See the line.",
                    "goal": {"type": "observe"},
                },
                {
                    "id": "explore",
                    "kind": "explore",
                    "title": "Move",
                    "coach": "Drag a.",
                    "goal": {"type": "change_param", "param": "a", "min_delta": 0.2},
                },
                {
                    "id": "predict",
                    "kind": "predict",
                    "title": "Guess",
                    "coach": "If a doubles, does the slope double?",
                    "goal": {"type": "quiz"},
                },
                {
                    "id": "test",
                    "kind": "test",
                    "title": "Try",
                    "coach": "Try it.",
                    "goal": {"type": "observe"},
                },
                {
                    "id": "check",
                    "kind": "check",
                    "title": "Check",
                    "coach": "Name the slope.",
                    "goal": {"type": "quiz"},
                },
            ],
        }
    )
    _repair_lesson(lesson)
    _validate_lesson(lesson)
    predict = next(p for p in lesson.phases if p.kind == "predict")
    assert predict.goal.quiz and "slope" in predict.goal.quiz.prompt.lower()
