import os
import numpy as np
import math
from manim import *



class Scene1(Scene):
    def construct(self):
        # Set dark architectural background
        self.camera.background_color = "#0f1115"

        # --- TITLE ---
        title = Text("The House & Convection", font_size=32, color=WHITE)
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
        gap_bottom = (
            Line([1.0, -1.3, 0], [1.0, -0.3, 0], color=BLUE, stroke_width=2)
            .set_opacity(0.4)
        )
        gap_top = (
            Line([1.0, 0.3, 0], [1.0, 1.1, 0], color=ORANGE, stroke_width=2)
            .set_opacity(0.4)
        )

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
        label_inside = Text("Inside\n(Warm)", font_size=18, color=ORANGE).move_to(
            [-1.2, -0.5, 0]
        )
        label_outside = Text(
            "Outside\n(Cold)", font_size=18, color=BLUE_B
        ).move_to([2.6, -0.5, 0])

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

        # Continuous fluid motion display
        self.wait(5.0)

        # Clean up updaters
        orange_dots.remove_updater(update_orange_particles)
        blue_dots.remove_updater(update_blue_particles)

        self.wait(2)


class InteriorBuildingVolume(Scene):
    def construct(self):
        # Set dark architectural background
        self.camera.background_color = "#0f1115"

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
        house_outline = Polygon(
            *interior_points,
            color="#8A9BA8",
            stroke_width=3
        )
        
        ground = Line(
            start=[-3.8, -2.0, 0], 
            end=[3.8, -2.0, 0], 
            color="#5A6577", 
            stroke_width=2
        )

        # Window outline
        window = Rectangle(width=0.7, height=1.0, color="#8A9BA8", stroke_width=2)
        window.move_to([1.8, -0.8, 0])

        # Scene Title aligned with visual lesson styling
        title = Text("Interior Building Volume", font_size=36)
        title.to_edge(UP, buff=0.5)

        # External Blue Dots (outside air)
        blue_positions = [
            [-3.2, 1.5, 0], [-3.5, -0.5, 0], [-3.0, -1.5, 0],
            [3.2, 1.8, 0], [3.6, 0.2, 0], [3.3, -1.2, 0],
            [-1.5, 2.8, 0], [1.5, 2.8, 0], [0.0, 3.1, 0]
        ]
        blue_dots = VGroup(*[
            Dot(point=pos, color="#4C9EFF", radius=0.08)
            for pos in blue_positions
        ])

        # Internal Orange Dots (warm indoor air)
        orange_positions = [
            [-1.8, -1.3, 0], [-0.6, -1.4, 0], [0.7, -1.3, 0], [1.8, -1.4, 0],
            [-1.6, -0.3, 0], [-0.5, -0.2, 0], [0.6, -0.3, 0], [1.7, -0.2, 0],
            [-1.0, 0.7, 0], [0.0, 1.1, 0], [1.0, 0.7, 0], [0.0, -0.6, 0]
        ]
        orange_dots = VGroup(*[
            Dot(point=pos, color="#FF9F1C", radius=0.08)
            for pos in orange_positions
        ])

        # Initial display setup
        self.add(ground, house_outline, window, title, blue_dots, orange_dots)
        self.wait(0.5)

        # Animation Beat 1 & 2: Fade out external blue dots, dim inside orange dots to 30% opacity
        self.play(
            FadeOut(blue_dots, run_time=1.2),
            orange_dots.animate(run_time=1.2).set_opacity(0.3)
        )

        # Animation Beat 3: Translucent orange polygon filling the interior volume
        interior_fill = Polygon(
            *interior_points,
            fill_color="#FF9F1C",
            fill_opacity=0.35,
            stroke_width=0
        )
        self.play(
            FadeIn(interior_fill, run_time=1.5)
        )

        # Animation Beat 4: Orange variable 'V' and descriptive label in the middle of the house
        v_label = Text("V", font_size=56, color="#FF9F1C")
        v_subtext = Text("Volume (m³)", font_size=20, color="#FF9F1C")
        
        v_group = VGroup(v_label, v_subtext).arrange(DOWN, buff=0.1)
        v_group.move_to([0.0, -0.2, 0])

        self.play(
            Write(v_label, run_time=1.0),
            FadeIn(v_subtext, shift=UP * 0.15, run_time=1.0)
        )

        # Architectural dimension line indicator at bottom
        dim_line = Line(start=[-2.5, -2.3, 0], end=[2.5, -2.3, 0], color="#FF9F1C", stroke_width=1.5)
        dim_tick_l = Line(start=[-2.5, -2.4, 0], end=[-2.5, -2.2, 0], color="#FF9F1C", stroke_width=1.5)
        dim_tick_r = Line(start=[2.5, -2.4, 0], end=[2.5, -2.2, 0], color="#FF9F1C", stroke_width=1.5)
        dimension_group = VGroup(dim_line, dim_tick_l, dim_tick_r)

        self.play(
            Create(dimension_group, run_time=1.0)
        )

        # Final hold
        self.wait(2)


