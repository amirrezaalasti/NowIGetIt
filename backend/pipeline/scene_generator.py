"""Generate and revise Manim Community Edition code for a single scene."""

from __future__ import annotations

import math
from typing import Optional

from backend.code_utils import clean_manim_code, lint_scene_code, validate_manim_code
from backend.languages import language_display_name, normalize_language
from backend.llm import OpenRouterClient
from backend.pipeline.templates import format_templates_for_prompt, retrieve_templates
from backend.schemas import ScenePlan, SceneSection

MANIM_SYSTEM = """You are an expert Manim Community Edition developer (3Blue1Brown-caliber).
Generate a single complete Scene class for ONE educational video section.

QUALITY BAR (first pass must already look finished):
- One clear visual metaphor that GROWS through real motion — not a static poster.
- Default composition: title top | diagram center (~70% of frame) | optional ONE caption/formula bottom.
- The FINAL hold must still show the key diagram + title. Never FadeOut everything before the end.
- Prefer fewer, larger objects over many tiny ones — but every beat must ANIMATE something
  meaningful (Create/Write/GrowArrow/.animate/ValueTracker). Do NOT only FadeIn a still diagram
  and wait; learners should see the idea build.
- On-screen text is sparse; long explanations stay in narration only (subtitles handle VO).
- Every shape must teach the concept. No decorative Circle↔Square morphs or random filler.

RUNTIME CONTRACT (injected before render — write code that COOPERATES with it):
A host post-processor wraps Text / MarkupText / Paragraph and patches Mobject.to_edge.
Treat these as the real APIs you are calling:

  Text / MarkupText / Paragraph
  - Born centered at ORIGIN (auto-recentered after create). No host width-cap,
    soft-wrap, font-size upscaling, or scale_to_fit_width — you own sizing.
  - Default font is Noto Sans (host-enforced with Liberation/DejaVu fallback).
    Do not set font= or disable_ligatures= — the host overrides both.
  - Do NOT use width=/height= on Text, stretch_to_fit_*, scale_to_fit_width,
    per-letter Text pieces, NBSP padding, or `_ManimText` (bypasses are rewritten).
  - Keep formulas COMPLETE. If a line is long: smaller font_size or an explicit
    two-line Text("line one\\nline two") — never truncate words.
  - Prefer FadeIn for on-screen text (Write looks cut off mid-animation).
  - Prefer font_size ≥ 24 for body labels (titles 36–44). The host re-renders
    small text at a higher Pango size then scales it down for even letter spacing.

  to_edge(UP) / to_edge(DOWN)
  - After the edge move, X is forced to 0 (horizontally centered). No frame clamp
    and no shrinking. Do NOT fight this with shift(LEFT/RIGHT) after to_edge(UP/DOWN).
  - For left/right-aligned labels use next_to(...) / move_to(...), not to_edge(UP)+shift.

  Layout intent
  - Titles: Text(...).to_edge(UP, buff=0.3) + FadeIn (not Write — Write looks cut off
    mid-animation). Prefer readable full phrases over cramped micro-titles.
  - Never hand-place a title at hardcoded corner coordinates (e.g.
    move_to(UP*3.5 + LEFT*5)) to dodge the to_edge centering: the frame is only
    ~14.2 x 8 units, so that pushes long titles off-screen. A horizontally centered
    title at the top is correct — accept it.
  - Captions: to_edge(DOWN, buff=0.35) or next_to(diagram, DOWN, buff=0.3) + FadeIn.
  - Side labels: next_to(obj, LEFT/RIGHT, buff=0.25).
  - Keep large Sphere / dense diagrams from covering the title band.

CRITICAL RULES (Manim Community / `manim`, NOT ManimGL):
1. Start with: `from manim import *`
2. Use `Create` (not ShowCreation). Use `FadeIn`, `Write`, `GrowFromCenter`, `GrowArrow`.
3. ALWAYS use `Text("...")` for ALL labels, titles, and mathematical equations.
   DO NOT use `MathTex`, `Tex`, or `TexText`. LaTeX/dvisvgm is not configured on the rendering host.
   For math expressions, write them in plain text inside `Text()`, e.g., `Text("E = mc²")` or `Text("loss = (y - ŷ)²")`.
   Prefer `font_size` ≥ 24 for body labels (titles 36–44). Prefer FadeIn on whole
   Text mobjects; avoid TransformMatchingShapes on long labels.
4. Axes: use `x_length` / `y_length` (not width/height). Example:
   Axes(x_range=[-3, 3, 1], y_range=[-1, 5, 1], x_length=7, y_length=5)
5. Graphs: `axes.plot(lambda x: x**2, x_range=[-2, 2], color=YELLOW)`
   (NOT axes.get_graph).
6. Map coords with `axes.c2p(x, y)` / `axes.i2gp(x, graph)`.
7. No hallucinated methods (.bounce, .jump, .shimmer, Wait() as a mobject).
8. Use `.animate` for property animations.
9. LAYOUT (critical — cut-off / overlapping text is a hard failure):
   - Build local groups near ORIGIN with arrange/next_to, THEN center with
     `group.move_to(ORIGIN)` (or ORIGIN + DOWN*0.2). Avoid double absolute shifts.
   - Prefer VGroup(...).arrange(...) / next_to(...) over large LEFT/RIGHT*3 placement.
   - Never place text on top of other text, arrows, or busy diagram paths.
   - At most ONE formula on screen at a time; keep wording COMPLETE (no chopped words).
   - Short UI labels when possible. Always use `Text(...)`.
   - Progressive reveal: FadeOut previous labels/formulas before the next dense beat,
     but keep the core diagram visible through the final hold.
   - Do NOT call scale_to_fit_width / stretch_to_fit_* on Text. Resize diagrams with
     arrange/smaller counts first; never crop letters.
   - Boxes must fully contain their labels.
10. VISUAL RECIPES (pick the closest; motion-first, still readable):
    - Neural net / layers: 2–3 columns of Circles (≤4 nodes/layer) + thin Lines;
      animate layer-by-layer, then pulse a path. No weight matrices.
    - Forward / backward pass: animate colored arrows / highlight on the SAME diagram;
      update one short caption (FadeOut old → FadeIn new).
    - Loss / cost / error: Axes + curve drawn with Create; moving Dot via ValueTracker;
      optional tangent or error brace that grows.
    - Equation scenes: Write a complete formula; transform/replace via FadeOut/FadeIn
      with a matching diagram change in the same beat when possible.
    - Flows / processes: GrowArrow, LaggedStart Create, Indicate, .animate.shift/scale/set_color.
    - Morphs: only when the morph teaches (wrong fit → better fit). Never decorative
      Circle→Square swaps.
11. Use plain `Scene` only — NOT MovingCameraScene / ThreeDScene.
12. Do NOT use add_fixed_in_frame_mobjects, AlwaysRedraw, TOP_RIGHT, or camera.frame.
    `always_redraw` is OK. Prefer ValueTracker + updaters for continuous motion.
13. TIMING + MOTION (critical): Map EVERY animation_beat to an explicit self.play(...)
    with real motion (not only wait). TOTAL construct time (sum of play/wait, excluding
    a final 0.5s hold) must match the target narration duration within ±0.5s.
    Spend that time on NEW INFORMATION: every self.play must reveal, label, move or
    change something the narration is describing at that moment. If the time budget is
    larger than your beats seem to need, break the beats into smaller SUBSTANTIVE steps
    (label the next part, annotate the next arrow, walk a tracker further along the
    curve, transform the formula) and give meaningful animations longer run_time.
    End with exactly one self.wait(0.5) on the teaching frame.
14. BANNED TIME-FILLERS — a scene doing any of these is a FAILURE even if it renders
    and matches the duration:
    - "Breathing" loops: obj.animate.scale(1.1) then back down, or set_opacity
      oscillating 0.4 → 0.6 → 0.4, purely to consume seconds.
    - `.scale(1.0)` — a NO-OP that does not undo an earlier scale. Never write it.
      (If an object must return to its size, use scale(1/1.1) — but prefer not to.)
    - Unexplained objects flying in and back out (dots, particles, arrows) with no label
      and no role in the explanation.
    - Repeating the same self.play to burn budget, or re-animating an object that has
      already made its point.
    - A trailing self.wait(N) beyond the single 0.5s hold to "reach" the target time.
    - Timing arithmetic in comments (`# total 6.78s`, `# adjust to reach 40.7s total`,
      `# Total runtime check`). Never write runtime math in comments.
15. LABEL DENSITY: every element the narration names gets a short Text label (≤3 words)
    when it appears, revealed progressively. A scene longer than ~12s carrying only a
    title is a failure — aim for 2-4 short labels/captions besides the title.
16. AESTHETICS & CONTEXT (critical): Deeply understand the context and semantics of the material.
    Use beautiful, harmonious pastel color combinations (e.g. "#FFB3BA", "#FFDFBA", "#FFFFBA", "#BAFFC9", "#BAE1FF")
    for elements to create a visually pleasing, premium aesthetic. Avoid generic harsh colors.
    Animate objects better: use smooth, organic, and engaging animations (e.g., DrawBorderThenFill,
    LaggedStart, smooth interpolations) instead of flat or abrupt transitions, ensuring the motion
    perfectly reflects the underlying concept being taught. Apply these pastel palettes and set
    background with config.background_color or self.camera.background_color.
17. When reference templates/samples are provided, adapt their motion + layout patterns
    to THIS scene — do not copy verbatim, and keep the RUNTIME CONTRACT (Text / to_edge).
18. Output ONLY valid Python code — no markdown, checklists, or commentary.
"""


