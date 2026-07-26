from manim import *


class SineCurve(Scene):
    """Unit circle + always_redraw → draw a sine wave in real time."""

    def construct(self):
        self.show_axis()
        self.show_circle()
        self.move_dot_and_draw_curve()
        self.wait(0.5)

    def show_axis(self):
        x_axis = Line(np.array([-6, 0, 0]), np.array([6, 0, 0]))
        y_axis = Line(np.array([-4, -2, 0]), np.array([-4, 2, 0]))
        self.play(Create(x_axis), Create(y_axis), run_time=0.8)

        for i, label in enumerate(["π", "2π", "3π", "4π"]):
            t = Text(label, font_size=28)
            t.next_to(np.array([-1 + 2 * i, 0, 0]), DOWN, buff=0.2)
            self.add(t)

        self.origin_point = np.array([-4, 0, 0])
        self.curve_start = np.array([-3, 0, 0])

    def show_circle(self):
        circle = Circle(radius=1).move_to(self.origin_point)
        self.play(Create(circle), run_time=0.8)
        self.circle = circle

    def move_dot_and_draw_curve(self):
        orbit = self.circle
        origin_point = self.origin_point
        dot = Dot(radius=0.08, color=RED).move_to(orbit.point_from_proportion(0))
        self.t_offset = 0
        rate = 0.25

        def go_around_circle(mob, dt):
            self.t_offset += dt * rate
            mob.move_to(orbit.point_from_proportion(self.t_offset % 1))

        def get_line_to_circle():
            return Line(origin_point, dot.get_center(), color=TEAL)

        def get_line_to_curve():
            x = self.curve_start[0] + self.t_offset * 4
            y = dot.get_center()[1]
            return Line(dot.get_center(), np.array([x, y, 0]), color=ORANGE, stroke_width=2)

        self.curve = VGroup(Line(self.curve_start, self.curve_start))

        def get_curve():
            last_line = self.curve[-1]
            x = self.curve_start[0] + self.t_offset * 4
            y = dot.get_center()[1]
            self.curve.add(Line(last_line.get_end(), np.array([x, y, 0]), color=PURPLE))
            return self.curve

        dot.add_updater(go_around_circle)
        self.add(
            dot,
            always_redraw(get_line_to_circle),
            always_redraw(get_line_to_curve),
            always_redraw(get_curve),
        )
        self.wait(6.0)
        dot.remove_updater(go_around_circle)