class Scene3(Scene):
    def construct(self):
        # Set scene background
        self.camera.background_color = "#0f1115"

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
        
        house_fill = Polygon(*house_points, fill_color=COLOR_V, fill_opacity=0.55, stroke_width=0)
        house_outline = Polygon(*house_points, color=WHITE, stroke_width=3, fill_opacity=0)
        house_fill.shift(house_shift)
        house_outline.shift(house_shift)

        # Label V inside house
        v_label = Text("V", font_size=52, color=COLOR_V).move_to(house_outline.get_center())

        # Beat 1: Draw house interior volume and label 'V'
        self.play(
            Create(house_outline),
            FadeIn(house_fill),
            Write(v_label),
            run_time=2.0
        )
        self.wait(0.8)

        # 2. Setup Clock Icon and Label 'n'
        clock_center = RIGHT * 2.4 + DOWN * 0.4
        clock_radius = 0.85
        clock_circle = Circle(radius=clock_radius, color=WHITE, stroke_width=3).move_to(clock_center)
        
        ticks = VGroup()
        for i in range(12):
            angle = i * (2 * PI / 12)
            start = clock_center + 0.70 * clock_radius * np.array([np.sin(angle), np.cos(angle), 0])
            end = clock_center + 0.92 * clock_radius * np.array([np.sin(angle), np.cos(angle), 0])
            ticks.add(Line(start, end, color=WHITE, stroke_width=2))
            
        hand = Line(clock_center, clock_center + UP * 0.6, color=WHITE, stroke_width=3)
        clock_icon = VGroup(clock_circle, ticks, hand)

        n_symbol = Text("n", font_size=52, color=COLOR_N).next_to(clock_icon, UP, buff=0.4)
        n_subtext = Text("Air Change Rate", font_size=22, color=WHITE).next_to(clock_icon, DOWN, buff=0.4)

        # Beat 2: Display white variable 'n' and minimalist clock
        self.play(
            Create(clock_icon),
            Write(n_symbol),
            FadeIn(n_subtext, shift=UP * 0.2),
            run_time=2.0
        )
        self.wait(0.5)

        # Beat 3: Clock minute hand sweeps 360 deg while interior transitions from warm orange to cold blue
        rate_caption = Text("1 Air Change = Full Volume Replaced", font_size=24, color=COLOR_COLD).to_edge(DOWN, buff=0.6)

        self.play(
            Rotate(hand, angle=-2 * PI, about_point=clock_center, rate_func=linear),
            house_fill.animate.set_fill(COLOR_COLD, opacity=0.65),
            v_label.animate.set_color(COLOR_V),
            FadeIn(rate_caption),
            run_time=3.5
        )
        self.wait(1.0)

        # 3. Form Equation 'V * n' at top center
        target_v = Text("V", font_size=48, color=COLOR_V)
        target_times = Text("×", font_size=40, color=WHITE)
        target_n = Text("n", font_size=48, color=COLOR_N)
        
        equation_group = VGroup(target_v, target_times, target_n).arrange(RIGHT, buff=0.25).move_to(UP * 3.1)

        v_copy = v_label.copy()
        n_copy = n_symbol.copy()

        # Beat 4: Transform 'V' and 'n' into equation at the top
        self.play(
            FadeOut(n_subtext),
            FadeOut(rate_caption),
            Transform(v_copy, target_v),
            Transform(n_copy, target_n),
            FadeIn(target_times),
            run_time=2.2
        )

        # Final hold
        self.wait(2.0)


