"""Curated Manim CE pattern snippets for retrieval-augmented codegen.

Also loads `samples/*.py` (user + Manim docs adaptations). Drop a new
`.py` scene file in `samples/` and register it in `SAMPLE_META` to feed codegen.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

from backend.schemas import SceneSection

_SAMPLES_DIR = Path(__file__).resolve().parents[2] / "samples"


@dataclass(frozen=True)
class ManimTemplate:
    id: str
    title: str
    tags: tuple[str, ...]
    devices: tuple[str, ...]
    snippet: str


# Metadata for files in samples/. Files needing manim_physics / SpaceScene are skipped.
SAMPLE_META: dict[str, dict] = {
    "MovingAngle.py": {
        "title": "ValueTracker angle with live Angle updater",
        "tags": ("angle", "geometry", "tracker", "trig", "theta"),
        "devices": ("unit_circle", "angle_tracker", "axes_graph"),
    },
    "DynamicPolygon.py": {
        "title": "always_redraw area under curve (xy=k)",
        "tags": ("area", "axes", "tracker", "optimization", "calculus", "polygon"),
        "devices": ("axes_graph",),
    },
    "SineCurve.py": {
        "title": "Unit circle draws a sine wave (always_redraw)",
        "tags": ("sine", "wave", "circle", "always_redraw", "trig", "orbit"),
        "devices": ("unit_circle", "axes_graph", "path_trace"),
    },
    "DancingCircles.py": {
        "title": "Formation change + group Rotate",
        "tags": ("circles", "formation", "rotate", "ensemble", "particles"),
        "devices": ("particle_flow", "morph_transform"),
    },
    "BooleanOperations.py": {
        "title": "Intersection / Union / Exclusion / Difference",
        "tags": ("boolean", "sets", "venn", "intersection", "union"),
        "devices": ("comparison_split", "before_after", "boolean_sets"),
    },
    "EquationMoving.py": {
        "title": "Moving SurroundingRectangle over equation terms",
        "tags": ("equation", "highlight", "surround", "framebox", "formula"),
        "devices": ("equation_reveal",),
    },
    "GridTransform.py": {
        "title": "Nonlinear NumberPlane warp",
        "tags": ("grid", "transform", "lattice", "warp", "coordinates"),
        "devices": ("lattice_grid", "morph_transform"),
    },
    "PointMovingOnShapes.py": {
        "title": "MoveAlongPath + Rotating",
        "tags": ("path", "orbit", "particle", "movealongpath"),
        "devices": ("path_trace", "particle_flow", "unit_circle"),
    },
    "PointWithTrace.py": {
        "title": "Point leaves a traced trail",
        "tags": ("trace", "trail", "path", "updater"),
        "devices": ("path_trace", "particle_flow"),
    },
    "MovingDots.py": {
        "title": "Dual ValueTrackers + linked line",
        "tags": ("tracker", "dots", "linked", "updater"),
        "devices": ("particle_flow", "axes_graph"),
    },
    "VectorArrow.py": {
        "title": "NumberPlane + labeled vector",
        "tags": ("vector", "plane", "arrow", "coordinates", "physics"),
        "devices": ("axes_graph", "vector_field"),
    },
    "BraceAnnotation.py": {
        "title": "Brace label on a segment",
        "tags": ("brace", "annotation", "distance", "geometry"),
        "devices": ("annotated_diagram", "number_line"),
    },
    "RotationUpdater.py": {
        "title": "dt updater continuous rotation",
        "tags": ("updater", "rotation", "continuous", "spin"),
        "devices": ("unit_circle", "particle_flow"),
    },
    "IndicateHighlight.py": {
        "title": "Indicate + Circumscribe attention",
        "tags": ("indicate", "circumscribe", "highlight", "attention", "boxes"),
        "devices": ("labeled_box_flow", "annotated_diagram", "gate_mechanism"),
    },
    "ArrowVectorFieldDemo.py": {
        "title": "ArrowVectorField flow (no manim_physics)",
        "tags": ("field", "vector", "physics", "flow", "charge"),
        "devices": ("vector_field", "particle_flow"),
    },
}


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
# Build near origin, arrange, then center — never absolute LEFT/RIGHT*3 shifts.
title = Text("Neural Net", font_size=36).to_edge(UP, buff=0.3)
layers = [3, 4, 2]
cols = VGroup()
for li, n in enumerate(layers):
    nodes = VGroup(*[Circle(radius=0.22, color=TEAL, stroke_width=2) for _ in range(n)])
    nodes.arrange(DOWN, buff=0.35)
    cols.add(nodes)
cols.arrange(RIGHT, buff=1.6)
edges = VGroup()
for a, b in zip(cols[:-1], cols[1:]):
    for na in a:
        for nb in b:
            edges.add(Line(na.get_right(), nb.get_left(), stroke_width=1.5, color=GREY_B))
labels = VGroup(
    Text("In", font_size=24).next_to(cols[0], DOWN, buff=0.3),
    Text("Hidden", font_size=24).next_to(cols[1], DOWN, buff=0.3),
    Text("Out", font_size=24).next_to(cols[2], DOWN, buff=0.3),
)
net = VGroup(cols, edges, labels).move_to(ORIGIN + DOWN * 0.15)
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
# Pattern: left/right panels arranged then centered (stays inside frame)
left = RoundedRectangle(width=5.0, height=3.6, corner_radius=0.15)
right = RoundedRectangle(width=5.0, height=3.6, corner_radius=0.15)
label_l = Text("Before", font_size=28).next_to(left, UP, buff=0.2)
label_r = Text("After", font_size=28).next_to(right, UP, buff=0.2)
panels = VGroup(VGroup(left, label_l), VGroup(right, label_r))
panels.arrange(RIGHT, buff=0.7).move_to(ORIGIN + DOWN * 0.1)
divider = Line(UP * 1.6, DOWN * 1.6, color=GREY).move_to(ORIGIN + DOWN * 0.1)
self.play(Create(left), Create(right), Create(divider), Write(label_l), Write(label_r), run_time=1.5)
""".strip(),
    ),
    ManimTemplate(
        id="particle_flow",
        title="Particle / fluid motion with updaters",
        tags=("particles", "flow", "fluid", "convection", "heat"),
        devices=("particle_flow",),
        snippet="""
# Pattern: dots with updaters drifting upward (convection-style) — keep inside frame
import random
particles = VGroup()
for _ in range(20):
    p = Dot(radius=0.05, color=ORANGE)
    p.move_to([random.uniform(-2.5, 2.5), random.uniform(-1.8, 1.2), 0])
    particles.add(p)

def drift(m, dt):
    m.shift(UP * dt * 0.6)
    if m.get_y() > 2.2:
        m.set_y(-1.8)
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
# Pattern: NumberLine + moving indicator (centered, fits frame)
line = NumberLine(x_range=[-4, 4, 1], length=10, include_numbers=True)
line.move_to(ORIGIN)
dot = Dot(color=YELLOW).move_to(line.n2p(0))
label = Text("x", font_size=28).next_to(dot, UP, buff=0.2)
self.play(Create(line), FadeIn(dot), Write(label), run_time=1.2)
self.play(dot.animate.move_to(line.n2p(2.5)), run_time=1.5)
label.next_to(dot, UP, buff=0.2)
""".strip(),
    ),
    ManimTemplate(
        id="unit_circle",
        title="Unit circle with sine / cosine projections",
        tags=("circle", "trig", "sine", "cosine", "unit_circle"),
        devices=("unit_circle",),
        snippet="""
# Pattern: unit circle + angle tracker + projections (centered)
circle = Circle(radius=2, color=BLUE)
axes = Axes(x_range=[-2.5, 2.5], y_range=[-2.5, 2.5], x_length=5, y_length=5)
group = VGroup(axes, circle).move_to(ORIGIN)
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
# Pattern: grid of dots, color sweep from left (heat flow) — build then center
rows, cols = 4, 6
dots = VGroup()
for r in range(rows):
    for c in range(cols):
        d = Dot(radius=0.12, color=BLUE)
        dots.add(d)
dots.arrange_in_grid(rows, cols, buff=0.45).move_to(ORIGIN)
self.play(LaggedStart(*[FadeIn(d) for d in dots], lag_ratio=0.05), run_time=1.5)
self.play(*[d.animate.set_color(ORANGE) for d in dots[:cols]], run_time=1.2)
""".strip(),
    ),
    ManimTemplate(
        id="morph_transform",
        title="Concept morph via ReplacementTransform",
        tags=("morph", "transform", "fit", "model"),
        devices=("morph_transform",),
        snippet="""
# Pattern: morph ONLY when it teaches (wrong fit → better fit). Never decorative Circle↔Square.
title = Text("Better Fit", font_size=36).to_edge(UP, buff=0.3)
axes = Axes(x_range=[-2, 2, 1], y_range=[-0.5, 4, 1], x_length=6, y_length=3.8)
axes.move_to(ORIGIN + DOWN * 0.1)
bad = axes.plot(lambda x: 0.2 * x + 1.2, x_range=[-2, 2], color=RED)
good = axes.plot(lambda x: x**2, x_range=[-2, 2], color=TEAL)
cap = Text("wrong model → right model", font_size=28).to_edge(DOWN, buff=0.35)
self.play(Write(title), Create(axes), run_time=0.8)
self.play(Create(bad), FadeIn(cap), run_time=0.8)
self.play(ReplacementTransform(bad, good), run_time=1.4)
""".strip(),
    ),
    ManimTemplate(
        id="house_section",
        title="Architectural cross-section (walls / volume)",
        tags=("house", "building", "architecture", "wall", "insulation"),
        devices=("house_section",),
        snippet="""
# Pattern: simple house outline + filled interior (centered)
roof = Polygon([-2, 1, 0], [2, 1, 0], [0, 2.5, 0], color=GREY_B)
walls = Polygon([-1.8, -1.5, 0], [1.8, -1.5, 0], [1.8, 1, 0], [-1.8, 1, 0], color=GREY_B)
interior = walls.copy().set_fill(ORANGE, opacity=0.35).set_stroke(width=0)
house = VGroup(walls, roof, interior).move_to(ORIGIN)
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
# Pattern: 3 short-labeled boxes in a row — arrange then center
title = Text("Data Flow", font_size=36).to_edge(UP, buff=0.3)
boxes = VGroup()
labels = ["Input", "Process", "Output"]
for name in labels:
    box = RoundedRectangle(width=2.2, height=1.3, corner_radius=0.12, color=TEAL)
    lab = Text(name, font_size=26)
    boxes.add(VGroup(box, lab))
boxes.arrange(RIGHT, buff=0.9)
arrows = VGroup(
    Arrow(boxes[0].get_right(), boxes[1].get_left(), buff=0.1, color=GREY_B),
    Arrow(boxes[1].get_right(), boxes[2].get_left(), buff=0.1, color=GREY_B),
)
group = VGroup(boxes, arrows).move_to(ORIGIN)
self.play(Write(title), run_time=0.6)
self.play(LaggedStart(*[FadeIn(b) for b in boxes], lag_ratio=0.2), run_time=1.2)
self.play(LaggedStart(*[GrowArrow(a) for a in arrows], lag_ratio=0.2), run_time=0.8)
caption = Text("one step at a time", font_size=28).next_to(group, DOWN, buff=0.35)
self.play(FadeIn(caption), run_time=0.6)
""".strip(),
    ),
    ManimTemplate(
        id="gate_mechanism",
        title="Single gate / cell box with progressive internals",
        tags=("gate", "sigmoid", "tanh", "lstm", "cell", "memory", "forget", "input"),
        devices=("gate_mechanism",),
        snippet="""
# Pattern: ONE gate box; build assembly then center so labels stay on-frame
title = Text("Forget Gate", font_size=36).to_edge(UP, buff=0.3)
gate = RoundedRectangle(width=3.8, height=2.4, corner_radius=0.15, color=ORANGE)
gate_label = Text("Forget Gate", font_size=24).next_to(gate, UP, buff=0.15)
sigma = Text("σ", font_size=40).move_to(gate.get_center() + LEFT * 0.8)
tanh_t = Text("tanh", font_size=28).move_to(gate.get_center() + RIGHT * 0.7)
h_in = Text("h(t-1)", font_size=24).next_to(gate, LEFT, buff=0.45).shift(UP * 0.4)
x_in = Text("x(t)", font_size=24).next_to(gate, LEFT, buff=0.45).shift(DOWN * 0.4)
a1 = Arrow(h_in.get_right(), gate.get_left() + UP * 0.35, buff=0.08, color=TEAL)
a2 = Arrow(x_in.get_right(), gate.get_left() + DOWN * 0.35, buff=0.08, color=TEAL)
diagram = VGroup(gate, gate_label, sigma, tanh_t, h_in, x_in, a1, a2)
diagram.move_to(ORIGIN + UP * 0.15)
self.play(Write(title), Create(gate), Write(gate_label), run_time=1.0)
self.play(FadeIn(h_in), FadeIn(x_in), GrowArrow(a1), GrowArrow(a2), run_time=1.0)
self.play(Write(sigma), Write(tanh_t), run_time=0.8)
self.play(FadeOut(h_in), FadeOut(x_in), FadeOut(a1), FadeOut(a2), run_time=0.4)
formula = Text("f(t) = σ(W · [h, x] + b)", font_size=28)
formula.to_edge(DOWN, buff=0.35)
self.play(Write(formula), run_time=1.0)
""".strip(),
    ),
    ManimTemplate(
        id="annotated_diagram",
        title="Diagram zone + reserved formula/caption zone",
        tags=("annotated", "diagram", "zones", "callout", "architecture"),
        devices=("annotated_diagram",),
        snippet="""
# Pattern: diagram centered, one annotation bottom — keep line length inside frame
title = Text("Cell State Path", font_size=36).to_edge(UP, buff=0.3)
rail = Line(LEFT * 3.5, RIGHT * 3.5, color=TEAL)
box = RoundedRectangle(width=2.2, height=1.3, corner_radius=0.12, color=ORANGE)
diag_lab = Text("Update", font_size=26).move_to(box.get_center())
diagram_group = VGroup(rail, box, diag_lab).move_to(ORIGIN + UP * 0.15)
note = Text("cell state flows left → right", font_size=28).to_edge(DOWN, buff=0.35)
self.play(Write(title), Create(rail), Create(box), Write(diag_lab), run_time=1.4)
self.play(FadeIn(note), run_time=0.7)
note2 = Text("gates scale what is kept", font_size=28).to_edge(DOWN, buff=0.35)
self.play(FadeOut(note), FadeIn(note2), run_time=0.7)
""".strip(),
    ),
]


