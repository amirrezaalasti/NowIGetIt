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
# Pattern: one formula at a time (FadeOut → FadeIn). No TransformMatchingShapes.
eq1 = Text("loss = (y - ŷ)²", font_size=40)
eq1.move_to(ORIGIN)
self.play(Write(eq1), run_time=1.2)
self.wait(0.5)
eq2 = Text("smaller loss → better fit", font_size=32)
eq2.move_to(ORIGIN)
self.play(FadeOut(eq1), FadeIn(eq2), run_time=1.0)
""".strip(),
    ),
    ManimTemplate(
        id="neural_net_layers",
        title="Sparse neural net: columns of nodes + edges",
        tags=("network", "neural", "layers", "nodes", "weights", "backprop"),
        devices=("labeled_box_flow", "annotated_diagram", "particle_flow"),
        snippet="""
# Pattern: 3 columns of Circles (≤4/layer), thin Lines, short layer labels
title = Text("Neural Net", font_size=36).to_edge(UP, buff=0.35)
layers = [3, 4, 2]
cols = VGroup()
for li, n in enumerate(layers):
    nodes = VGroup(*[Circle(radius=0.22, color=TEAL, stroke_width=2) for _ in range(n)])
    nodes.arrange(DOWN, buff=0.35)
    cols.add(nodes)
cols.arrange(RIGHT, buff=2.2)
cols.move_to(ORIGIN + DOWN * 0.15)
edges = VGroup()
for a, b in zip(cols[:-1], cols[1:]):
    for na in a:
        for nb in b:
            edges.add(Line(na.get_right(), nb.get_left(), stroke_width=1.5, color=GREY_B))
