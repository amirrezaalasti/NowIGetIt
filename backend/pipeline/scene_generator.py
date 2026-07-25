"""Generate and revise Manim Community Edition code for a single scene."""

from __future__ import annotations

from typing import Optional

from backend.code_utils import clean_manim_code, validate_manim_code
from backend.llm import OpenRouterClient
from backend.pipeline.templates import format_templates_for_prompt, retrieve_templates
from backend.schemas import ScenePlan, SceneSection

MANIM_SYSTEM = """You are an expert Manim Community Edition developer (3Blue1Brown-caliber).
Generate a single complete Scene class for ONE educational video section.

QUALITY BAR (first pass must already look finished):
- One clear visual metaphor that grows over time — not a wall of labels.
- Default composition: title top | diagram center (~70% of frame) | optional ONE caption bottom.
- The FINAL hold must still show the key diagram + title. Never FadeOut everything before the end.
- Prefer fewer, larger objects over many tiny ones. White space is good.
- On-screen text is sparse; long explanations stay in narration only.

CRITICAL RULES (Manim Community / `manim`, NOT ManimGL):
1. Start with: `from manim import *`
2. Use `Create` (not ShowCreation). Use `FadeIn`, `Write`, `GrowFromCenter`, `GrowArrow`.
3. ALWAYS use `Text("...")` for ALL labels, titles, and mathematical equations.
   DO NOT use `MathTex`, `Tex`, or `TexText`. LaTeX/dvisvgm is not configured on the rendering host.
   For math expressions, write them in plain text inside `Text()`, e.g., `Text("E = mc²")` or `Text("loss = (y - ŷ)²")`.
   Prefer `font_size` ≥ 28 for body labels (titles 36–44). Do NOT build words from
   per-letter Text() pieces, and do NOT stretch/skew Text with stretch_to_fit_width.
   Prefer FadeIn/Write on whole Text mobjects; avoid TransformMatchingShapes on long labels.
   Keep formula Text short (≤ 36 chars). Prefer compact forms over full expansions.
4. Axes: use `x_length` / `y_length` (not width/height). Example:
   Axes(x_range=[-3, 3, 1], y_range=[-1, 5, 1], x_length=7, y_length=5)
5. Graphs: `axes.plot(lambda x: x**2, x_range=[-2, 2], color=YELLOW)`
   (NOT axes.get_graph).
6. Map coords with `axes.c2p(x, y)` / `axes.i2gp(x, graph)`.
7. No hallucinated methods (.bounce, .jump, .shimmer, Wait() as a mobject).
8. Use `.animate` for property animations.
9. LAYOUT (critical — overlapping/cut-off text is a hard failure):
   - Titles: `to_edge(UP, buff=0.35)`. Keep ≥0.35 margin from all frame edges.
   - Never place text on top of other text, arrows, or busy diagram paths.
   - Use VGroup(...).arrange(...) / next_to(..., buff≥0.35) — avoid stacked absolute coords.
   - At most ONE formula on screen at a time; put it in a reserved bottom zone
     with buff≥0.5 from the diagram.
   - Short labels only (≤3 words, or compact math ≤36 chars). Never dump narration.
   - Progressive reveal: FadeOut previous labels/formulas before the next dense beat,
     but keep the core diagram visible through the final hold.
   - After building a VGroup, if width > 11 or height > 6.0, scale_to_fit_width(11) / scale down.
   - Boxes must fully contain their labels (font_size 22–28 inside boxes; never clip).
10. VISUAL RECIPES (pick the closest; stay sparse):
    - Neural net / layers: 2–3 columns of Circles (≤4 nodes/layer) + thin Lines between
      adjacent layers; OR 3 short-labeled RoundedRectangles in a row. No weight matrices.
    - Forward / backward pass: animate colored arrows or highlight path on the SAME diagram;
      one short caption that updates (FadeOut old → FadeIn new).
    - Loss / cost / error: one Axes + one curve + optional one Dot marker; caption bottom.
    - Equation scenes: at most one Text formula visible; replace via FadeOut/FadeIn.
11. Use plain `Scene` only — NOT MovingCameraScene / ThreeDScene.
12. Do NOT use add_fixed_in_frame_mobjects, AlwaysRedraw, TOP_RIGHT, or camera.frame.
    `always_redraw` is OK. Prefer ValueTracker + updaters for continuous motion.
13. TIMING (critical): Map every animation_beat to an explicit run_time / wait so the
    TOTAL construct time (sum of play/wait, excluding a final 0.5s hold) matches the
    target narration duration within ±0.5s. Prefer self.wait() between beats over
    dumping all motion at once. End with self.wait(0.5) while the teaching frame is still up.
14. Apply the provided palette colors via Manim color constants or hex strings
    (e.g. "#e8a87c"). Set background with config.background_color or self.camera.background_color.
15. When reference templates are provided, adapt their patterns — do not copy blindly.
16. Output ONLY valid Python code — no markdown, checklists, or commentary.
"""