def _extract_sample_snippet(source: str, *, max_chars: int = 2200) -> str:
    """Turn a sample Scene file into a prompt-sized pattern snippet."""
    # Drop vertical/pixel config overrides — codegen targets default 16:9 Scene.
    source = re.sub(
        r"^config\.(pixel_width|pixel_height|frame_width|frame_height)\s*=.*\n",
        "",
        source,
        flags=re.M,
    )
    source = re.sub(r"\bMathTex\s*\(", "Text(", source)
    source = re.sub(r"\bTex\s*\(", "Text(", source)
    # Prefer the construct body (+ helpers) over imports / class shell.
    m = re.search(
        r"class\s+\w+\s*\([^)]*Scene[^)]*\)\s*:\s*(.*)\Z",
        source,
        flags=re.S,
    )
    body = m.group(1).strip() if m else source.strip()
    # Dedent one level if class-indented.
    lines = body.splitlines()
    if lines and lines[0].startswith("    "):
        body = "\n".join(ln[4:] if ln.startswith("    ") else ln for ln in lines)
    body = body.strip()
    if len(body) > max_chars:
        body = body[: max_chars - 20].rstrip() + "\n# ... truncated ..."
    return body


@lru_cache(maxsize=1)
def _load_sample_templates() -> tuple[ManimTemplate, ...]:
    if not _SAMPLES_DIR.is_dir():
        return ()
    out: list[ManimTemplate] = []
    for path in sorted(_SAMPLES_DIR.glob("*.py")):
        meta = SAMPLE_META.get(path.name)
        if not meta:
            continue
        try:
            raw = path.read_text(encoding="utf-8")
        except OSError:
            continue
        # Skip samples that need optional physics plugins / SpaceScene.
        if re.search(r"^\s*from manim_physics\b|^\s*import manim_physics\b", raw, flags=re.M):
            continue
        if re.search(r"class\s+\w+\s*\(\s*SpaceScene\s*\)", raw):
            continue
        snippet = _extract_sample_snippet(raw)
        if len(snippet) < 40:
            continue
        out.append(
            ManimTemplate(
                id=f"sample_{path.stem.lower()}",
                title=str(meta["title"]),
                tags=tuple(meta["tags"]),
                devices=tuple(meta["devices"]),
                snippet=snippet,
            )
        )
    return tuple(out)


