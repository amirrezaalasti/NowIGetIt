"""Curated Manim CE pattern snippets for retrieval-augmented codegen."""

from __future__ import annotations

from dataclasses import dataclass

from backend.schemas import SceneSection


@dataclass(frozen=True)
class ManimTemplate:
    id: str
    title: str
    tags: tuple[str, ...]
    devices: tuple[str, ...]
    snippet: str


TEMPLATES: list[ManimTemplate] = [
    ManimTemplate(
        id="axes_parabola",
        title="Axes + plotted curve + moving tangent",
        tags=("axes", "graph", "parabola", "tangent", "calculus"),
        devices=("axes_graph",),
        snippet="""
# Pattern: axes, plot, ValueTracker for a moving point / tangent
axes = Axes(x_range=[-3, 3, 1], y_range=[-1, 5, 1], x_length=7, y_length=5)
graph = axes.plot(lambda x: x**2, x_range=[-2, 2], color=YELLOW)
dot = Dot(color=RED)
tracker = ValueTracker(-2)

def update_dot(m):
    x = tracker.get_value()
    m.move_to(axes.c2p(x, x**2))
dot.add_updater(update_dot)

self.play(Create(axes), Create(graph), run_time=1.5)
self.play(FadeIn(dot), tracker.animate.set_value(2), run_time=2.5)
""".strip(),
    ),
    ManimTemplate(
        id="equation_reveal",
        title="Stepwise equation / formula reveal",
        tags=("equation", "formula", "reveal", "algebra"),
        devices=("equation_reveal",),
        snippet="""
# Pattern: stacked Text equations, Transform between steps (no MathTex)
eq1 = Text("Q = m * c * ΔT", font_size=40)
eq2 = Text("heat = mass × heat capacity × temp change", font_size=32)
eq1.to_edge(UP)
eq2.next_to(eq1, DOWN, buff=0.6)
self.play(Write(eq1), run_time=1.2)
self.wait(0.4)
self.play(TransformMatchingShapes(eq1.copy(), eq2), run_time=1.5)
""".strip(),
    ),
    ManimTemplate(
        id="before_after",
        title="Side-by-side before / after comparison",
        tags=("compare", "before", "after", "split"),
        devices=("before_after", "comparison_split"),
        snippet="""
# Pattern: left/right panels with a divider
left = RoundedRectangle(width=5, height=4, corner_radius=0.15).shift(LEFT * 3.2)
right = RoundedRectangle(width=5, height=4, corner_radius=0.15).shift(RIGHT * 3.2)
divider = Line(UP * 2.2, DOWN * 2.2, color=GREY)
label_l = Text("Before", font_size=28).next_to(left, UP)
label_r = Text("After", font_size=28).next_to(right, UP)
self.play(Create(left), Create(right), Create(divider), Write(label_l), Write(label_r), run_time=1.5)
""".strip(),
    ),
    ManimTemplate(
        id="particle_flow",
        title="Particle / fluid motion with updaters",
        tags=("particles", "flow", "fluid", "convection", "heat"),
        devices=("particle_flow",),
        snippet="""
# Pattern: dots with updaters drifting upward (convection-style)
import random
particles = VGroup()
for _ in range(24):
    p = Dot(radius=0.05, color=ORANGE)
    p.move_to([random.uniform(-2, 2), random.uniform(-2, 1), 0])
    particles.add(p)

def drift(m, dt):
    m.shift(UP * dt * 0.6)
    if m.get_y() > 2.5:
        m.set_y(-2.2)
for p in particles:
    p.add_updater(drift)

self.add(particles)
self.wait(3)
for p in particles:
    p.clear_updaters()
""".strip(),
    ),
    ManimTemplate(
        id="number_line",
        title="Number line with moving brace / tick",
        tags=("number_line", "scale", "interval", "brace"),
        devices=("number_line",),
        snippet="""
# Pattern: NumberLine + moving indicator
line = NumberLine(x_range=[-4, 4, 1], length=10, include_numbers=True)
dot = Dot(color=YELLOW).move_to(line.n2p(0))
label = Text("x", font_size=28).next_to(dot, UP)
self.play(Create(line), FadeIn(dot), Write(label), run_time=1.2)
self.play(dot.animate.move_to(line.n2p(2.5)), run_time=1.5)
label.next_to(dot, UP)
""".strip(),
    ),
    ManimTemplate(
        id="unit_circle",
        title="Unit circle with sine / cosine projections",
        tags=("circle", "trig", "sine", "cosine", "unit_circle"),
        devices=("unit_circle",),
        snippet="""
# Pattern: unit circle + angle tracker + projections
circle = Circle(radius=2, color=BLUE)
axes = Axes(x_range=[-2.5, 2.5], y_range=[-2.5, 2.5], x_length=5, y_length=5)
theta = ValueTracker(0)
dot = always_redraw(lambda: Dot(circle.point_at_angle(theta.get_value()), color=YELLOW))
self.play(Create(axes), Create(circle), run_time=1.2)
self.add(dot)
self.play(theta.animate.set_value(PI), run_time=2.5)
""".strip(),
    ),
    ManimTemplate(
        id="lattice_grid",
        title="Atom / lattice grid with heat sweep",
        tags=("lattice", "grid", "atoms", "conduction", "heat"),
        devices=("lattice_grid",),
        snippet="""
# Pattern: grid of dots, color sweep from left (heat flow)
rows, cols = 4, 6
dots = VGroup()
for r in range(rows):
    for c in range(cols):
        d = Dot(point=[c * 0.7 - 2, r * 0.7 - 1, 0], radius=0.12, color=BLUE)
        dots.add(d)
self.play(LaggedStart(*[FadeIn(d) for d in dots], lag_ratio=0.05), run_time=1.5)
self.play(*[d.animate.set_color(ORANGE) for d in dots[:cols]], run_time=1.2)
""".strip(),
    ),
    ManimTemplate(
        id="morph_transform",
        title="Shape morph / ReplacementTransform",
        tags=("morph", "transform", "shape"),
        devices=("morph_transform",),
        snippet="""
# Pattern: morph one shape into another
a = Circle(radius=1.2, color=TEAL).shift(LEFT * 2)
b = Square(side_length=2.2, color=GOLD).shift(RIGHT * 2)
self.play(Create(a), run_time=0.8)
self.play(ReplacementTransform(a, b), run_time=1.5)
""".strip(),
    ),
    ManimTemplate(
        id="house_section",
        title="Architectural cross-section (walls / volume)",
        tags=("house", "building", "architecture", "wall", "insulation"),
        devices=("house_section",),
        snippet="""
# Pattern: simple house outline + filled interior
roof = Polygon([-2, 1, 0], [2, 1, 0], [0, 2.5, 0], color=GREY_B)
walls = Polygon([-1.8, -1.5, 0], [1.8, -1.5, 0], [1.8, 1, 0], [-1.8, 1, 0], color=GREY_B)
interior = walls.copy().set_fill(ORANGE, opacity=0.35).set_stroke(width=0)
self.play(Create(walls), Create(roof), run_time=1.2)
self.play(FadeIn(interior), run_time=1.0)
""".strip(),
    ),
]


