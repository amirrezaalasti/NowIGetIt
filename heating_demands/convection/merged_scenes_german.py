import os
import numpy as np
import math
from manim import *


class Scene1(Scene):
    def construct(self):
        # Set dark architectural background
        self.camera.background_color = "#0f1115"
        Text.set_default(font="Serif")

        # --- TITLE ---
        title = Text("Das Gebäude & Konvektion", font_size=32, color=WHITE)
        title.to_edge(UP, buff=0.4)

        self.play(Write(title), run_time=1.0)

        # --- ARCHITECTURAL CROSS-SECTION ---
        floor = Line([-3.0, -2.0, 0], [1.0, -2.0, 0], color=GREY_A, stroke_width=4)
        left_wall = Line([-3.0, -2.0, 0], [-3.0, 1.1, 0], color=GREY_A, stroke_width=4)
        roof_left = Line([-3.0, 1.1, 0], [-1.0, 2.3, 0], color=GREY_A, stroke_width=4)
        roof_right = Line([-1.0, 2.3, 0], [1.0, 1.1, 0], color=GREY_A, stroke_width=4)
        right_wall_bot = Line(
            [1.0, -2.0, 0], [1.0, -1.3, 0], color=GREY_A, stroke_width=4
        )
        right_wall_mid = Line(
            [1.0, -0.3, 0], [1.0, 0.3, 0], color=GREY_A, stroke_width=4
        )

        # Window gap indicators
        gap_bottom = Line(
            [1.0, -1.3, 0], [1.0, -0.3, 0], color=BLUE, stroke_width=2
        ).set_opacity(0.4)
        gap_top = Line(
            [1.0, 0.3, 0], [1.0, 1.1, 0], color=ORANGE, stroke_width=2
        ).set_opacity(0.4)

        house = VGroup(
            floor,
            left_wall,
            roof_left,
            roof_right,
            right_wall_bot,
            right_wall_mid,
            gap_bottom,
            gap_top,
        )

        # Zone Labels
        txt_innen = Text("Innen", font_size=20, color=ORANGE)
        txt_warm = Text("Warm", font_size=16, color=ORANGE)
        label_inside = (
            VGroup(txt_innen, txt_warm)
            .arrange(DOWN, buff=0.15)
            .move_to([-1.2, -0.5, 0])
        )

        txt_aussen = Text("Außen", font_size=20, color=BLUE_B)
        txt_kalt = Text("Kalt", font_size=16, color=BLUE_B)
        label_outside = (
            VGroup(txt_aussen, txt_kalt)
            .arrange(DOWN, buff=0.15)
            .move_to([2.6, -0.5, 0])
        )

        self.play(Create(house), run_time=1.5)
        self.play(
            FadeIn(label_inside),
            FadeIn(label_outside),
            run_time=1.0,
        )

        # --- FLUID CONVECTION PARTICLES ---
        np.random.seed(42)

        # Spawn 70 orange dots inside
        orange_dots = VGroup(
            *[
                Dot(
                    point=[
                        np.random.uniform(-2.7, 0.5),
                        np.random.uniform(-1.7, 0.7),
                        0,
                    ],
                    radius=0.04,
                    color=ORANGE,
                )
                for _ in range(70)
            ]
        )

        # Spawn 70 blue dots outside
        blue_dots = VGroup(
            *[
                Dot(
                    point=[
                        np.random.uniform(1.3, 3.3),
                        np.random.uniform(-2.0, 0.2),
                        0,
                    ],
                    radius=0.04,
                    color=BLUE_B,
                )
                for _ in range(70)
            ]
        )

        self.play(FadeIn(orange_dots), FadeIn(blue_dots), run_time=1.0)

        # Updaters for fluid motion simulation
        def update_orange_particles(group, dt):
            for dot in group:
                pos = dot.get_center()
                if pos[0] < 1.0:
                    dx = 0.45 * dt
                    dy = (0.7 - pos[1]) * 0.4 * dt + 0.15 * dt
                    pos += np.array([dx, dy, 0])
                else:
                    pos += np.array([0.5 * dt, 0.8 * dt, 0])
                    if pos[1] > 2.4 or pos[0] > 3.8:
                        pos[0] = np.random.uniform(-2.7, -0.5)
                        pos[1] = np.random.uniform(-1.7, -0.5)
                dot.move_to(pos)

        def update_blue_particles(group, dt):
            for dot in group:
                pos = dot.get_center()
                if pos[0] > 1.0:
                    dx = -0.5 * dt
                    dy = (-0.8 - pos[1]) * 0.4 * dt
                    pos += np.array([dx, dy, 0])
                else:
                    pos += np.array([-0.5 * dt, -0.3 * dt, 0])
                    if pos[0] < -2.7 or pos[1] < -1.8:
                        pos[0] = np.random.uniform(1.5, 3.5)
                        pos[1] = np.random.uniform(-1.8, 0.0)
                dot.move_to(pos)

        orange_dots.add_updater(update_orange_particles)
        blue_dots.add_updater(update_blue_particles)

        # Continuous fluid motion display throughout the entire scene
        self.wait(7.0)

        orange_dots.remove_updater(update_orange_particles)
        blue_dots.remove_updater(update_blue_particles)


