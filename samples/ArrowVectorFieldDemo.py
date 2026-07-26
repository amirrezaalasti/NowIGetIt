from manim import *


class ArrowVectorFieldDemo(Scene):
    """Built-in ArrowVectorField — physics/flow without manim_physics."""

    def construct(self):
        title = Text("Vector field", font_size=36).to_edge(UP, buff=0.3)
        field = ArrowVectorField(
            lambda p: np.array([p[1], -p[0], 0]),
            x_range=[-3, 3, 0.75],
            y_range=[-2.2, 2.2, 0.75],
        )
        field.move_to(ORIGIN + DOWN * 0.15)
        charge = Dot(ORIGIN, radius=0.12, color=YELLOW)
        caption = Text("rotation field around a point", font_size=28).to_edge(
            DOWN, buff=0.35
        )

        self.play(Write(title), FadeIn(charge), run_time=0.8)
        self.play(Create(field), FadeIn(caption), run_time=2.0)
        self.play(charge.animate.scale(1.4), run_time=0.5)
        self.play(charge.animate.scale(1 / 1.4), run_time=0.5)
        self.wait(0.5)
