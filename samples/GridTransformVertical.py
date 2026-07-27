from manim import *
import numpy as np

# Configure for horizontal format (16:9) - 1920x1080
config.pixel_width = 1920
config.pixel_height = 1080
config.frame_width = 16.0
config.frame_height = 9.0

class GridTransformVertical(Scene):
    def construct(self):
        # Create a colorful grid
        grid = NumberPlane(
            x_range=[-8, 8, 1],
            y_range=[-5, 5, 1],
            background_line_style={
                "stroke_color": BLUE,
                "stroke_width": 2,
                "stroke_opacity": 0.6
            }
        )
        
        # Color the axes
        grid.x_axis.set_color("#00D9FF")
        grid.y_axis.set_color("#FF006E")
        
        # Create the grid with animation
        self.play(
            Create(grid, run_time=3, lag_ratio=0.1),
        )
        self.wait(1)
        
        # Apply non-linear transformation
        grid.prepare_for_nonlinear_transform()
        self.play(
            grid.animate.apply_function(
                lambda p: p + np.array([
                    np.sin(p[1]),
                    np.sin(p[0]),
                    0,
                ])
            ),
            run_time=4,
        )
        self.wait(2)
        
        # Apply another cool transformation
        grid.prepare_for_nonlinear_transform()
        self.play(
            grid.animate.apply_function(
                lambda p: p + np.array([
                    0.3 * np.sin(2 * p[1]),
                    0.3 * np.cos(2 * p[0]),
                    0,
                ])
            ),
            run_time=4,
        )
        self.wait(2)
        
        # Fade out
        self.play(FadeOut(grid))
        self.wait()