class InteriorBuildingVolume(Scene):
    def construct(self):
        # Set dark architectural background
        self.camera.background_color = "#0f1115"
        Text.set_default(font="Serif")

        # House vertices defining the interior space
        v_bottom_left = np.array([-2.5, -2.0, 0])
        v_bottom_right = np.array([2.5, -2.0, 0])
        v_top_right = np.array([2.5, 0.5, 0])
        v_roof_peak = np.array([0.0, 2.2, 0])
        v_top_left = np.array([-2.5, 0.5, 0])

        interior_points = [
            v_bottom_left,
            v_bottom_right,
            v_top_right,
            v_roof_peak,
            v_top_left,
        ]

        # Architectural house outline and ground line
        house_outline = Polygon(*interior_points, color="#8A9BA8", stroke_width=3)

        ground = Line(
            start=[-3.8, -2.0, 0], end=[3.8, -2.0, 0], color="#5A6577", stroke_width=2
        )

        # Window outline
        # window = Rectangle(width=0.7, height=1.0, color="#8A9BA8", stroke_width=2)
        # window.move_to([1.8, -0.8, 0])

        # Scene Title aligned with visual lesson styling
        title = Text("Gebäude-Innenvolumen V (DIN EN 12831)", font_size=28, color=WHITE)
        title.to_edge(UP, buff=0.5)

        # External Blue Dots (outside air)
        blue_positions = [
            [-3.2, 1.5, 0],
            [-3.5, -0.5, 0],
            [-3.0, -1.5, 0],
            [3.2, 1.8, 0],
            [3.6, 0.2, 0],
            [3.3, -1.2, 0],
            [-1.5, 2.8, 0],
            [1.5, 2.8, 0],
            [0.0, 3.1, 0],
        ]
        blue_dots = VGroup(
            *[Dot(point=pos, color="#4C9EFF", radius=0.08) for pos in blue_positions]
        )

        # Internal Orange Dots (warm indoor air)
        orange_positions = [
            [-1.8, -1.3, 0],
            [-0.6, -1.4, 0],
            [0.7, -1.3, 0],
            [1.8, -1.4, 0],
            [-1.6, -0.3, 0],
            [-0.5, -0.2, 0],
            [0.6, -0.3, 0],
            [1.7, -0.2, 0],
            [-1.0, 0.7, 0],
            [0.0, 1.1, 0],
            [1.0, 0.7, 0],
            [0.0, -0.6, 0],
        ]
        orange_dots = VGroup(
            *[Dot(point=pos, color="#FF9F1C", radius=0.08) for pos in orange_positions]
        )

        # Initial display setup
        self.add(ground, house_outline, blue_dots, orange_dots)
        self.play(Write(title), run_time=1.0)
        self.wait(0.5)

        # Animation Beat 1 & 2: Fade out external blue dots, dim inside orange dots to 30% opacity
        self.play(
            FadeOut(blue_dots, run_time=1.2),
            orange_dots.animate(run_time=1.2).set_opacity(0.3),
        )

        # Animation Beat 3: Translucent orange polygon filling the interior volume
        interior_fill = Polygon(
            *interior_points, fill_color="#FF9F1C", fill_opacity=0.35, stroke_width=0
        )
        self.play(FadeIn(interior_fill, run_time=1.5))

        # Animation Beat 4: Orange variable 'V' and descriptive label in the middle of the house
        v_label = Text("V", font_size=56, color="#FF9F1C")
        v_subtext = Text("Nettovolumen (m³)", font_size=18, color="#FF9F1C")

        v_group = VGroup(v_label, v_subtext).arrange(DOWN, buff=0.1)
        v_group.move_to([0.0, -0.2, 0])

        self.play(
            Write(v_label, run_time=1.0),
            FadeIn(v_subtext, shift=UP * 0.15, run_time=1.0),
        )

        # Architectural dimension line indicator at bottom
        dim_line = Line(
            start=[-2.5, -2.3, 0], end=[2.5, -2.3, 0], color="#FF9F1C", stroke_width=1.5
        )
        dim_tick_l = Line(
            start=[-2.5, -2.4, 0],
            end=[-2.5, -2.2, 0],
            color="#FF9F1C",
            stroke_width=1.5,
        )
        dim_tick_r = Line(
            start=[2.5, -2.4, 0], end=[2.5, -2.2, 0], color="#FF9F1C", stroke_width=1.5
        )
        dimension_group = VGroup(dim_line, dim_tick_l, dim_tick_r)

        self.play(Create(dimension_group, run_time=1.0))

        # Final hold
        self.wait(2)


