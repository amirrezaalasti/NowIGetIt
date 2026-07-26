from manim import *


class PointWithTrace(Scene):
    """Leave a trail behind a moving point (Manim docs PointWithTrace)."""

    def construct(self):
        title = Text("Traced path", font_size=36).to_edge(UP, buff=0.3)
        path = VMobject(color=TEAL, stroke_width=3)
        dot = Dot(color=YELLOW)
        path.set_points_as_corners([dot.get_center(), dot.get_center()])

        def update_path(p):
            previous = p.copy()
            previous.add_points_as_corners([dot.get_center()])
            p.become(previous)

        path.add_updater(update_path)
        self.play(Write(title), FadeIn(dot), run_time=0.8)
        self.add(path)
        self.play(Rotating(dot, angle=PI, about_point=RIGHT, run_time=2))
        self.play(dot.animate.shift(UP), run_time=0.8)
        self.play(dot.animate.shift(LEFT * 2), run_time=0.8)
        path.remove_updater(update_path)
        self.wait(0.5)
