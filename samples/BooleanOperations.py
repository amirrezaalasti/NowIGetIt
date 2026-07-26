from manim import *


class BooleanOperations(Scene):
    """Set ops via Intersection/Union/Exclusion/Difference (Manim docs)."""

    def construct(self):
        title = Text("Boolean operations", font_size=36).to_edge(UP, buff=0.3)
        ellipse1 = Ellipse(
            width=3.2, height=3.6, fill_opacity=0.45, color=PURPLE, stroke_width=6
        ).move_to(LEFT * 1.1 + DOWN * 0.2)
        ellipse2 = ellipse1.copy().set_color(TEAL).move_to(RIGHT * 1.1 + DOWN * 0.2)
        self.play(Write(title), FadeIn(ellipse1), FadeIn(ellipse2), run_time=1.0)

        results = VGroup()
        specs = [
            (Intersection, "∩", GOLD),
            (Union, "∪", MAROON),
            (Exclusion, "Δ", BLUE_C),
            (Difference, "−", PINK),
        ]
        for op, name, color in specs:
            shape = op(ellipse1, ellipse2, color=color, fill_opacity=0.55)
            shape.scale(0.28)
            lab = Text(name, font_size=28).next_to(shape, UP, buff=0.12)
            results.add(VGroup(shape, lab))
        results.arrange(RIGHT, buff=0.45).to_edge(DOWN, buff=0.4)

        self.play(
            LaggedStart(
                *[FadeIn(g, shift=UP * 0.2) for g in results],
                lag_ratio=0.2,
            ),
            run_time=2.0,
        )
        self.wait(0.5)