class Scene3(Scene):
    def construct(self):
        # Set scene background
        self.camera.background_color = "#0f1115"
        Text.set_default(font="Serif")

        # Color palette definition
        COLOR_V = ORANGE
        COLOR_N = WHITE
        COLOR_COLD = "#00BFFF"

        # 1. Setup House Geometry
        house_points = [
            np.array([-2.0, -1.8, 0]),
            np.array([2.0, -1.8, 0]),
            np.array([2.0, 0.4, 0]),
            np.array([0.0, 1.8, 0]),
            np.array([-2.0, 0.4, 0]),
        ]

        house_shift = LEFT * 2.6 + DOWN * 0.2

        house_fill = Polygon(
            *house_points, fill_color=COLOR_V, fill_opacity=0.3, stroke_width=0
        )
        house_outline = Polygon(
            *house_points, color=WHITE, stroke_width=3, fill_opacity=0
        )
        house_fill.shift(house_shift)
        house_outline.shift(house_shift)

        # Label V inside house
        v_label = Text("V", font_size=52, color=COLOR_V).move_to(
            house_outline.get_center()
        )

        # Beat 1: Draw house interior volume and label 'V'
        self.play(
            Create(house_outline), FadeIn(house_fill), Write(v_label), run_time=2.0
        )
        self.wait(0.8)

        # 2. Setup Clock Icon and Label 'n'
        clock_center = RIGHT * 2.4 + DOWN * 0.4
        clock_radius = 0.85
        clock_circle = Circle(radius=clock_radius, color=WHITE, stroke_width=3).move_to(
            clock_center
        )

        ticks = VGroup()
        for i in range(12):
            angle = i * (2 * PI / 12)
            start = clock_center + 0.70 * clock_radius * np.array(
                [np.sin(angle), np.cos(angle), 0]
            )
            end = clock_center + 0.92 * clock_radius * np.array(
                [np.sin(angle), np.cos(angle), 0]
            )
            ticks.add(Line(start, end, color=WHITE, stroke_width=2))

        hand = Line(clock_center, clock_center + UP * 0.6, color=WHITE, stroke_width=3)
        clock_icon = VGroup(clock_circle, ticks, hand)

        n_symbol = Text("n", font_size=52, color=COLOR_N).next_to(
            clock_icon, UP, buff=0.4
        )
        line1 = Text("Luftwechselrate n (1/h)", font_size=16, color=WHITE)
        line2 = Text("(DIN 1946-6)", font_size=14, color=WHITE)
        n_subtext = (
            VGroup(line1, line2)
            .arrange(DOWN, buff=0.08)
            .next_to(clock_icon, DOWN, buff=0.4)
        )

        # Beat 2: Display white variable 'n' and minimalist clock
        self.play(
            Create(clock_icon),
            Write(n_symbol),
            FadeIn(n_subtext, shift=UP * 0.2),
            run_time=2.0,
        )
        self.wait(0.5)

        # Beat 3: Clock minute hand sweeps 360 deg while interior transitions from warm orange to cold blue
        rate_caption = Text(
            "1 Luftwechsel = Vollständiges Volumen ausgetauscht",
            font_size=20,
            color=COLOR_COLD,
        ).to_edge(DOWN, buff=0.6)

        self.play(
            Rotate(hand, angle=-2 * PI, about_point=clock_center, rate_func=linear),
            house_fill.animate.set_fill(COLOR_COLD, opacity=0.2),
            v_label.animate.set_color(COLOR_V),
            FadeIn(rate_caption),
            run_time=3.5,
        )
        self.wait(1.0)

        # 3. Form Equation 'V * n' at top center
        target_v = Text("V", font_size=48, color=COLOR_V)
        target_times = Text("×", font_size=40, color=WHITE)
        target_n = Text("n", font_size=48, color=COLOR_N)

        equation_group = (
            VGroup(target_v, target_times, target_n)
            .arrange(RIGHT, buff=0.25)
            .move_to(UP * 3.1)
        )

        v_copy = v_label.copy()
        n_copy = n_symbol.copy()

        # Beat 4: Transform 'V' and 'n' into equation at the top
        self.play(
            FadeOut(n_subtext),
            FadeOut(rate_caption),
            Transform(v_copy, target_v),
            Transform(n_copy, target_n),
            FadeIn(target_times),
            run_time=2.2,
        )

        # Final hold
        self.wait(2.0)


class Scene4(Scene):
    def construct(self):
        # Set background color
        self.camera.background_color = "#0f1115"
        Text.set_default(font="Serif")

        # Top Equation Initial State: V * n
        eq_v = Text("V", color=ORANGE, font_size=40)
        eq_times1 = Text(" × ", color=WHITE, font_size=40)
        eq_n = Text("n", color=WHITE, font_size=40)

        top_eq_initial = VGroup(eq_v, eq_times1, eq_n).arrange(RIGHT, buff=0.1)
        top_eq_initial.to_edge(UP, buff=0.4)

        self.add(top_eq_initial)

        # Build 1m³ Isometric Cube
        scale_fac = 1.15
        c_center = UP * 0.2

        # Isometric vertices relative to center
        top_pt = c_center + UP * 1.0 * scale_fac
        tr_pt = c_center + (RIGHT * 0.866 + UP * 0.5) * scale_fac
        br_pt = c_center + (RIGHT * 0.866 + DOWN * 0.5) * scale_fac
        bot_pt = c_center + DOWN * 1.0 * scale_fac
        bl_pt = c_center + (LEFT * 0.866 + DOWN * 0.5) * scale_fac
        tl_pt = c_center + (LEFT * 0.866 + UP * 0.5) * scale_fac

        # Initial translucent blue faces
        face_top = Polygon(
            c_center,
            tl_pt,
            top_pt,
            tr_pt,
            fill_color=BLUE,
            fill_opacity=0.35,
            stroke_color=BLUE_A,
            stroke_width=2,
        )
        face_left = Polygon(
            c_center,
            tl_pt,
            bl_pt,
            bot_pt,
            fill_color="#1565C0",
            fill_opacity=0.45,
            stroke_color=BLUE_A,
            stroke_width=2,
        )
        face_right = Polygon(
            c_center,
            tr_pt,
            br_pt,
            bot_pt,
            fill_color="#0D47A1",
            fill_opacity=0.55,
            stroke_color=BLUE_A,
            stroke_width=2,
        )

        cube = VGroup(face_top, face_left, face_right)

        # Position '1 m³' label inside the top face of the cube
        cube_label = Text("1 m³", font_size=28, color=WHITE).move_to(
            face_top.get_center()
        )

        # Animate Cube Appearance
        self.play(FadeIn(cube, shift=UP * 0.3), Write(cube_label), run_time=2.0)
        self.wait(0.5)

        # Heating Coil (Sine wave below the cube)
        coil_y = -2.1
        coil = ParametricFunction(
            lambda t: np.array([t, 0.1 * np.sin(10 * t) + coil_y, 0]),
            t_range=[-1.1, 1.1],
            color=RED,
        ).set_stroke(width=4)

        coil_label = Text("Heizelement", font_size=15, color=RED_B).next_to(
            coil, DOWN, buff=0.15
        )

        self.play(Create(coil), FadeIn(coil_label), run_time=1.5)
        self.wait(0.5)

        # Heat Waves Animation
        heat_lines = VGroup()
        for x_off in [-0.7, -0.35, 0.0, 0.35, 0.7]:
            line = ParametricFunction(
                lambda t: np.array(
                    [x_off + 0.05 * np.sin(8 * t), t + coil_y + 0.15, 0]
                ),
                t_range=[0, 0.95],
                color=ORANGE,
            ).set_stroke(width=2.5, opacity=0.8)
            heat_lines.add(line)

        # Warm target faces for color transition
        face_top_warm = Polygon(
            c_center,
            tl_pt,
            top_pt,
            tr_pt,
            fill_color=ORANGE,
            fill_opacity=0.45,
            stroke_color=ORANGE,
            stroke_width=2,
        )
        face_left_warm = Polygon(
            c_center,
            tl_pt,
            bl_pt,
            bot_pt,
            fill_color="#E65100",
            fill_opacity=0.55,
            stroke_color=ORANGE,
            stroke_width=2,
        )
        face_right_warm = Polygon(
            c_center,
            tr_pt,
            br_pt,
            bot_pt,
            fill_color="#BF360C",
            fill_opacity=0.65,
            stroke_color=ORANGE,
            stroke_width=2,
        )

        self.play(
            Create(heat_lines),
            Transform(face_top, face_top_warm),
            Transform(face_left, face_left_warm),
            Transform(face_right, face_right_warm),
            run_time=2.5,
        )

        # Introduce c_Luft variable next to the cube (without arrow)
        c_air_tag = Text("c_Luft", color=GREEN, font_size=32)
        c_air_desc1 = Text("Spez. Wärmekapazität", color=GREEN_B, font_size=14)
        c_air_desc2 = Text("(0,34 Wh/(m³·K))", color=GREEN_B, font_size=14)
        c_air_group = VGroup(c_air_tag, c_air_desc1, c_air_desc2).arrange(
            DOWN, buff=0.08
        )
        c_air_group.next_to(cube, RIGHT, buff=0.5).shift(DOWN * 0.2)

        self.play(FadeIn(c_air_group, shift=RIGHT * 0.2), run_time=1.5)
        self.wait(1.0)

        # Update Equation at Top: V * n -> V * n * c_Luft
        eq_times2 = Text(" × ", color=WHITE, font_size=40)
        eq_c = Text("c_Luft", color=GREEN, font_size=36)

        top_eq_full = (
            VGroup(
                Text("V", color=ORANGE, font_size=40),
                Text(" × ", color=WHITE, font_size=40),
                Text("n", color=WHITE, font_size=40),
                eq_times2,
                eq_c,
            )
            .arrange(RIGHT, buff=0.1)
            .to_edge(UP, buff=0.4)
        )

        self.play(
            Transform(top_eq_initial, top_eq_full[:3]),
            FadeIn(top_eq_full[3:]),
            run_time=1.5,
        )

        # Final hold
        self.wait(2.0)


