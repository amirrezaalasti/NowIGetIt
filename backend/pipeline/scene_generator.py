"""Generate and revise Manim Community Edition code for a single scene."""

from __future__ import annotations

from typing import Optional

from backend.code_utils import clean_manim_code, validate_manim_code
from backend.llm import OpenRouterClient
from backend.pipeline.templates import format_templates_for_prompt, retrieve_templates
from backend.schemas import ScenePlan, SceneSection

MANIM_SYSTEM = """You are an expert Manim Community Edition developer.
Generate a single complete Scene class for ONE educational video section.

CRITICAL RULES (Manim Community / `manim`, NOT ManimGL):
1. Start with: `from manim import *`
2. Use `Create` (not ShowCreation). Use `FadeIn`, `Write`, `GrowFromCenter`.
3. ALWAYS use `Text("...")` for ALL labels, titles, and mathematical equations.
   DO NOT use `MathTex`, `Tex`, or `TexText`. LaTeX/dvisvgm is not configured on the rendering host.
   For math expressions, write them in plain text inside `Text()`, e.g., `Text("E = mc²")` or `Text("dT/dt = k * ∇²T")`.
   Prefer `font_size` ≥ 28 for body labels (titles can be larger). Do NOT build words from
   per-letter Text() pieces, and do NOT stretch/skew Text with stretch_to_fit_width.
   Prefer FadeIn/Write on whole Text mobjects; avoid TransformMatchingShapes on long labels.
4. Axes: use `x_length` / `y_length` (not width/height). Example:
   Axes(x_range=[-3, 3, 1], y_range=[-1, 5, 1], x_length=7, y_length=5)
5. Graphs: `axes.plot(lambda x: x**2, x_range=[-2, 2], color=YELLOW)`
   (NOT axes.get_graph).
6. Map coords with `axes.c2p(x, y)` / `axes.i2gp(x, graph)`.
7. No hallucinated methods (.bounce, .jump, .shimmer, Wait() as a mobject).
8. Use `.animate` for property animations.
9. Fit content on screen; titles with `to_edge(UP)`.
10. Keep the scene simple and complete.
11. Use plain `Scene` only — NOT MovingCameraScene / ThreeDScene.
12. Do NOT use add_fixed_in_frame_mobjects, AlwaysRedraw, TOP_RIGHT, or camera.frame.
    `always_redraw` is OK. Prefer ValueTracker + updaters for continuous motion.
13. TIMING (critical): Map every animation_beat to an explicit run_time / wait so the
    TOTAL construct time (sum of play/wait, excluding a final 0.4s hold) matches the
    target narration duration within ±0.5s. Prefer self.wait() between beats over
    dumping all motion at once. End with a short final hold: self.wait(0.4).
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
    templates = retrieve_templates(scene, limit=2)
    template_block = format_templates_for_prompt(templates)
    duration = target_duration_seconds or scene.duration_seconds
    # Budget: leave a tiny final hold; distribute the rest across beats
    beat_count = max(len(scene.animation_beats), 1)
    per_beat = max(0.6, (duration - 0.4) / beat_count)

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

Return one complete runnable Manim Community Scene file.
"""
    raw = client.chat(
        system=MANIM_SYSTEM,
        user=user,
        temperature=0.3,
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
    )


def revise_scene_code(
    client: OpenRouterClient,
    *,
    code: str,
    scene: SceneSection,
    revision_instructions: str,
    render_error: str = "",
    target_duration_seconds: Optional[float] = None,
) -> str:
    duration = target_duration_seconds or scene.duration_seconds
    user = f"""Fix this Manim Community scene. Output ONLY a complete valid Python file.

Scene title: {scene.title}
Visual goal: {scene.visual_description}
Visual device: {scene.visual_device or "(unspecified)"}
Beats:
{chr(10).join(f"- {b}" for b in scene.animation_beats)}
Target narration duration: {duration:.1f}s (keep total play+wait matched)

Revision instructions:
{revision_instructions}

Render / runtime error (if any):
{render_error or "(none)"}

Current code (may be broken — rewrite fully if needed):
```python
{code}
```
"""
    raw = client.chat(
        system=MANIM_SYSTEM
        + "\nWhen revising, rewrite the FULL file. Never output checklists or rule audits.",
        user=user,
        temperature=0.15,
        max_tokens=8192,
    )
    return clean_manim_code(raw)
