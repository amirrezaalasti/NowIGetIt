from manim import *


class PointMovingOnShapes(Scene):
    """MoveAlongPath + Rotating — particle / orbit motion (Manim docs)."""

    def construct(self):
        title = Text("Move along a path", font_size=36).to_edge(UP, buff=0.3)
        circle = Circle(radius=1.4, color=BLUE).move_to(ORIGIN + DOWN * 0.2)
        dot = Dot(color=YELLOW)
        self.play(Write(title), GrowFromCenter(circle), FadeIn(dot), run_time=1.2)
        self.play(MoveAlongPath(dot, circle), run_time=2.5, rate_func=linear)
        self.play(Rotating(dot, about_point=circle.get_center()), run_time=1.5)
        self.wait(0.5)