class Scene5(Scene):
    def construct(self):
        # Set dark background theme
        self.camera.background_color = "#0f1115"
        Text.set_default(font="Serif")

        # --- Scene Title ---
        title = Text("Lüftungswärmeverlust (DIN EN 12831-1)", font_size=32, color=WHITE)
        title.to_edge(UP, buff=0.5)
        self.add(title)

        # --- Initial State (carried from previous scene) ---
        top_v = Text("V", color=ORANGE, font_size=32)
        top_dot1 = Text(" · ", color=WHITE, font_size=32)
        top_n = Text("n", color=WHITE, font_size=32)
        top_dot2 = Text(" · ", color=WHITE, font_size=32)
        top_c = Text("c_Luft", color=GREEN, font_size=32)
        top_terms = VGroup(top_v, top_dot1, top_n, top_dot2, top_c).arrange(
            RIGHT, buff=0.1
        )
        top_terms.next_to(title, DOWN, buff=0.4)

        # 3D Isometric Volume & Lüftungsverlust airflow visualization
        scale_fac = 0.95
        c_center = DOWN * 0.9

        top_pt = c_center + UP * 1.0 * scale_fac
        tr_pt = c_center + (RIGHT * 0.866 + UP * 0.5) * scale_fac
        br_pt = c_center + (RIGHT * 0.866 + DOWN * 0.5) * scale_fac
        bot_pt = c_center + DOWN * 1.0 * scale_fac
        bl_pt = c_center + (LEFT * 0.866 + DOWN * 0.5) * scale_fac
        tl_pt = c_center + (LEFT * 0.866 + UP * 0.5) * scale_fac

        face_top = Polygon(
            c_center,
            tl_pt,
            top_pt,
            tr_pt,
            fill_color=ORANGE,
            fill_opacity=0.35,
            stroke_color=ORANGE,
            stroke_width=2,
        )
        face_left = Polygon(
            c_center,
            tl_pt,
            bl_pt,
            bot_pt,
            fill_color="#E65100",
            fill_opacity=0.45,
            stroke_color=ORANGE,
            stroke_width=2,
        )
        face_right = Polygon(
            c_center,
            tr_pt,
            br_pt,
            bot_pt,
            fill_color="#BF360C",
            fill_opacity=0.55,
            stroke_color=ORANGE,
            stroke_width=2,
        )

        cube = VGroup(face_top, face_left, face_right)
        cube_label = Text("1 m³", font_size=22, color=WHITE).move_to(
            face_top.get_center()
        )

        loss_label = Text("Lüftungsverlust", font_size=18, color="#FF9F43").next_to(
            cube, UP, buff=0.35
        )

        prev_visuals = VGroup(cube, cube_label, loss_label)

        self.add(top_terms, prev_visuals)
        self.wait(0.5)

        # --- Beat 1: Fade Unit Cube and Coil ---
        self.play(FadeOut(prev_visuals), run_time=1.0)

        # --- Beat 2: Display Yellow Vertical Bracket and Delta T ---
        t_inside = Text(
            "T_innen  (Innentemperatur)", color="#FF6B6B", font_size=18
        ).shift(UP * 0.3 + RIGHT * 1.2)
        t_outside = Text(
            "T_außen (Außentemperatur)", color="#4D96FF", font_size=18
        ).shift(DOWN * 1.5 + RIGHT * 1.2)

        dt_brace = BraceBetweenPoints(
            t_outside.get_left() + LEFT * 0.3,
            t_inside.get_left() + LEFT * 0.3,
            direction=LEFT,
            color=YELLOW,
        )
        dt_label = Text("ΔT", color=YELLOW, font_size=36).next_to(
            dt_brace, LEFT, buff=0.25
        )

        dt_sub = (
            VGroup(
                Text("Temperatur-", color=YELLOW, font_size=14),
                Text("differenz", color=YELLOW, font_size=14),
            )
            .arrange(DOWN, buff=0.05)
            .next_to(dt_label, DOWN, buff=0.15)
        )

        self.play(
            FadeIn(t_inside, shift=LEFT * 0.2),
            FadeIn(t_outside, shift=LEFT * 0.2),
            GrowFromCenter(dt_brace),
            Write(dt_label),
            FadeIn(dt_sub),
            run_time=2.0,
        )
        self.wait(1.0)

        # --- Beat 3: Morph Terms into Final Master Equation ---
        eq_phi = Text("Φ_V = ", color=WHITE, font_size=40)
        eq_v = Text("V", color=ORANGE, font_size=40)
        eq_dot1 = Text(" · ", color=WHITE, font_size=40)
        eq_n = Text("n", color=WHITE, font_size=40)
        eq_dot2 = Text(" · ", color=WHITE, font_size=40)
        eq_c = Text("c_Luft", color=GREEN, font_size=36)
        eq_dot3 = Text(" · ", color=WHITE, font_size=40)
        eq_dt = Text("ΔT", color=YELLOW, font_size=40)

        master_eq = (
            VGroup(eq_phi, eq_v, eq_dot1, eq_n, eq_dot2, eq_c, eq_dot3, eq_dt)
            .arrange(RIGHT, buff=0.1)
            .move_to(UP * 0.8)
        )

        self.play(
            FadeOut(t_inside),
            FadeOut(t_outside),
            FadeOut(dt_brace),
            FadeOut(dt_sub),
            FadeOut(title),
            ReplacementTransform(top_v, eq_v),
            ReplacementTransform(top_dot1, eq_dot1),
            ReplacementTransform(top_n, eq_n),
            ReplacementTransform(top_dot2, eq_dot2),
            ReplacementTransform(top_c, eq_c),
            ReplacementTransform(dt_label, eq_dt),
            Write(eq_phi),
            Write(eq_dot3),
            run_time=2.0,
        )

        # Frame surrounding the complete master equation
        eq_box = SurroundingRectangle(
            master_eq, color=WHITE, buff=0.25, corner_radius=0.15, stroke_width=2
        )
        self.play(Create(eq_box), run_time=1.0)
        self.wait(0.5)

        # --- Beat 4: Highlight Color Coding & Explanatory Labels ---
        card_v = VGroup(
            Text("V", color=ORANGE, font_size=20),
            Text("Gebäudevolumen", color=GREY_A, font_size=13),
            Text("(m³, DIN EN 12831)", color=GREY_A, font_size=11),
        ).arrange(DOWN, buff=0.08)

        card_n = VGroup(
            Text("n", color=WHITE, font_size=20),
            Text("Luftwechselrate", color=GREY_A, font_size=13),
            Text("(1/h, DIN 1946-6)", color=GREY_A, font_size=11),
        ).arrange(DOWN, buff=0.08)

        card_c = VGroup(
            Text("c_Luft", color=GREEN, font_size=18),
            Text("Spez. Wärmekapazität", color=GREY_A, font_size=13),
            Text("(0,34 Wh/(m³·K))", color=GREY_A, font_size=11),
        ).arrange(DOWN, buff=0.08)

        card_dt = VGroup(
            Text("ΔT", color=YELLOW, font_size=20),
            Text("Temperaturdifferenz", color=GREY_A, font_size=13),
            Text("(K oder °C)", color=GREY_A, font_size=11),
        ).arrange(DOWN, buff=0.08)

        cards = VGroup(card_v, card_n, card_c, card_dt).arrange(RIGHT, buff=0.35)
        cards.next_to(eq_box, DOWN, buff=0.8)

        highlights = [(eq_v, card_v), (eq_n, card_n), (eq_c, card_c), (eq_dt, card_dt)]

        for target_eq, card in highlights:
            self.play(
                target_eq.animate.scale(1.25),
                FadeIn(card, shift=UP * 0.15),
                run_time=0.5,
            )
            self.play(target_eq.animate.scale(1 / 1.25), run_time=0.3)

        self.wait(1.5)

        # --- Beat 5: Fade Scene to Black ---
        self.play(FadeOut(Group(*self.mobjects)), run_time=1.5)
        self.wait(2)


