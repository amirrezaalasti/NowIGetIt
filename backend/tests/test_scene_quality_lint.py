"""The lint must catch scenes that fill their runtime with nothing.

Regression case: a 40s "Gebäudehülle" intro whose only Text was the title and
whose beats were pulse/opacity loops, `.scale(1.0)` no-ops, dots flying in and
out, and a trailing wait to pad up to the narration length.
"""

from __future__ import annotations

from backend.code_utils import lint_scene_code
from backend.pipeline.planner import (
    LENGTH_SCENE_COUNT,
    LENGTH_TARGET_SECONDS,
    _validate_plan_length,
    estimate_narration_seconds,
)
from backend.schemas import ScenePlan, SceneSection

MARKER = "# _NOWIGETIT_TEXT_LAYOUT_FIX_V7_END"

FILLER_SCENE = f'''{MARKER}
class Scene1(Scene):
    def construct(self):
        title = Text("Einfuehrung: Die Gebaeudehuelle", font_size=40)
        self.play(FadeIn(title, run_time=2.0))
        self.play(title.animate.scale(0.8).move_to(UP * 3.5 + LEFT * 5), run_time=2.0)
        self.wait(0.78)  # total 6.78s
        glow = Circle(radius=1.0)
        self.play(glow.animate.set_fill_opacity(0.4), run_time=3.0)
        self.play(glow.animate.set_fill_opacity(0.6), run_time=1.5)
        self.play(glow.animate.set_fill_opacity(0.4), run_time=1.5)
        sun = Circle(radius=0.5)
        self.play(FadeIn(sun, run_time=2.5))
        self.play(sun.animate.scale(1.1), run_time=1.5)
        self.play(sun.animate.scale(1.0), run_time=1.5)
        particles = VGroup(Dot(), Dot())
        self.play(particles.animate.set_opacity(0.3).scale(1.5), run_time=1.0)
        self.play(particles.animate.set_opacity(1.0).scale(0.67), run_time=1.0)
        self.wait(0.5)
        self.wait(1.3)  # adjust to reach 40.7s total
'''

TEACHING_SCENE = f'''{MARKER}
class Scene1(Scene):
    def construct(self):
        title = Text("Gradient Descent", font_size=40).to_edge(UP, buff=0.3)
        axes = Axes(x_range=[-3, 3, 1], y_range=[-1, 5, 1], x_length=7, y_length=4.5)
        curve = axes.plot(lambda x: x**2, x_range=[-2.2, 2.2])
        dot = Dot(color=YELLOW).move_to(axes.c2p(-2, 4))
        slope_label = Text("steep slope", font_size=26).next_to(axes, RIGHT, buff=0.25)
        min_label = Text("minimum", font_size=26).next_to(axes.c2p(0, 0), DOWN, buff=0.3)
        self.play(FadeIn(title), run_time=1.2)
        self.play(Create(axes), run_time=1.6)
        self.play(Create(curve), run_time=1.8)
        self.play(FadeIn(dot), FadeIn(slope_label), run_time=1.4)
        tracker = ValueTracker(-2.0)
        dot.add_updater(lambda m: m.move_to(axes.c2p(tracker.get_value(), 0)))
        self.play(tracker.animate.set_value(0.0), run_time=3.5)
        self.play(FadeIn(min_label), run_time=1.2)
        self.play(Indicate(min_label), run_time=1.0)
        self.wait(0.5)
'''


def _issue_text(code: str, duration: float) -> str:
    return " ".join(lint_scene_code(code, target_duration=duration)).lower()


def test_filler_scene_is_flagged_for_every_anti_pattern() -> None:
    issues = _issue_text(FILLER_SCENE, 40.7)
    assert "scale(1.0)" in issues
    assert "breathing" in issues
    assert "opacity oscillation" in issues
    assert "on-screen text label" in issues
    assert "trailing self.wait" in issues
    assert "runtime-arithmetic comments" in issues


def test_teaching_scene_passes_lint() -> None:
    assert lint_scene_code(TEACHING_SCENE, target_duration=14.0) == []


def test_updater_driven_wait_is_not_treated_as_dead_time() -> None:
    # With add_updater / always_redraw, self.wait() IS the animation.
    spinning = (
        f"{MARKER}\nclass S(Scene):\n    def construct(self):\n"
        '        label = Text("orbit", font_size=26)\n'
        '        caption = Text("one period", font_size=24)\n'
        "        dot = Dot()\n"
        "        dot.add_updater(lambda m, dt: m.rotate(dt))\n"
        "        self.play(FadeIn(label), FadeIn(caption), run_time=1.0)\n"
        "        self.wait(8.0)\n"
    )
    assert lint_scene_code(spinning, target_duration=9.0) == []


def test_handcrafted_samples_stay_clean() -> None:
    from pathlib import Path

    samples = sorted(Path("samples").glob("*.py"))
    assert samples, "sample scenes are the false-positive corpus"
    for path in samples:
        assert lint_scene_code(path.read_text(), target_duration=None) == [], path.name


def test_short_scene_is_not_required_to_carry_labels() -> None:
    tiny = f'{MARKER}\nclass S(Scene):\n    def construct(self):\n        t = Text("Hi")\n        self.play(FadeIn(t), run_time=2.0)\n        self.wait(0.5)\n'
    assert lint_scene_code(tiny, target_duration=3.0) == []


def _scene(sid: str, words: int) -> SceneSection:
    return SceneSection(
        id=sid,
        title=sid,
        narration=" ".join(["wort"] * words),
        visual_description="d",
        duration_seconds=12.0,
    )


def test_long_individual_scenes_are_allowed_when_total_fits() -> None:
    # A ~40s scene used to be rejected by the 20s ceiling; totals still gate length.
    scenes = [_scene(f"scene_{i}", 40) for i in range(9)] + [_scene("scene_big", 100)]
    plan = ScenePlan(title="t", concept_summary="c", scenes=scenes)
    # 9*16s + 40s ≈ 184s — inside deep target; the long scene alone must not fail.
    _validate_plan_length(plan, length_preset="deep", language="en")
    assert estimate_narration_seconds(scenes[-1].narration, "en") > 20.0


def test_deep_preset_reaches_its_target_with_many_scenes() -> None:
    min_scenes, max_scenes = LENGTH_SCENE_COUNT["deep"]
    min_target, max_target = LENGTH_TARGET_SECONDS["deep"]
    # 11 scenes x ~16s of narration each ≈ 176s: inside the target.
    scenes = [_scene(f"scene_{i}", 40) for i in range(11)]
    plan = ScenePlan(title="t", concept_summary="c", scenes=scenes)
    _validate_plan_length(plan, length_preset="deep", language="en")

    per_scene = estimate_narration_seconds(scenes[0].narration, "en")
    assert min_scenes <= len(scenes) <= max_scenes
    assert min_target <= per_scene * len(scenes) <= max_target
