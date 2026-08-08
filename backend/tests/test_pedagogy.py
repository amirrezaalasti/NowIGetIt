"""The teaching blueprint (step 0) and the storyboard's coverage of it."""

from __future__ import annotations

import pytest

from backend.pipeline.pedagogy import (
    _normalize_step_ids,
    _validate_blueprint,
    format_blueprint_for_codegen,
    format_blueprint_for_planner,
)
from backend.pipeline.planner import _validate_step_coverage
from backend.schemas import (
    BlueprintStep,
    NotationEntry,
    Relation,
    SceneSection,
    ScenePlan,
    TeachingBlueprint,
)


def _blueprint(step_count: int = 3) -> TeachingBlueprint:
    return TeachingBlueprint(
        core_question="Why does gradient descent settle at the bottom?",
        payoff="Predict where the next step lands.",
        running_example="The parabola y = x^2 starting at x = -2 with step size 0.3",
        notation=[
            NotationEntry(
                symbol="x",
                meaning="current position",
                visual_encoding="orange dot on the curve",
            )
        ],
        relations=[
            Relation(
                expression="x_next = x - 0.3 * slope",
                reads_as="step downhill by a fraction of the slope",
                how_to_show="drag the dot along the tangent before the symbols appear",
            )
        ],
        steps=[
            BlueprintStep(
                id=f"step_{i + 1}",
                claim=f"claim {i + 1}",
                why_it_follows="follows from the previous rung" if i else "",
                uses=["x_next = x - 0.3 * slope"] if i == 1 else [],
                visual_strategy=f"the dot moves to show {i + 1}",
                checkpoint=f"can predict {i + 1}",
            )
            for i in range(step_count)
        ],
        visual_grammar=["vertical axis is always loss"],
    )


def _plan(covers: list[list[str]], blueprint: TeachingBlueprint | None = None) -> ScenePlan:
    return ScenePlan(
        title="t",
        concept_summary="c",
        blueprint=blueprint,
        scenes=[
            SceneSection(
                id=f"scene_{i + 1}",
                title=f"scene {i + 1}",
                narration="n",
                covers_steps=steps,
            )
            for i, steps in enumerate(covers)
        ],
    )


def test_blueprint_needs_a_visual_encoding_for_every_symbol() -> None:
    bp = _blueprint().model_copy(
        update={"notation": [NotationEntry(symbol="x", meaning="position")]}
    )
    with pytest.raises(ValueError, match="visual_encoding"):
        _validate_blueprint(bp, min_steps=3)


def test_blueprint_needs_a_concrete_running_example() -> None:
    bp = _blueprint().model_copy(update={"running_example": "  "})
    with pytest.raises(ValueError, match="running_example"):
        _validate_blueprint(bp, min_steps=3)


def test_blueprint_steps_must_say_why_they_follow() -> None:
    steps = list(_blueprint().steps)
    steps[2] = steps[2].model_copy(update={"why_it_follows": ""})
    with pytest.raises(ValueError, match="why they follow"):
        _validate_blueprint(_blueprint().model_copy(update={"steps": steps}), min_steps=3)


def test_first_step_needs_no_antecedent() -> None:
    _validate_blueprint(_blueprint(), min_steps=3)


def test_too_few_rungs_is_a_summary_not_an_explanation() -> None:
    with pytest.raises(ValueError, match="at least 4 rungs"):
        _validate_blueprint(_blueprint(3), min_steps=4)


def test_step_ids_are_filled_in_when_the_model_omits_them() -> None:
    bp = TeachingBlueprint(
        steps=[BlueprintStep(claim="a"), BlueprintStep(id=" ", claim="b")]
    )
    assert [s.id for s in _normalize_step_ids(bp).steps] == ["step_1", "step_2"]


def test_plain_strings_are_accepted_for_structured_entries() -> None:
    bp = TeachingBlueprint.model_validate(
        {
            "notation": ["x"],
            "relations": ["y = x^2"],
            "steps": ["the dot slides downhill"],
            "misconceptions": ["the step size is the distance moved"],
        }
    )
    assert bp.notation[0].symbol == "x"
    assert bp.relations[0].expression == "y = x^2"
    assert bp.steps[0].claim == "the dot slides downhill"
    assert bp.misconceptions[0].belief.startswith("the step size")


def test_coverage_passes_when_every_step_is_staged_in_order() -> None:
    bp = _blueprint()
    _validate_step_coverage(_plan([["step_1"], ["step_2"], ["step_3"]]), bp)
    # A big step may span two consecutive scenes.
    _validate_step_coverage(_plan([["step_1"], ["step_2"], ["step_2"], ["step_3"]]), bp)


def test_coverage_rejects_a_dropped_step() -> None:
    with pytest.raises(ValueError, match="step_2"):
        _validate_step_coverage(_plan([["step_1"], ["step_3"]]), _blueprint())


def test_coverage_rejects_steps_taught_out_of_order() -> None:
    with pytest.raises(ValueError, match="out of order"):
        _validate_step_coverage(
            _plan([["step_1"], ["step_3"], ["step_2"]]), _blueprint()
        )


def test_coverage_rejects_a_scene_that_teaches_nothing_from_the_plan() -> None:
    with pytest.raises(ValueError, match="scene_2"):
        _validate_step_coverage(
            _plan([["step_1"], [], ["step_2"], ["step_3"]]), _blueprint()
        )


def test_coverage_rejects_unknown_step_ids() -> None:
    with pytest.raises(ValueError, match="unknown step ids"):
        _validate_step_coverage(
            _plan([["step_1"], ["step_2"], ["step_3"], ["step_9"]]), _blueprint()
        )


def test_planner_brief_carries_the_teaching_decisions() -> None:
    text = format_blueprint_for_planner(_blueprint())
    assert "gradient descent settle" in text
    assert "orange dot on the curve" in text
    assert "step_2" in text
    assert "vertical axis is always loss" in text


def test_codegen_brief_narrows_to_this_scene_but_keeps_shared_encodings() -> None:
    text = format_blueprint_for_codegen(_blueprint(), covers_steps=["step_2"])
    assert "claim 2" in text
    assert "claim 3" not in text
    # Notation, visual grammar, and the running example are shared by every scene.
    assert "orange dot on the curve" in text
    assert "vertical axis is always loss" in text
    assert "x^2" in text
    # The relation this step uses comes along; unrelated ones do not.
    assert "drag the dot along the tangent" in text


def test_codegen_brief_is_empty_without_a_blueprint() -> None:
    assert format_blueprint_for_codegen(None, covers_steps=["step_1"]) == ""