class Scene6_HeatRecoveryIntro(Scene):
    def construct(self):
        self.camera.background_color = "#0f1115"
        Text.set_default(font="Serif")

        # --- TITLE ---
        title = Text(
            "Wärmerückgewinnung (WRG) & Lüftungswärmeverlust",
            font_size=26,
            color=WHITE,
        )
        title.to_edge(UP, buff=0.4)
        self.play(Write(title), run_time=1.0)

        # --- STEP 1: INITIAL STANDARD FORMULA (WITHOUT WRG) ---
        eq_phi1 = Text("Φ_V  =", color=RED_B, font_size=26)
        eq_v1 = Text("V", color=ORANGE, font_size=26)
        eq_dot11 = Text(" · ", color=WHITE, font_size=26)
        eq_n1 = Text("n", color=WHITE, font_size=26)
        eq_dot12 = Text(" · ", color=WHITE, font_size=26)
        eq_c1 = Text("c_Luft", color=GREEN_B, font_size=26)
        eq_dot13 = Text(" · ", color=WHITE, font_size=26)
        eq_dt1 = Text("ΔT", color=YELLOW, font_size=26)

        formula_old = (
            VGroup(eq_phi1, eq_v1, eq_dot11, eq_n1, eq_dot12, eq_c1, eq_dot13, eq_dt1)
            .arrange(RIGHT, buff=0.08)
            .next_to(title, DOWN, buff=0.4)
        )

        old_label = Text(
            "Formel ohne Wärmerückgewinnung (η = 0%)", font_size=14, color=GREY_A
        ).next_to(formula_old, DOWN, buff=0.15)

        self.play(Write(formula_old), FadeIn(old_label), run_time=1.5)
        self.wait(1.0)

        # --- STEP 2: TRANSFORM TO FORMULA WITH HEAT RECOVERY FACTOR (1 - η_WRG) ---
        eq_phi2 = Text("Φ_V  =", color=RED_B, font_size=26)
        eq_v2 = Text("V", color=ORANGE, font_size=26)
        eq_dot21 = Text(" · ", color=WHITE, font_size=26)
        eq_n2 = Text("n", color=WHITE, font_size=26)
        eq_dot22 = Text(" · ", color=WHITE, font_size=26)
        eq_eta2 = Text("(1 - η_WRG)", color=GREEN, font_size=26)
        eq_dot23 = Text(" · ", color=WHITE, font_size=26)
        eq_c2 = Text("c_Luft", color=GREEN_B, font_size=26)
        eq_dot24 = Text(" · ", color=WHITE, font_size=26)
        eq_dt2 = Text("ΔT", color=YELLOW, font_size=26)

        formula_new = (
            VGroup(
                eq_phi2,
                eq_v2,
                eq_dot21,
                eq_n2,
                eq_dot22,
                eq_eta2,
                eq_dot23,
                eq_c2,
                eq_dot24,
                eq_dt2,
            )
            .arrange(RIGHT, buff=0.08)
            .next_to(title, DOWN, buff=0.4)
        )

        box_new = SurroundingRectangle(
            formula_new, color="#FFFF", buff=0.15, corner_radius=0.1
        )
        new_label = Text(
            "Reduzierte Heizlast durch Wärmerückgewinnungsgrad η_WRG",
            font_size=14,
            color=GREEN,
        ).next_to(box_new, DOWN, buff=0.15)

        self.play(
            FadeOut(old_label),
            TransformMatchingShapes(formula_old, formula_new),
            Create(box_new),
            FadeIn(new_label),
            run_time=2.0,
        )
        self.wait(1.0)

        # --- STEP 3: NUMERICAL EXAMPLE & COMPARISON BARS ---
        # Bar 1: Without WRG (100% loss)
        bar_label1 = Text("Ohne WRG (η = 0%)", font_size=14, color=RED_B)
        bar1 = RoundedRectangle(
            width=4.0,
            height=0.35,
            corner_radius=0.05,
            color=RED,
            fill_color=RED,
            fill_opacity=0.6,
        )
        bar_text1 = Text("100% Lüftungsverlust", font_size=12, color=WHITE).move_to(
            bar1
        )
        bar_group1 = VGroup(bar_label1, VGroup(bar1, bar_text1)).arrange(
            RIGHT, buff=0.3
        )

        # Bar 2: With WRG (η = 80% -> 20% loss remaining)
        bar_label2 = Text("Mit WRG (η = 80%)", font_size=14, color=GREEN)
        bar2_saved = RoundedRectangle(
            width=3.2,
            height=0.35,
            corner_radius=0.05,
            color=GREEN,
            fill_color=GREEN,
            fill_opacity=0.6,
        )
        bar_text2_saved = Text("80% Eingespart", font_size=12, color=WHITE).move_to(
            bar2_saved
        )
        bar2_loss = RoundedRectangle(
            width=0.8,
            height=0.35,
            corner_radius=0.05,
            color=RED,
            fill_color=RED,
            fill_opacity=0.6,
        ).next_to(bar2_saved, RIGHT, buff=0.0)
        bar_text2_loss = Text("20%", font_size=11, color=WHITE).move_to(bar2_loss)
        bar_group2 = VGroup(
            bar_label2, VGroup(bar2_saved, bar_text2_saved, bar2_loss, bar_text2_loss)
        ).arrange(RIGHT, buff=0.35)

        comparison_visual = (
            VGroup(bar_group1, bar_group2)
            .arrange(DOWN, aligned_edge=LEFT, buff=0.3)
            .shift(DOWN * 0.7)
        )

        self.play(FadeIn(comparison_visual, shift=UP * 0.2), run_time=1.5)
        self.wait(1.5)

        # --- STEP 4: NORMS & EXPLANATION CARDS ---
        self.play(FadeOut(comparison_visual), FadeOut(new_label), run_time=1.0)

        card_eta = VGroup(
            Text("η_WRG", color=GREEN, font_size=20),
            Text("Wärmerückgewinnungsgrad", color=WHITE, font_size=14),
            Text("Typisch: 0,70 bis 0,90 (70% bis 90%)", color=GREY_A, font_size=11),
            Text("DIN EN 13141-7 / DIN 1946-6", color="#00BFFF", font_size=11),
        ).arrange(DOWN, buff=0.08)

        card_phi = VGroup(
            Text("Φ_V", color=RED_B, font_size=20),
            Text("Reduzierte Lüftungsheizlast", color=WHITE, font_size=14),
            Text("Watt [W] oder Kilowatt [kW]", color=GREY_A, font_size=11),
            Text("DIN EN 12831-1", color="#00BFFF", font_size=11),
        ).arrange(DOWN, buff=0.08)

        cards = VGroup(card_eta, card_phi).arrange(RIGHT, buff=1.0).shift(DOWN * 0.8)

        self.play(
            eq_eta2.animate.scale(1.25),
            FadeIn(card_eta, shift=UP * 0.2),
            run_time=1.5,
        )
        self.play(eq_eta2.animate.scale(1 / 1.25), run_time=0.4)

        self.play(
            eq_phi2.animate.scale(1.25),
            FadeIn(card_phi, shift=UP * 0.2),
            run_time=1.5,
        )
        self.play(eq_phi2.animate.scale(1 / 1.25), run_time=0.4)

        self.wait(2.5)
        self.play(FadeOut(Group(*self.mobjects)), run_time=1.0)


