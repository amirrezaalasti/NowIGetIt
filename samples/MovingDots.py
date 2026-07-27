from manim import *


class MovingDots(Scene):
    """Two ValueTrackers driving linked dots + line (Manim docs)."""

    def construct(self):
        title = Text("Linked trackers", font_size=36).to_edge(UP, buff=0.3)
        d1, d2 = Dot(color=BLUE), Dot(color=GREEN)
        VGroup(d1, d2).arrange(RIGHT, buff=1.2).move_to(ORIGIN + DOWN * 0.2)
        line = Line(d1.get_center(), d2.get_center(), color=RED)

        x = ValueTracker(d1.get_x())
        y = ValueTracker(d2.get_y())
        d1.add_updater(lambda z: z.set_x(x.get_value()))
        d2.add_updater(lambda z: z.set_y(y.get_value()))
        line.add_updater(
            lambda z: z.become(Line(d1.get_center(), d2.get_center(), color=RED))
        )

        self.play(Write(title), FadeIn(d1), FadeIn(d2), Create(line), run_time=1.0)
        self.play(x.animate.set_value(3), run_time=1.5)
        self.play(y.animate.set_value(2), run_time=1.5)
        self.wait(0.5)