class Scene4(Scene):
    def construct(self):
        # Set background color
        self.camera.background_color = "#0f1115"

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
            c_center, tl_pt, top_pt, tr_pt,
            fill_color=BLUE, fill_opacity=0.35, stroke_color=BLUE_A, stroke_width=2
        )
        face_left = Polygon(
            c_center, tl_pt, bl_pt, bot_pt,
            fill_color="#1565C0", fill_opacity=0.45, stroke_color=BLUE_A, stroke_width=2
        )
        face_right = Polygon(
            c_center, tr_pt, br_pt, bot_pt,
            fill_color="#0D47A1", fill_opacity=0.55, stroke_color=BLUE_A, stroke_width=2
        )

        cube = VGroup(face_top, face_left, face_right)
        
        # Position '1 m³' label inside the top face of the cube
        cube_label = Text("1 m³", font_size=28, color=WHITE).move_to(face_top.get_center())

        # Animate Cube Appearance
        self.play(
            FadeIn(cube, shift=UP * 0.3),
            Write(cube_label),
            run_time=2.0
        )
        self.wait(0.5)

        # Heating Coil (Sine wave below the cube)
        coil_y = -2.1
        coil = ParametricFunction(
            lambda t: np.array([
                t,
                0.1 * np.sin(10 * t) + coil_y,
                0
            ]),
            t_range=[-1.1, 1.1],
            color=RED
        ).set_stroke(width=4)

        coil_label = Text("Heating Element", font_size=16, color=RED_B).next_to(coil, DOWN, buff=0.15)

        self.play(
            Create(coil),
            FadeIn(coil_label),
            run_time=1.5
        )
        self.wait(0.5)

        # Heat Waves Animation
        heat_lines = VGroup()
        for x_off in [-0.7, -0.35, 0.0, 0.35, 0.7]:
            line = ParametricFunction(
                lambda t: np.array([
                    x_off + 0.05 * np.sin(8 * t),
                    t + coil_y + 0.15,
                    0
                ]),
                t_range=[0, 0.95],
                color=ORANGE
            ).set_stroke(width=2.5, opacity=0.8)
            heat_lines.add(line)

        # Warm target faces for color transition
        face_top_warm = Polygon(
            c_center, tl_pt, top_pt, tr_pt,
            fill_color=ORANGE, fill_opacity=0.45, stroke_color=ORANGE, stroke_width=2
        )
        face_left_warm = Polygon(
            c_center, tl_pt, bl_pt, bot_pt,
            fill_color="#E65100", fill_opacity=0.55, stroke_color=ORANGE, stroke_width=2
        )
        face_right_warm = Polygon(
            c_center, tr_pt, br_pt, bot_pt,
            fill_color="#BF360C", fill_opacity=0.65, stroke_color=ORANGE, stroke_width=2
        )

        self.play(
            Create(heat_lines),
            Transform(face_top, face_top_warm),
            Transform(face_left, face_left_warm),
            Transform(face_right, face_right_warm),
            run_time=2.5
        )

        # Introduce c_air variable next to the cube (without arrow)
        c_air_tag = Text("c_air", color=GREEN, font_size=36)
        c_air_desc = Text("Specific Heat Capacity", color=GREEN_B, font_size=16)
        c_air_group = VGroup(c_air_tag, c_air_desc).arrange(DOWN, aligned_edge=LEFT, buff=0.08)
        c_air_group.next_to(cube, RIGHT, buff=0.5).shift(DOWN * 0.2)

        self.play(
            FadeIn(c_air_group, shift=RIGHT * 0.2),
            run_time=1.5
        )
        self.wait(1.0)

        # Update Equation at Top: V * n -> V * n * c_air
        eq_times2 = Text(" × ", color=WHITE, font_size=40)
        eq_c = Text("c_air", color=GREEN, font_size=40)

        top_eq_full = VGroup(
            Text("V", color=ORANGE, font_size=40),
            Text(" × ", color=WHITE, font_size=40),
            Text("n", color=WHITE, font_size=40),
            eq_times2,
            eq_c
        ).arrange(RIGHT, buff=0.1).to_edge(UP, buff=0.4)

        self.play(
            Transform(top_eq_initial, top_eq_full[:3]),
            FadeIn(top_eq_full[3:]),
            run_time=1.5
        )

        # Final hold
        self.wait(2.0)


