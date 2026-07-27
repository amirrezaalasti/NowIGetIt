from manim import *


class GridTransform(Scene):
    """Nonlinear NumberPlane warp — lattice / coordinate morph (from samples)."""

    def construct(self):
        title = Text("Grid transform", font_size=36).to_edge(UP, buff=0.3)
        grid = NumberPlane(
            x_range=[-6, 6, 1],
            y_range=[-3.5, 3.5, 1],
            x_length=12,
            y_length=6.2,
            background_line_style={
                "stroke_color": BLUE,
                "stroke_width": 2,
                "stroke_opacity": 0.55,
            },
        ).move_to(ORIGIN + DOWN * 0.15)
        grid.x_axis.set_color("#00D9FF")
        grid.y_axis.set_color("#FF006E")

        self.play(Write(title), Create(grid, lag_ratio=0.05), run_time=1.8)
        grid.prepare_for_nonlinear_transform()
        self.play(
            grid.animate.apply_function(
                lambda p: p + np.array([np.sin(p[1]), np.sin(p[0]), 0])
            ),
            run_time=2.5,
        )
        self.wait(0.5)
