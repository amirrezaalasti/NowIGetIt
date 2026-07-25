"""Generate and revise Manim Community Edition code for a single scene."""

from __future__ import annotations

from backend.code_utils import clean_manim_code, validate_manim_code
from backend.llm import OpenRouterClient
from backend.schemas import ScenePlan, SceneSection

MANIM_SYSTEM = """You are an expert Manim Community Edition developer.
Generate a single complete Scene class for ONE educational video section.

CRITICAL RULES (Manim Community / `manim`, NOT ManimGL):
1. Start with: `from manim import *`
2. Use `Create` (not ShowCreation). Use `FadeIn`, `Write`, `GrowFromCenter`.
3. ALWAYS use `Text("...")` for ALL labels, titles, and mathematical equations.
   DO NOT use `MathTex`, `Tex`, or `TexText`. LaTeX/dvisvgm is not configured on the rendering host.
   For math expressions, write them in plain text inside `Text()`, e.g., `Text("E = mc²")` or `Text("dT/dt = k * ∇²T")`.
4. Axes: use `x_length` / `y_length` (not width/height). Example:
   Axes(x_range=[-3, 3, 1], y_range=[-1, 5, 1], x_length=7, y_length=5)
5. Graphs: `axes.plot(lambda x: x**2, x_range=[-2, 2], color=YELLOW)`
   (NOT axes.get_graph).
6. Map coords with `axes.c2p(x, y)` / `axes.i2gp(x, graph)`.
7. No hallucinated methods (.bounce, .jump, .shimmer, Wait() as a mobject).
8. Use `.animate` for property animations.
9. Fit content on screen; titles with `to_edge(UP)`.
10. Keep the scene simple and complete. Always end with `self.wait(2)` (final hold).
11. Use plain `Scene` only — NOT MovingCameraScene / ThreeDScene.
12. Do NOT use add_fixed_in_frame_mobjects, AlwaysRedraw, TOP_RIGHT, or camera.frame.
13. Output ONLY valid Python code — no markdown, checklists, or commentary.
"""


def generate_scene_code(
    client: OpenRouterClient,
    *,
    plan: ScenePlan,
    scene: SceneSection,
    previous_context: str = "",
) -> str:
    user = f"""Video title: {plan.title}
Concept: {plan.concept_summary}
Style: {plan.style_notes}

Scene id: {scene.id}
Scene title: {scene.title}
Visual description: {scene.visual_description}
Animation beats:
{chr(10).join(f"- {b}" for b in scene.animation_beats)}
Duration seconds: {scene.duration_seconds}
Camera notes: {scene.camera_notes}
Narration (pacing only; do not dump full VO on screen):
{scene.narration}

Previous scenes context:
{previous_context or "(first scene)"}

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
    )


def revise_scene_code(
    client: OpenRouterClient,
    *,
    code: str,
    scene: SceneSection,
    revision_instructions: str,
    render_error: str = "",
) -> str:
    user = f"""Fix this Manim Community scene. Output ONLY a complete valid Python file.

Scene title: {scene.title}
Visual goal: {scene.visual_description}
Beats:
{chr(10).join(f"- {b}" for b in scene.animation_beats)}

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