def generate_scene_code(
    client: OpenRouterClient,
    *,
    plan: ScenePlan,
    scene: SceneSection,
    previous_context: str = "",
    target_duration_seconds: Optional[float] = None,
    creative_direction: str = "",
) -> str:
    templates = retrieve_templates(scene, limit=3)
    template_block = format_templates_for_prompt(templates)
    duration = target_duration_seconds or scene.duration_seconds
    # Budget: leave a short final hold; distribute the rest across beats
    beat_count = max(len(scene.animation_beats), 1)
    per_beat = max(0.6, (duration - 0.5) / beat_count)

    palette = plan.palette or {}
    palette_lines = (
        "\n".join(f"  - {k}: {v}" for k, v in palette.items())
        if palette
        else "  (use style_notes colors)"
    )

    user = f"""Video title: {plan.title}
Concept: {plan.concept_summary}
Style: {plan.style_notes}
Visual identity: {plan.visual_identity or "(none)"}
Palette:
{palette_lines}

Scene id: {scene.id}
Scene title: {scene.title}
Visual device: {scene.visual_device or "(unspecified)"}
Style tags: {", ".join(scene.style_tags) or "(none)"}
Visual description: {scene.visual_description}
Animation beats (map each to run_time ≈ {per_beat:.1f}s):
{chr(10).join(f"- {b}" for b in scene.animation_beats)}
Target narration duration: {duration:.1f} seconds  ← TOTAL play+wait must match this
Camera notes: {scene.camera_notes}
Narration (pacing only; do not dump full VO on screen):
{scene.narration}

Creative direction:
{creative_direction or "(none)"}

Previous scenes context:
{previous_context or "(first scene)"}

Reference Manim patterns (adapt to this scene):
{template_block}

Composition contract:
- Build a clean first-pass teaching frame (title + core diagram still visible at the end).
- Max ~8–12 animated mobjects on screen at peak; prefer scale and spacing over density.
- If the brief sounds crowded, simplify: keep the single most important visual idea.

Return one complete runnable Manim Community Scene file.
"""
    raw = client.chat(
        system=MANIM_SYSTEM,
        user=user,
        temperature=0.25,
        max_tokens=8192,
    )
    code = clean_manim_code(raw)
    ok, err = validate_manim_code(code)
    if ok:
        return code
    return revise_scene_code(
        client,
        code=code,
        scene=scene,
        revision_instructions=(
            f"The previous output was invalid ({err}). "
            "Rewrite a complete, syntactically valid Manim Community Scene."
        ),
        target_duration_seconds=duration,
        surgical=False,
    )


def revise_scene_code(
    client: OpenRouterClient,
    *,
    code: str,
    scene: SceneSection,
    revision_instructions: str,
    render_error: str = "",
    target_duration_seconds: Optional[float] = None,
    surgical: bool = True,
) -> str:
    duration = target_duration_seconds or scene.duration_seconds
    mode_note = (
        "Make the SMALLEST edits that fix the listed issues. Preserve the visual idea, "
        "palette, and timing structure. Do NOT redesign from scratch unless the code "
        "cannot render or misses the core diagram entirely."
        if surgical and not render_error
        else "Rewrite a complete valid file that renders and teaches the scene."
    )
    user = f"""Fix this Manim Community scene. Output ONLY a complete valid Python file.

Scene title: {scene.title}
Visual goal: {scene.visual_description}
Visual device: {scene.visual_device or "(unspecified)"}
Beats:
{chr(10).join(f"- {b}" for b in scene.animation_beats)}
Target narration duration: {duration:.1f}s (keep total play+wait matched)

Revision mode:
{mode_note}

Revision instructions:
{revision_instructions}

Render / runtime error (if any):
{render_error or "(none)"}

Current code (base your edits on this — keep what already works):
```python
{code}
```
"""
    raw = client.chat(
        system=MANIM_SYSTEM
        + "\nWhen revising, output the FULL Python file. Never output checklists or rule audits."
        + "\nSurgical priority: fix listed overlaps/clipping/cutoffs first; shorten labels;"
        + " FadeOut prior labels before new dense beats; keep one formula zone;"
        + " keep the core diagram visible in the final hold.",
        user=user,
        temperature=0.12,
        max_tokens=8192,
    )
    return clean_manim_code(raw)
