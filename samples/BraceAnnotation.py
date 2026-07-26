from manim import *


class BraceAnnotation(Scene):
    """Brace labels on a segment (Manim docs — Text only, no get_tex)."""

    def construct(self):
        title = Text("Brace annotation", font_size=36).to_edge(UP, buff=0.3)
        dot_a = Dot([-2.5, -0.5, 0], color=YELLOW)
        dot_b = Dot([2.5, 1.0, 0], color=YELLOW)
        line = Line(dot_a.get_center(), dot_b.get_center(), color=ORANGE)
        brace = Brace(line, direction=DOWN, color=TEAL)
        label = brace.get_text("distance")
        label.set_color(WHITE)

        self.play(Write(title), FadeIn(dot_a), FadeIn(dot_b), Create(line), run_time=1.0)
        self.play(GrowFromCenter(brace), FadeIn(label), run_time=0.8)
        self.wait(0.5)