def retrieve_templates(scene: SceneSection, *, limit: int = 2) -> list[ManimTemplate]:
    """Score templates by visual_device + style_tags + description keywords."""
    device = (scene.visual_device or "").strip().lower()
    tags = {t.strip().lower() for t in (scene.style_tags or []) if t}
    blob = " ".join(
        [
            scene.visual_description or "",
            " ".join(scene.animation_beats or []),
            scene.title or "",
        ]
    ).lower()

    scored: list[tuple[int, ManimTemplate]] = []
    for tpl in TEMPLATES:
        score = 0
        if device and device in tpl.devices:
            score += 5
        for tag in tags:
            if tag in tpl.tags:
                score += 3
            elif tag in tpl.id or tag in tpl.title.lower():
                score += 2
        for tag in tpl.tags:
            if tag in blob:
                score += 1
        if score > 0:
            scored.append((score, tpl))

    scored.sort(key=lambda x: (-x[0], x[1].id))
    if scored:
        return [t for _, t in scored[:limit]]

    # Fallback: axes_graph or equation_reveal from narration cues
    if any(w in blob for w in ("graph", "plot", "curve", "parabola", "axes")):
        return [TEMPLATES[0]]
    if any(w in blob for w in ("equation", "formula", "equals")):
        return [TEMPLATES[1]]
    return [TEMPLATES[0]]


def format_templates_for_prompt(templates: list[ManimTemplate]) -> str:
    if not templates:
        return "(no templates)"
    parts = []
    for t in templates:
        parts.append(
            f"### Template `{t.id}` — {t.title}\n```python\n{t.snippet}\n```"
        )
    return "\n\n".join(parts)
