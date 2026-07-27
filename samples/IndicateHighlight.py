from manim import *


class IndicateHighlight(Scene):
    """Indicate + Circumscribe for attention (Manim docs indication patterns)."""

    def construct(self):
        title = Text("Call attention", font_size=36).to_edge(UP, buff=0.3)
        boxes = VGroup(
            *[
                RoundedRectangle(width=2.0, height=1.2, corner_radius=0.12, color=TEAL)
                for _ in range(3)
            ]
        )
        labels = VGroup(
            Text("A", font_size=32),
            Text("B", font_size=32),
            Text("C", font_size=32),
        )
        for box, lab in zip(boxes, labels):
            lab.move_to(box.get_center())
        row = VGroup(*[VGroup(b, l) for b, l in zip(boxes, labels)])
        row.arrange(RIGHT, buff=0.55).move_to(ORIGIN + DOWN * 0.1)

        self.play(Write(title), LaggedStart(*[FadeIn(g) for g in row], lag_ratio=0.2))
        self.play(Indicate(row[1], color=YELLOW), run_time=1.0)
        self.play(Circumscribe(row[2], color=ORANGE), run_time=1.2)
        self.wait(0.5)