class Scene5(Scene):
    def construct(self):
        # Set dark background theme
        self.camera.background_color = "#0f1115"

        # --- Scene Title ---
        title = Text("Ventilation Heat Loss Equation", font_size=36, color=WHITE)
        title.to_edge(UP, buff=0.5)
        self.add(title)

        # --- Initial State (carried from previous scene) ---
        top_v = Text("V", color=ORANGE, font_size=32)
        top_dot1 = Text(" · ", color=WHITE, font_size=32)
        top_n = Text("n", color=WHITE, font_size=32)
        top_dot2 = Text(" · ", color=WHITE, font_size=32)
        top_c = Text("c_air", color=GREEN, font_size=32)
        top_terms = VGroup(top_v, top_dot1, top_n, top_dot2, top_c).arrange(RIGHT, buff=0.1)
        top_terms.next_to(title, DOWN, buff=0.4)

        # Representing unit cube and heating coil from previous scene
        cube = Square(side_length=1.6, color=BLUE, fill_opacity=0.15, stroke_width=2).shift(DOWN * 0.8)
        cube_label = Text("1 m³", color=BLUE_B, font_size=20).move_to(cube)
        coil = Line(LEFT * 0.8, RIGHT * 0.8, color=RED, stroke_width=4).next_to(cube, DOWN, buff=0.1)
        prev_visuals = VGroup(cube, cube_label, coil)

        self.add(top_terms, prev_visuals)
        self.wait(0.5)

        # --- Beat 1: Fade Unit Cube and Coil ---
        self.play(
            FadeOut(prev_visuals),
            run_time=1.0
        )

        # --- Beat 2: Display Yellow Vertical Bracket and Delta T ---
        t_inside = Text("T_in  (Inside Temp)", color="#FF6B6B", font_size=22).shift(UP * 0.3 + RIGHT * 1.2)
        t_outside = Text("T_out (Outside Temp)", color="#4D96FF", font_size=22).shift(DOWN * 1.5 + RIGHT * 1.2)

        dt_brace = BraceBetweenPoints(
            t_outside.get_left() + LEFT * 0.3, 
            t_inside.get_left() + LEFT * 0.3, 
            direction=LEFT, 
            color=YELLOW
        )
        dt_label = Text("ΔT", color=YELLOW, font_size=36).next_to(dt_brace, LEFT, buff=0.25)
        
        dt_sub = VGroup(
            Text("Temperature", color=YELLOW, font_size=16),
            Text("Difference", color=YELLOW, font_size=16)
        ).arrange(DOWN, buff=0.05).next_to(dt_label, DOWN, buff=0.15)

        self.play(
            FadeIn(t_inside, shift=LEFT * 0.2),
            FadeIn(t_outside, shift=LEFT * 0.2),
            GrowFromCenter(dt_brace),
            Write(dt_label),
            FadeIn(dt_sub),
            run_time=2.0
        )
        self.wait(1.0)

        # --- Beat 3: Morph Terms into Final Master Equation ---
        eq_phi = Text("Φ_vent = ", color=WHITE, font_size=42)
        eq_v = Text("V", color=ORANGE, font_size=42)
        eq_dot1 = Text(" · ", color=WHITE, font_size=42)
        eq_n = Text("n", color=WHITE, font_size=42)
        eq_dot2 = Text(" · ", color=WHITE, font_size=42)
        eq_c = Text("c_air", color=GREEN, font_size=42)
        eq_dot3 = Text(" · ", color=WHITE, font_size=42)
        eq_dt = Text("ΔT", color=YELLOW, font_size=42)

        master_eq = VGroup(
            eq_phi, eq_v, eq_dot1, eq_n, eq_dot2, eq_c, eq_dot3, eq_dt
        ).arrange(RIGHT, buff=0.1).move_to(UP * 0.8)

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
            run_time=2.0
        )

        # Frame surrounding the complete master equation
        eq_box = SurroundingRectangle(master_eq, color=WHITE, buff=0.25, corner_radius=0.15, stroke_width=2)
        self.play(Create(eq_box), run_time=1.0)
        self.wait(0.5)

        # --- Beat 4: Highlight Color Coding & Explanatory Labels ---
        card_v = VGroup(
            Text("V", color=ORANGE, font_size=22),
            Text("Building Volume", color=GREY_A, font_size=14),
            Text("(m³)", color=GREY_A, font_size=14)
        ).arrange(DOWN, buff=0.08)

        card_n = VGroup(
            Text("n", color=WHITE, font_size=22),
            Text("Air Change Rate", color=GREY_A, font_size=14),
            Text("(1/h)", color=GREY_A, font_size=14)
        ).arrange(DOWN, buff=0.08)

        card_c = VGroup(
            Text("c_air", color=GREEN, font_size=22),
            Text("Specific Heat", color=GREY_A, font_size=14),
            Text("Capacity", color=GREY_A, font_size=14)
        ).arrange(DOWN, buff=0.08)

        card_dt = VGroup(
            Text("ΔT", color=YELLOW, font_size=22),
            Text("Temp Difference", color=GREY_A, font_size=14),
            Text("(K or °C)", color=GREY_A, font_size=14)
        ).arrange(DOWN, buff=0.08)

        cards = VGroup(card_v, card_n, card_c, card_dt).arrange(RIGHT, buff=0.5)
        cards.next_to(eq_box, DOWN, buff=0.8)

        highlights = [
            (eq_v, card_v),
            (eq_n, card_n),
            (eq_c, card_c),
            (eq_dt, card_dt)
        ]

        for target_eq, card in highlights:
            self.play(
                target_eq.animate.scale(1.25),
                FadeIn(card, shift=UP * 0.15),
                run_time=0.5
            )
            self.play(
                target_eq.animate.scale(1 / 1.25),
                run_time=0.3
            )

        self.wait(1.5)

        # --- Beat 5: Fade Scene to Black ---
        self.play(
            FadeOut(Group(*self.mobjects)),
            run_time=1.5
        )
        self.wait(2)


class FullConvectionVideo(Scene):
    def construct(self):
        scenes = [Scene1, InteriorBuildingVolume, Scene3, Scene4, Scene5]
        base_dir = os.path.dirname(os.path.abspath(__file__))
        audio_files = [
            os.path.join(base_dir, f"scene_{i}_audio.mp3")
            for i in range(1, 6)
        ]
        
        for scene_cls, audio_path in zip(scenes, audio_files):
            if os.path.exists(audio_path):
                self.add_sound(audio_path)
            scene_cls.construct(self)
            self.clear()


