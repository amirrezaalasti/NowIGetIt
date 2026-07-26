from manim import *


class RotationUpdater(Scene):
    """dt-based updater for continuous rotation (Manim docs)."""

    def construct(self):
        title = Text("Updater rotation", font_size=36).to_edge(UP, buff=0.3)
        ref = Line(ORIGIN, LEFT * 2, color=GREY_B)
        moving = Line(ORIGIN, LEFT * 2, color=YELLOW)
        group = VGroup(ref, moving).move_to(ORIGIN + DOWN * 0.2)

        def spin(mobj, dt):
            mobj.rotate(dt, about_point=group.get_center())

        self.play(Write(title), Create(ref), Create(moving), run_time=0.8)
        moving.add_updater(spin)
        self.wait(2.5)
        moving.remove_updater(spin)
        self.wait(0.5)