def generate_scene_code(
    client: OpenRouterClient,
    *,
    plan: ScenePlan,
    scene: SceneSection,
    previous_context: str = "",
    next_context: str = "",
    target_duration_seconds: Optional[float] = None,
    creative_direction: str = "",
    language: str = "en",
) -> str:
    templates = retrieve_templates(scene, limit=3)
    template_block = format_templates_for_prompt(templates)
    duration = target_duration_seconds or scene.duration_seconds
    # Budget: leave a short final hold; distribute the rest across beats
    beat_count = max(len(scene.animation_beats), 1)
    per_beat = max(0.6, (duration - 0.5) / beat_count)
    # Density floor: long scenes need many *substantive* steps, otherwise the
    # model stretches a few animations and pads the rest with decorative motion.
    min_plays = max(beat_count, math.ceil(duration / 4.0))
    min_labels = 2 if duration < 20 else 3
    lang = normalize_language(language)
    lang_name = language_display_name(lang)

    palette = plan.palette or {}
    palette_lines = (
        "\n".join(f"  - {k}: {v}" for k, v in palette.items())
        if palette
        else "  (use style_notes colors)"
    )
    recurring = list(plan.recurring_elements or [])
    recurring_block = (
        "\n".join(f"  - {r}" for r in recurring)
        if recurring
        else "  (none specified — still reuse the palette + visual_identity consistently)"
    )

    user = f"""Video title: {plan.title}
Concept: {plan.concept_summary}
Style: {plan.style_notes}
Visual identity: {plan.visual_identity or "(none)"}
Palette:
{palette_lines}
Recurring visual elements (CRITICAL — reuse these in THIS scene with the exact
SAME shape, color, label, and screen role they have elsewhere in the video, so
every scene visually reads as part of one continuous video, not a disconnected
clip. Adapt only their position if the layout requires it):
{recurring_block}
Output language: {lang_name} — ALL on-screen Text(...) titles/labels/captions/formulas
must be written in this language (ASCII math symbols OK).

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

What comes right after this scene (context only — do NOT preview or draw its content,
just make sure THIS scene's final beat feels like a natural hand-off rather than a
random stop, matching the tone of the narration's closing line):
{next_context or "(final scene)"}

Reference Manim patterns (adapt to this scene):
{template_block}

Composition contract:
- VISUAL CONSISTENCY IS NON-NEGOTIABLE: use the palette hex values above verbatim (not
  approximations) for background/accent/text/highlight, keep title placement/typography
  the same style as other scenes (top, FadeIn, similar font_size), and render every
  recurring element listed above so a viewer scrubbing between scenes sees the same
  visual language, not a new color scheme or layout convention each time.
- Build a clean teaching frame that MOVES: each animation_beat → at least one self.play
  with Create/Write/GrowArrow/Indicate/.animate/ValueTracker (not only FadeIn + wait).
- Center the main diagram; keep every label fully inside the frame (no clipped letters).
- Aim for a lively but readable peak (~10–16 mobjects). Prefer progressive reveal over
  a single static image.
- If crowded, simplify labels — never delete formula terms or strip the motion that
  teaches the idea.
- Every object on screen must map to the concept (no filler shapes).
- TIMING IS NON-NEGOTIABLE: the audio narration is already fixed at {duration:.1f}s.
  Sum every self.play(run_time=...) and self.wait(...) call (excluding the final 0.5s
  hold) and make sure it lands within ±0.5s of {duration:.1f}s — a mismatch here means
  the video will freeze or run silent against the voiceover. Distribute the budget
  roughly evenly across the beats above (~{per_beat:.1f}s each); do not dump the whole
  budget into one giant self.wait().
- DENSITY FLOOR for this {duration:.1f}s scene: at least {min_plays} distinct self.play
  calls, each advancing the explanation (a new element, a new label, a real state
  change), and at least {min_labels} short Text labels besides the title. Total
  self.wait() time must stay under {max(1.0, 0.15 * duration):.1f}s including the final
  0.5s hold. Reaching the duration with pulse/opacity loops, objects flying in and out,
  or a padding wait at the end counts as a failed scene — if you run out of things to
  show, reveal more of the narration's named parts as labeled annotations instead.

Return one complete runnable Manim Community Scene file.
"""
    raw = client.chat(
        system=MANIM_SYSTEM,
        user=user,
        temperature=0.25,
        max_tokens=8192,
        model=client.manim_model,
    )
    code = clean_manim_code(raw)
    ok, err = validate_manim_code(code)
    if ok:
        return _fix_filler_motion(
            client,
            code=code,
            scene=scene,
            duration=duration,
            language=lang,
        )
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
        language=lang,
    )


