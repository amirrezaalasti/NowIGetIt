from manim import *


class DynamicPolygon(Scene):
    """always_redraw area under xy=k — optimization / calculus (Manim docs)."""

    def get_rectangle_corners(self, bottom_left, top_right):
        return [
            (top_right[0], top_right[1]),
            (bottom_left[0], top_right[1]),
            (bottom_left[0], bottom_left[1]),
            (top_right[0], bottom_left[1]),
        ]

    def construct(self):
        title = Text("xy = k area", font_size=36).to_edge(UP, buff=0.3)
        ax = Axes(
            x_range=[0, 10],
            y_range=[0, 10],
            x_length=6,
            y_length=5.2,
            axis_config={"include_tip": False},
        ).move_to(ORIGIN + DOWN * 0.2)

        t = ValueTracker(5)
        k = 25
        graph = ax.plot(
            lambda x: k / x,
            color=RED,
            x_range=[k / 10, 10.0, 0.01],
            use_smoothing=False,
        )

        def get_rectangle():
            polygon = Polygon(
                *[
                    ax.c2p(*i)
                    for i in self.get_rectangle_corners(
                        (0, 0), (t.get_value(), k / t.get_value())
                    )
                ]
            )
            polygon.set_fill(TEAL, opacity=0.5)
            polygon.set_stroke(PURPLE, width=1)
            return polygon

        polygon = always_redraw(get_rectangle)
        dot = Dot(color=YELLOW)
        dot.add_updater(lambda m: m.move_to(ax.c2p(t.get_value(), k / t.get_value())))
        dot.set_z_index(10)

        self.play(Write(title), Create(ax), Create(graph), FadeIn(dot), run_time=1.4)
        self.play(Create(polygon), run_time=0.8)
        self.play(t.animate.set_value(10), run_time=1.5)
        self.play(t.animate.set_value(k / 10), run_time=1.5)
        self.play(t.animate.set_value(5), run_time=1.0)
        self.wait(0.5)