class Scene7_VentilationSystemsComparison(Scene):
    def construct(self):
        self.camera.background_color = "#0f1115"
        Text.set_default(font="Serif")

        # --- TITLE ---
        title = Text(
            "Lüftungssysteme im Vergleich (DIN 1946-6)",
            font_size=28,
            color=WHITE,
        )
        title.to_edge(UP, buff=0.35)
        self.play(Write(title), run_time=1.0)

        # Three comparison cards layout
        card_w, card_h = 3.9, 4.4
        card_y = DOWN * 0.45

        # Helper function for identical base house wall schematic across all 3 options
        def create_base_house(center_pos):
            wall_top = Rectangle(
                width=2.4,
                height=0.35,
                color=GREY_A,
                fill_color="#333A42",
                fill_opacity=0.9,
                stroke_width=2,
            ).move_to(center_pos + UP * 0.85)
            wall_bot = Rectangle(
                width=2.4,
                height=0.35,
                color=GREY_A,
                fill_color="#333A42",
                fill_opacity=0.9,
                stroke_width=2,
            ).move_to(center_pos + DOWN * 0.85)

            lbl_outside = Text("Außen (Kalt)", font_size=10, color=BLUE_B).move_to(
                center_pos + LEFT * 0.7 + UP * 1.15
            )
            lbl_inside = Text("Innen (Warm)", font_size=10, color=ORANGE).move_to(
                center_pos + RIGHT * 0.7 + UP * 1.15
            )

            channel = Rectangle(
                width=2.4, height=1.35, color=GREY_C, fill_opacity=0.08, stroke_width=1
            ).move_to(center_pos)
            return VGroup(wall_top, wall_bot, channel, lbl_outside, lbl_inside)

        # ----------------------------------------------------
        # COLUMN 1: Fensterlüftung (Freie Lüftung, η = 0%)
        # ----------------------------------------------------
        rect1 = RoundedRectangle(
            width=card_w,
            height=card_h,
            corner_radius=0.15,
            color="#FF6B6B",
            fill_color="#1a1215",
            fill_opacity=0.85,
        )
        title1 = Text("1. Fensterlüftung", font_size=17, color="#FF6B6B")
        eta1 = Text("η_WRG = 0%  (Freie Lüftung)", font_size=12, color=RED_B)
        hdr1 = (
            VGroup(title1, eta1)
            .arrange(DOWN, buff=0.08)
            .move_to(rect1.get_top() + DOWN * 0.45)
        )

        center1 = rect1.get_center() + DOWN * 0.25
        base1 = create_base_house(center1)

        # Uncontrolled direct airflow: Warm air out (top), Cold air in (bottom)
        arr_warm_out = Arrow(
            center1 + RIGHT * 0.95 + UP * 0.3,
            center1 + LEFT * 0.95 + UP * 0.3,
            color=ORANGE,
            stroke_width=3,
            buff=0,
        )
        arr_cold_in = Arrow(
            center1 + LEFT * 0.95 + DOWN * 0.3,
            center1 + RIGHT * 0.95 + DOWN * 0.3,
            color=BLUE_B,
            stroke_width=3,
            buff=0,
        )
        lbl_out1 = Text("Warm Raus", font_size=10, color=ORANGE).next_to(
            arr_warm_out, UP, buff=0.04
        )
        lbl_in1 = Text("Kalt Rein", font_size=10, color=BLUE_B).next_to(
            arr_cold_in, DOWN, buff=0.04
        )

        lbl_loss1 = Text("100% Lüftungsverlust", font_size=13, color=RED).move_to(
            rect1.get_bottom() + UP * 0.35
        )

        col1 = VGroup(
            rect1, hdr1, base1, arr_warm_out, arr_cold_in, lbl_out1, lbl_in1, lbl_loss1
        ).move_to(LEFT * 4.1 + card_y)

        # ----------------------------------------------------
        # COLUMN 2: Zentrale WRG (η = 80 - 90%)
        # ----------------------------------------------------
        rect2 = RoundedRectangle(
            width=card_w,
            height=card_h,
            corner_radius=0.15,
            color="#4D96FF",
            fill_color="#101825",
            fill_opacity=0.85,
        )
        title2 = Text("2. Zentrale WRG", font_size=17, color="#4D96FF")
        eta2 = Text("η_WRG = 80 - 90% (Zentral)", font_size=12, color=GREEN_B)
        hdr2 = (
            VGroup(title2, eta2)
            .arrange(DOWN, buff=0.08)
            .move_to(rect2.get_top() + DOWN * 0.45)
        )

        center2 = rect2.get_center() + DOWN * 0.25
        base2 = create_base_house(center2)

        # Central Heat Exchanger Plate in channel
        hx = RoundedRectangle(
            width=0.9,
            height=0.9,
            corner_radius=0.08,
            color=WHITE,
            fill_color="#1A2638",
            fill_opacity=0.95,
            stroke_width=2,
        ).move_to(center2)
        lbl_hx = Text("WRG", font_size=10, color=YELLOW).move_to(hx)

        # Continuous heat exchange airflow: Exhaust warm -> cold out; Supply cold -> warm in!
        arr_ex_in = Arrow(
            center2 + RIGHT * 0.95 + UP * 0.25,
            center2 + RIGHT * 0.45 + UP * 0.25,
            color=ORANGE,
            stroke_width=3,
            buff=0,
        )
        arr_ex_out = Arrow(
            center2 + LEFT * 0.45 + UP * 0.25,
            center2 + LEFT * 0.95 + UP * 0.25,
            color=BLUE_B,
            stroke_width=3,
            buff=0,
        )

        arr_sup_in = Arrow(
            center2 + LEFT * 0.95 + DOWN * 0.25,
            center2 + LEFT * 0.45 + DOWN * 0.25,
            color=BLUE_B,
            stroke_width=3,
            buff=0,
        )
        arr_sup_out = Arrow(
            center2 + RIGHT * 0.45 + DOWN * 0.25,
            center2 + RIGHT * 0.95 + DOWN * 0.25,
            color=ORANGE,
            stroke_width=3,
            buff=0,
        )

        lbl_loss2 = Text("Bis zu 90% Ersparnis!", font_size=13, color=GREEN).move_to(
            rect2.get_bottom() + UP * 0.35
        )

        col2 = VGroup(
            rect2,
            hdr2,
            base2,
            hx,
            lbl_hx,
            arr_ex_in,
            arr_ex_out,
            arr_sup_in,
            arr_sup_out,
            lbl_loss2,
        ).move_to(card_y)

        # ----------------------------------------------------
        # COLUMN 3: Dezentrale WRG (Pendellüfter, η = 70 - 85%)
        # ----------------------------------------------------
        rect3 = RoundedRectangle(
            width=card_w,
            height=card_h,
            corner_radius=0.15,
            color="#6BCB77",
            fill_color="#102018",
            fill_opacity=0.85,
        )
        title3 = Text("3. Dezentrale WRG", font_size=17, color="#6BCB77")
        eta3 = Text("η_WRG = 70 - 85% (Pendel)", font_size=12, color=GREEN_B)
        hdr3 = (
            VGroup(title3, eta3)
            .arrange(DOWN, buff=0.08)
            .move_to(rect3.get_top() + DOWN * 0.45)
        )

        center3 = rect3.get_center() + DOWN * 0.25
        base3 = create_base_house(center3)

        # Ceramic Heat Accumulator Core in channel
        ceramic = RoundedRectangle(
            width=0.9,
            height=0.9,
            corner_radius=0.08,
            color=YELLOW,
            fill_color=ORANGE,
            fill_opacity=0.65,
            stroke_width=2,
        ).move_to(center3)
        lbl_ceramic = Text("Keramik-\nSpeicher", font_size=9, color=WHITE).move_to(
            ceramic
        )

        # Reversing Push-Pull flow
        push_pull_arr = DoubleArrow(
            center3 + LEFT * 0.95,
            center3 + RIGHT * 0.95,
            color=YELLOW,
            stroke_width=3,
            buff=0,
        ).move_to(center3 + DOWN * 0.52)
        lbl_cycle = Text("70s Raus / 70s Rein", font_size=10, color=YELLOW).next_to(
            push_pull_arr, DOWN, buff=0.04
        )

        lbl_loss3 = Text(
            "Regenerativer Pendelbetrieb", font_size=12, color=GREEN
        ).move_to(rect3.get_bottom() + UP * 0.35)

        col3 = VGroup(
            rect3,
            hdr3,
            base3,
            ceramic,
            lbl_ceramic,
            push_pull_arr,
            lbl_cycle,
            lbl_loss3,
        ).move_to(RIGHT * 4.1 + card_y)

        # Display columns sequentially
        self.play(FadeIn(col1, shift=UP * 0.3), run_time=1.2)
        self.wait(0.5)
        self.play(FadeIn(col2, shift=UP * 0.3), run_time=1.2)
        self.wait(0.5)
        self.play(FadeIn(col3, shift=UP * 0.3), run_time=1.2)
        self.wait(1.5)

        # Highlight energy savings summary banner at bottom
        summary_box = RoundedRectangle(
            width=12.2,
            height=0.6,
            corner_radius=0.1,
            color=YELLOW,
            fill_color="#2b2510",
            fill_opacity=0.9,
        ).to_edge(DOWN, buff=0.15)
        summary_text = Text(
            "Fazit: Mechanische Lüftung mit WRG halbiert die Gebäudeheizlast!",
            font_size=18,
            color=YELLOW,
        ).move_to(summary_box)

        self.play(Create(summary_box), Write(summary_text), run_time=1.5)
        self.wait(3.0)


class FullConvectionVideo(Scene):
    def construct(self):
        scenes = [
            Scene1,
            InteriorBuildingVolume,
            Scene3,
            Scene4,
            Scene5,
            Scene6_HeatRecoveryIntro,
            Scene7_VentilationSystemsComparison,
        ]
        base_dir = os.path.dirname(os.path.abspath(__file__))
        audio_files = [
            os.path.join(base_dir, f"scene_{i}_audio.mp3") for i in range(1, 8)
        ]

        for scene_cls, audio_path in zip(scenes, audio_files):
            if os.path.exists(audio_path):
                self.add_sound(audio_path)
            scene_cls.construct(self)
            self.clear()