def _fix_filler_motion(
    client: OpenRouterClient,
    *,
    code: str,
    scene: SceneSection,
    duration: float,
    language: str,
) -> str:
    """One cheap pre-render pass against time-filling, information-free scenes.

    Static lint catches what the duration check cannot: a clip that runs the
    right length but spends it on pulsing shapes, no-op scale reverts, unlabeled
    objects and padding waits. Only keep the rewrite if it is valid AND actually
    fixes more than it breaks.
    """
    issues = lint_scene_code(code, target_duration=duration)
    if not issues:
        return code
    revised = revise_scene_code(
        client,
        code=code,
        scene=scene,
        revision_instructions=(
            "This scene fills its runtime with motion that teaches nothing. Keep the "
            "visual idea, layout and total duration, but replace the filler with "
            "substantive steps (new labeled elements, annotations of the parts the "
            "narration names, tracker/transform motion that shows change). Fix:\n- "
            + "\n- ".join(issues)
        ),
        target_duration_seconds=duration,
        surgical=True,
        language=language,
    )
    ok, _ = validate_manim_code(revised)
    if not ok:
        return code
    if len(lint_scene_code(revised, target_duration=duration)) >= len(issues):
        return code
    return revised


def revise_scene_code(
    client: OpenRouterClient,
    *,
    code: str,
    scene: SceneSection,
    revision_instructions: str,
    render_error: str = "",
    target_duration_seconds: Optional[float] = None,
    surgical: bool = True,
    language: str = "en",
) -> str:
    duration = target_duration_seconds or scene.duration_seconds
    lang_name = language_display_name(language)
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
Output language: keep all on-screen Text in {lang_name}.

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
        + "\nSurgical priority: (1) pull off-frame content back with arrange + move_to(ORIGIN),"
        + " (2) fix overlaps by FadeOut prior labels / next_to,"
        + " (3) fix cutoffs with smaller font or two-line Text — never hide/truncate glyphs,"
        + " (4) remove only decorative filler shapes."
        + " Keep the core diagram visible in the final hold.",
        user=user,
        temperature=0.12,
        max_tokens=8192,
        model=client.manim_model,
    )
    return clean_manim_code(raw)
