from manim import *


class VectorArrow(Scene):
    """NumberPlane + labeled vector (Manim docs VectorArrow)."""

    def construct(self):
        title = Text("Vector on a plane", font_size=36).to_edge(UP, buff=0.3)
        plane = NumberPlane(
            x_range=[-4, 4, 1],
            y_range=[-3, 3, 1],
            x_length=10,
            y_length=6,
            background_line_style={"stroke_opacity": 0.35},
        ).move_to(ORIGIN + DOWN * 0.15)

        start = plane.c2p(0, 0)
        end = plane.c2p(2, 2)
        dot = Dot(start, color=YELLOW)
        arrow = Arrow(start, end, buff=0, color=ORANGE)
        origin_text = Text("(0, 0)", font_size=28).next_to(dot, DOWN, buff=0.15)
        tip_text = Text("(2, 2)", font_size=28).next_to(arrow.get_end(), RIGHT, buff=0.15)

        self.play(Write(title), Create(plane), run_time=1.2)
        self.play(FadeIn(dot), GrowArrow(arrow), FadeIn(origin_text), FadeIn(tip_text))
        self.wait(0.5)
