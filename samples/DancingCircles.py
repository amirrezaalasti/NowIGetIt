from manim import *


class CircleSquareScene(Scene):
    """Formation change + group Rotate — particle / ensemble motion."""

    def construct(self):
        title = Text("Formation dance", font_size=36).to_edge(UP, buff=0.3)
        self.play(Write(title), run_time=0.5)

        # Create 5 circles of different colors
        circle1 = Circle(radius=0.7, color=RED, fill_opacity=0.7)
        circle2 = Circle(radius=0.7, color=BLUE, fill_opacity=0.7)
        circle3 = Circle(radius=0.7, color=GREEN, fill_opacity=0.7)
        circle4 = Circle(radius=0.7, color=YELLOW, fill_opacity=0.7)
        circle5 = Circle(radius=0.7, color=PURPLE, fill_opacity=0.7)

        circles = [circle1, circle2, circle3, circle4, circle5]
        for i, circle in enumerate(circles):
            circle.move_to(LEFT * 3.2 + RIGHT * i * 1.6)
        
        # Create circles one by one
        for circle in circles:
            self.play(Create(circle), run_time=0.5)
        
        # Make them all scale up together
        self.play(
            *[circle.animate.scale(1.3) for circle in circles],
            run_time=1.5
        )
        
        # Move them into a circle formation
        positions = [
            UP * 2,
            UP * 0.618 + RIGHT * 1.902,
            DOWN * 1.618 + RIGHT * 1.176,
            DOWN * 1.618 + LEFT * 1.176,
            UP * 0.618 + LEFT * 1.902
        ]
        
        self.play(
            *[circles[i].animate.move_to(positions[i]) for i in range(5)],
            run_time=2
        )
        
        # Rotate them around the center
        self.play(
            *[Rotate(circle, 2*PI, about_point=ORIGIN) for circle in circles],
            run_time=3
        )
        
        # Scale back and return to original positions
        self.play(
            *[circle.animate.scale(1/1.3) for circle in circles],
            run_time=1
        )
        
        self.play(
            *[circles[i].animate.move_to(LEFT * 4 + RIGHT * i * 2) for i in range(5)],
            run_time=2
        )
        
        self.wait(0.5)