labels = VGroup(
    Text("In", font_size=24).next_to(cols[0], DOWN, buff=0.35),
    Text("Hidden", font_size=24).next_to(cols[1], DOWN, buff=0.35),
    Text("Out", font_size=24).next_to(cols[2], DOWN, buff=0.35),
)
self.play(Write(title), run_time=0.5)
self.play(LaggedStart(*[FadeIn(c) for c in cols], lag_ratio=0.25), run_time=1.2)
self.play(Create(edges), FadeIn(labels), run_time=1.0)
# Highlight a path instead of dumping weight text
self.play(
    cols[0][1].animate.set_color(ORANGE),
    cols[1][2].animate.set_color(ORANGE),
    cols[2][0].animate.set_color(ORANGE),
    run_time=1.2,
)
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
    ManimTemplate(
        id="labeled_box_flow",
        title="Horizontal labeled boxes with arrows (pipeline)",
        tags=("boxes", "pipeline", "flow", "network", "layers", "lstm", "transformer"),
        devices=("labeled_box_flow",),
        snippet="""
# Pattern: 3 short-labeled boxes in a row — never crowd formulas on the arrows
title = Text("Data Flow", font_size=36).to_edge(UP, buff=0.35)
boxes = VGroup()
labels = ["Input", "Process", "Output"]
for name in labels:
    box = RoundedRectangle(width=2.4, height=1.4, corner_radius=0.12, color=TEAL)
    lab = Text(name, font_size=26)
    boxes.add(VGroup(box, lab))
boxes.arrange(RIGHT, buff=1.1)
arrows = VGroup(
    Arrow(boxes[0].get_right(), boxes[1].get_left(), buff=0.12, color=GREY_B),
    Arrow(boxes[1].get_right(), boxes[2].get_left(), buff=0.12, color=GREY_B),
)
group = VGroup(boxes, arrows).move_to(ORIGIN)
self.play(Write(title), run_time=0.6)
self.play(LaggedStart(*[FadeIn(b) for b in boxes], lag_ratio=0.2), run_time=1.2)
self.play(LaggedStart(*[GrowArrow(a) for a in arrows], lag_ratio=0.2), run_time=0.8)
# Optional single caption zone BELOW — never overlay on arrows
caption = Text("one step at a time", font_size=28).next_to(group, DOWN, buff=0.55)
self.play(FadeIn(caption), run_time=0.6)
""".strip(),
    ),
    ManimTemplate(
        id="gate_mechanism",
        title="Single gate / cell box with progressive internals",
        tags=("gate", "sigmoid", "tanh", "lstm", "cell", "memory", "forget", "input"),
        devices=("gate_mechanism",),
        snippet="""
# Pattern: ONE gate box; reveal internals then ONE formula in a bottom zone
title = Text("Forget Gate", font_size=36).to_edge(UP, buff=0.35)
gate = RoundedRectangle(width=4.2, height=2.6, corner_radius=0.15, color=ORANGE)
gate.move_to(ORIGIN + UP * 0.2)
gate_label = Text("Forget Gate", font_size=24).next_to(gate, UP, buff=0.15)
sigma = Text("σ", font_size=40).move_to(gate.get_center() + LEFT * 0.9)
tanh_t = Text("tanh", font_size=28).move_to(gate.get_center() + RIGHT * 0.8)
# Inputs from left — short labels only
h_in = Text("h(t-1)", font_size=24).next_to(gate, LEFT, buff=0.9).shift(UP * 0.5)
x_in = Text("x(t)", font_size=24).next_to(gate, LEFT, buff=0.9).shift(DOWN * 0.5)
a1 = Arrow(h_in.get_right(), gate.get_left() + UP * 0.4, buff=0.1, color=TEAL)
a2 = Arrow(x_in.get_right(), gate.get_left() + DOWN * 0.4, buff=0.1, color=TEAL)
self.play(Write(title), Create(gate), Write(gate_label), run_time=1.0)
self.play(FadeIn(h_in), FadeIn(x_in), GrowArrow(a1), GrowArrow(a2), run_time=1.0)
self.play(Write(sigma), Write(tanh_t), run_time=0.8)
# Clear busy labels before showing formula (prevents overlap)
self.play(FadeOut(h_in), FadeOut(x_in), FadeOut(a1), FadeOut(a2), run_time=0.4)
formula = Text("f(t) = σ(W · [h, x] + b)", font_size=30)
formula.to_edge(DOWN, buff=0.55)
self.play(Write(formula), run_time=1.0)
""".strip(),
    ),
    ManimTemplate(
        id="annotated_diagram",
        title="Diagram zone + reserved formula/caption zone",
        tags=("annotated", "diagram", "zones", "callout", "architecture"),
        devices=("annotated_diagram",),
        snippet="""
# Pattern: fixed layout zones — diagram center, one annotation bottom (never overlap)
title = Text("Cell State Path", font_size=36).to_edge(UP, buff=0.35)
diagram = VGroup(
    Line(LEFT * 4, RIGHT * 4, color=TEAL),
    RoundedRectangle(width=2.2, height=1.3, corner_radius=0.12, color=ORANGE),
)
diagram[1].move_to(ORIGIN)
diag_lab = Text("Update", font_size=26).move_to(diagram[1].get_center())
diagram_group = VGroup(diagram, diag_lab).shift(UP * 0.35)
# Reserved bottom band for exactly one explanation line
note = Text("cell state flows left → right", font_size=28).to_edge(DOWN, buff=0.55)
self.play(Write(title), Create(diagram[0]), Create(diagram[1]), Write(diag_lab), run_time=1.4)
self.play(FadeIn(note), run_time=0.7)
# Next beat: replace note instead of stacking
note2 = Text("gates scale what is kept", font_size=28).to_edge(DOWN, buff=0.55)
self.play(FadeOut(note), FadeIn(note2), run_time=0.7)
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

    # Fallback: pick from narration cues when scorer finds nothing
    by_id = {t.id: t for t in TEMPLATES}
    if any(
        w in blob
        for w in ("gate", "lstm", "sigmoid", "tanh", "forget", "cell state")
    ):
        return [by_id["gate_mechanism"], by_id["annotated_diagram"]]
    if any(
        w in blob
        for w in (
            "neural",
            "neuron",
            "backprop",
            "forward pass",
            "hidden layer",
            "weights",
        )
    ):
        return [by_id["neural_net_layers"], by_id["annotated_diagram"]]
    if any(
        w in blob
        for w in ("pipeline", "layer", "network", "transformer", "encoder", "boxes")
    ):
        return [by_id["labeled_box_flow"], by_id["neural_net_layers"]]
    if any(w in blob for w in ("graph", "plot", "curve", "parabola", "axes")):
        return [by_id["axes_parabola"]]
    if any(w in blob for w in ("equation", "formula", "equals")):
        return [by_id["equation_reveal"]]
    return [by_id["annotated_diagram"]]


def format_templates_for_prompt(templates: list[ManimTemplate]) -> str:
    if not templates:
        return "(no templates)"
    parts = []
    for t in templates:
        parts.append(
            f"### Template `{t.id}` — {t.title}\n```python\n{t.snippet}\n```"
        )
    return "\n\n".join(parts)
