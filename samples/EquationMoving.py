from manim import *


class EquationMoving(Scene):
    """Highlight terms in an equation with a moving SurroundingRectangle."""

    def construct(self):
        # Prefer separate Text pieces so the framebox can target one term.
        eq = VGroup(
            Text("E", font_size=48),
            Text("=", font_size=48),
            Text("mc²", font_size=48),
        ).arrange(RIGHT, buff=0.2)
        eq.move_to(ORIGIN)

        self.play(Write(eq), run_time=1.0)
        box1 = SurroundingRectangle(eq[0], buff=0.12, color=YELLOW)
        box2 = SurroundingRectangle(eq[2], buff=0.12, color=YELLOW)
        self.play(Create(box1), run_time=0.6)
        self.wait(0.4)
        self.play(ReplacementTransform(box1, box2), run_time=0.8)
        self.wait(0.5)
