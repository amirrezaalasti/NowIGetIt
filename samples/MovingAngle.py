from manim import *


class MovingAngle(Scene):
    """ValueTracker-driven angle — geometry / trig scenes."""

    def construct(self):
        rotation_center = LEFT
        theta_tracker = ValueTracker(110)

        line1 = Line(LEFT, RIGHT, color=WHITE)
        line_moving = Line(LEFT, RIGHT, color=BLUE)
        line_ref = line_moving.copy()
        line_moving.rotate(
            theta_tracker.get_value() * DEGREES, about_point=rotation_center
        )

        angle = Angle(line1, line_moving, radius=0.5, other_angle=False, color=RED)
        label = Text("θ", font_size=36, color=WHITE).move_to(
            Angle(
                line1, line_moving, radius=0.5 + 3 * SMALL_BUFF, other_angle=False
            ).point_from_proportion(0.5)
        )

        group = VGroup(line1, line_moving, angle, label).move_to(ORIGIN)
        self.play(Create(line1), Create(line_moving), Create(angle), FadeIn(label))

        line_moving.add_updater(
            lambda x: x.become(line_ref.copy()).rotate(
                theta_tracker.get_value() * DEGREES, about_point=rotation_center
            )
        )
        angle.add_updater(
            lambda x: x.become(
                Angle(line1, line_moving, radius=0.5, other_angle=False, color=RED)
            )
        )
        label.add_updater(
            lambda x: x.move_to(
                Angle(
                    line1, line_moving, radius=0.5 + 3 * SMALL_BUFF, other_angle=False
                ).point_from_proportion(0.5)
            )
        )

        self.play(theta_tracker.animate.set_value(40), run_time=1.5)
        self.play(theta_tracker.animate.increment_value(140), run_time=2.0)
        self.play(label.animate.set_color(YELLOW), run_time=0.4)
        self.play(theta_tracker.animate.set_value(350), run_time=2.0)
        self.wait(0.5)