def all_templates() -> list[ManimTemplate]:
    """Built-in teaching patterns + samples/ catalog."""
    return [*TEMPLATES, *_load_sample_templates()]


def retrieve_templates(scene: SceneSection, *, limit: int = 3) -> list[ManimTemplate]:
    """Score templates by visual_device + style_tags + description keywords."""
    catalog = all_templates()
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
    for tpl in catalog:
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
        # Prefer real sample scenes slightly when tied on motion keywords.
        if tpl.id.startswith("sample_") and score >= 3:
            score += 1
        # Weak keyword-only hits create mismatched / meaningless scenes — skip them.
        if score >= 3:
            scored.append((score, tpl))

    scored.sort(key=lambda x: (-x[0], x[1].id))
    if scored:
        return [t for _, t in scored[:limit]]

    # Fallback: pick from narration cues when scorer finds nothing
    by_id = {t.id: t for t in catalog}

    def pick(*ids: str) -> list[ManimTemplate]:
        return [by_id[i] for i in ids if i in by_id][:limit]

    if any(w in blob for w in ("gate", "lstm", "sigmoid", "tanh", "forget", "cell state")):
        return pick("gate_mechanism", "annotated_diagram", "sample_indicatehighlight")
    if any(
        w in blob
        for w in ("neural", "neuron", "backprop", "forward pass", "hidden layer", "weights")
    ):
        return pick("neural_net_layers", "annotated_diagram", "sample_indicatehighlight")
    if any(w in blob for w in ("pipeline", "layer", "network", "transformer", "encoder", "boxes")):
        return pick("labeled_box_flow", "neural_net_layers", "sample_indicatehighlight")
    if any(w in blob for w in ("vector field", "electric", "field lines", "charge")):
        return pick("sample_arrowvectorfielddemo", "sample_vectorarrow")
    if any(w in blob for w in ("sine", "unit circle", "wave", "orbit")):
        return pick("sample_sinecurve", "unit_circle", "sample_pointmovingonshapes")
    if any(w in blob for w in ("trace", "trail", "path")):
        return pick("sample_pointwithtrace", "sample_pointmovingonshapes")
    if any(w in blob for w in ("angle", "theta", "geometry")):
        return pick("sample_movingangle", "sample_braceannotation")
    if any(w in blob for w in ("boolean", "venn", "intersection", "union", "set")):
        return pick("sample_booleanoperations", "before_after")
    if any(w in blob for w in ("grid", "lattice", "warp", "transform")):
        return pick("sample_gridtransform", "lattice_grid")
    if any(w in blob for w in ("graph", "plot", "curve", "parabola", "axes", "area")):
        return pick("axes_parabola", "sample_dynamicpolygon", "sample_vectorarrow")
    if any(w in blob for w in ("equation", "formula", "equals", "highlight")):
        return pick("equation_reveal", "sample_equationmoving")
    return pick("annotated_diagram", "sample_indicatehighlight")


def format_templates_for_prompt(templates: list[ManimTemplate]) -> str:
    if not templates:
        return "(no templates)"
    parts = []
    for t in templates:
        source = "sample file" if t.id.startswith("sample_") else "pattern"
        parts.append(
            f"### Template `{t.id}` — {t.title} ({source})\n"
            f"Adapt this motion/layout pattern; do not copy verbatim.\n"
            f"```python\n{t.snippet}\n```"
        )
    return "\n\n".join(parts)
