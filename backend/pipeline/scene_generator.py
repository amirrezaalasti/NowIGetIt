"""Generate and revise Manim Community Edition code for a single scene."""

from __future__ import annotations

import math
from typing import Optional

from backend.code_utils import clean_manim_code, lint_scene_code, validate_manim_code
from backend.languages import language_display_name, normalize_language
from backend.llm import OpenRouterClient
from backend.pipeline.beat_timing import (
    beat_timeline,
    format_beat_timeline,
    narration_is_beat_aligned,
)
from backend.pipeline.pedagogy import format_blueprint_for_codegen
from backend.pipeline.templates import format_templates_for_prompt, retrieve_templates
from backend.schemas import ScenePlan, SceneSection

MANIM_SYSTEM = """You are an expert Manim Community Edition developer (3Blue1Brown-caliber).
Generate a single complete Scene class for ONE educational video section.

QUALITY BAR:
- One visual metaphor that GROWS through real motion, not a static poster. Prefer
  fewer, larger objects, but every beat must ANIMATE something meaningful
  (Create/Write/GrowArrow/.animate/ValueTracker) — do not just FadeIn a still diagram
  and wait.
- Default composition: title top | diagram center (~70% of frame) | optional one
  caption/formula bottom. The FINAL hold must still show the key diagram + title.
- On-screen text is sparse; long explanations stay in narration only (it becomes
  subtitles). Every shape must map to the concept — no decorative filler.

THE ANIMATION MUST *BE* THE EXPLANATION (this is what separates a good scene from
a slideshow — read the beat timeline below and follow it literally):
- Each beat's animation plays WHILE its narration line is spoken. Animate exactly
  what that line describes, at that moment: when the voice says "the slope flattens",
  the tangent line visibly flattens on screen. Never illustrate a sentence the voice
  already left behind, and never show a thing several seconds before it is named.
- MOTION CARRIES MEANING. Direction, speed, and change encode the idea: descending =
  moving down, growth = scaling up, equality = two things converging, cause→effect =
  A moves, THEN B reacts (sequential plays, not one simultaneous blob).
- Show change, don't restate it. Prefer Transform/ReplacementTransform when one thing
  BECOMES another, ValueTracker + updaters when a quantity varies continuously, and
  MoveAlongPath when something travels. A number that changes should visibly count
  (DecimalNumber + updater), not cut between two static labels.
- DIRECT ATTENTION. Only one thing should be "loud" at a time: Indicate / Circumscribe
  / SurroundingRectangle the element under discussion, and dim what is now background
  (`.animate.set_opacity(0.35)`) instead of deleting it. Anything mentioned again
  later must stay on screen, dimmed — do not FadeOut and rebuild it.
- BUILD, DON'T RESET. The diagram accumulates across the scene: the anchor object
  from beat 1 is still there at the end, annotated. Each beat adds to or modifies
  what is already there. Wiping the frame between beats destroys the through-line.
- SPATIAL GRAMMAR IS STABLE. Once a thing owns a screen position, it keeps it for the
  whole scene; a label stays next_to its object. Never re-shuffle the layout mid-scene
  just to make room — plan the composition so everything has a home from the start.
- CONCRETE OVER ABSTRACT. Use real numbers, real axes ticks, a real worked case
  (x = 3, not "some value"). A learner should be able to pause on any frame and read
  what each element means from its label.

RUNTIME CONTRACT (injected before render — write code that COOPERATES with it):
A host post-processor wraps Text / MarkupText / Paragraph and patches Mobject.to_edge.
Treat these as the real APIs you are calling:
  - Text / MarkupText / Paragraph auto-recenter at ORIGIN after creation — you own
    sizing; do not use width=/height=, scale_to_fit_width, stretch_to_fit_*, or
    font=/disable_ligatures= (the host overrides both). Keep formulas COMPLETE: if a
    line is long, use a smaller font_size or an explicit two-line Text — never
    truncate words. Prefer FadeIn for on-screen text (Write looks cut off
    mid-animation). font_size ≥ 24 for body labels (titles 36–44).
  - to_edge(UP)/to_edge(DOWN) force X=0 after the move (no frame clamp/shrink) — do
    NOT fight this with shift(LEFT/RIGHT) afterward. For left/right-aligned labels
    use next_to()/move_to() instead.
  - Titles: Text(...).to_edge(UP, buff=0.3) + FadeIn. Captions: to_edge(DOWN,
    buff=0.35) or next_to(diagram, DOWN, buff=0.3) + FadeIn. Side labels:
    next_to(obj, LEFT/RIGHT, buff=0.25).

CRITICAL RULES (Manim Community / `manim`, NOT ManimGL):
1. Start with `from manim import *`. Use `Create` (not ShowCreation), `FadeIn`,
   `Write`, `GrowFromCenter`, `GrowArrow`, `.animate` for property animations.
2. ALWAYS use Text("...") for every label, title, and equation. Do NOT use MathTex,
   Tex, or TexText — LaTeX is not installed on the render host. Write math in plain
   text inside Text(), e.g. Text("E = mc²") or Text("loss = (y - ŷ)²").
3. Axes: use x_length/y_length (not width/height), e.g.
   Axes(x_range=[-3, 3, 1], y_range=[-1, 5, 1], x_length=7, y_length=5).
   Graphs: axes.plot(lambda x: x**2, x_range=[-2, 2], color=YELLOW) (not get_graph).
   Map coords with axes.c2p(x, y) / axes.i2gp(x, graph).
4. No hallucinated methods (.bounce, .jump, .shimmer, Wait() as a mobject).
5. Use plain `Scene` only (not MovingCameraScene/ThreeDScene); no
   add_fixed_in_frame_mobjects, AlwaysRedraw, TOP_RIGHT, or camera.frame
   (always_redraw is fine — prefer ValueTracker + updaters for continuous motion).
6. LAYOUT (cut-off / overlapping text is a hard failure): build local groups near
   ORIGIN with arrange/next_to, then group.move_to(ORIGIN) — avoid double absolute
   shifts or large LEFT/RIGHT*3 placement. Never overlap text with other
   text/arrows/diagram paths. At most one formula on screen at a time, wording
   COMPLETE (no chopped words). FadeOut previous labels/formulas before the next
   dense beat, but keep the core diagram visible through the final hold. Boxes must
   fully contain their labels.
7. TIMING: map every animation_beat to an explicit self.play(...) with real motion
   (not only wait). TOTAL construct time (every play/wait, excluding a final 0.5s
   hold) must match the target narration duration within ±0.5s — spend that time on
   NEW INFORMATION (reveal, label, move, or change something the narration is
   describing). If the time budget is larger than the beats need, add substantive
   steps (label the next part, walk a tracker further, transform the formula) rather
   than stretching run_time on nothing. End with exactly one self.wait(0.5) hold.
8. NEVER pad the runtime with filler: no scale/opacity "breathing" loops, no
   `.scale(1.0)` no-ops, no unlabeled objects flying in and out, no repeating the
   same self.play, no trailing self.wait() beyond the 0.5s hold, and no
   timing-arithmetic comments (e.g. "# total 6.78s"). If you have time left over,
   add a real labeled element instead.
9. LABEL DENSITY: every element the narration names gets a short Text label
   (≤3 words), revealed progressively. A scene longer than ~12s carrying only a
   title is a failure — aim for 2-4 short labels/captions besides the title.
10. Apply the provided palette colors (hex strings are fine) via Manim color args
    and config.background_color / self.camera.background_color.
11. When reference templates/samples are provided, adapt their motion + layout
    patterns to THIS scene — do not copy verbatim, and keep the RUNTIME CONTRACT
    (Text / to_edge) above.
12. Output ONLY valid Python code — no markdown, checklists, or commentary.
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
    # Budget: leave a short final hold; the rest is split across beats in
    # proportion to how long each beat's own narration takes to speak, so the
    # animation tracks the voiceover instead of dividing the clock evenly.
    beat_count = max(len(scene.animation_beats), 1)
    timings = beat_timeline(scene, max(0.5, duration - 0.5), language=language)
    timeline_block = format_beat_timeline(timings)
    alignment_note = (
        ""
        if narration_is_beat_aligned(scene)
        else (
            "\n(This scene's narration was authored as one block rather than split\n"
            " per beat, so the split above is an estimate — keep the ORDER and the\n"
            " total, and use your judgement on where each sentence lands.)\n"
        )
    )
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
    # The teaching plan this scene was staged from: what it must actually leave the
    # learner able to do, and the notation/visual grammar shared with every other
    # scene. Without it the coder re-invents an encoding per scene.
    teaching_block = format_blueprint_for_codegen(
        plan.blueprint, covers_steps=scene.covers_steps
    )
    teaching_section = (
        f"""
TEACHING PLAN — this scene is one rung of a single explanation. Honour these
encodings exactly: they are what makes the video one system instead of a set of
unrelated clips, and the learner is tracking them from scene to scene.

{teaching_block}
"""
        if teaching_block
        else ""
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
Camera notes: {scene.camera_notes}
{teaching_section}
BEAT TIMELINE — the voiceover audio is ALREADY RECORDED and fixed at {duration:.1f}s.
These timecodes are what the learner will actually hear. Work through the beats in
this order and spend each beat's budget inside its own window, so every animation is
on screen exactly while its line is spoken. A beat's budget may be one self.play or
several consecutive ones — any beat over ~5s MUST be broken into 2-3 successive plays
that each move the explanation a step further (reveal, annotate, advance the tracker),
because a single 8-second animation reads as nothing happening:

{timeline_block}
{alignment_note}
Full narration for reference (do NOT dump this on screen — it is spoken, and the
subtitles are burned in separately):
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

Numbers for this scene (the narration audio is already fixed at {duration:.1f}s — a
mismatch means the video freezes or runs silent against the voiceover):
- Total self.play(run_time=...) + self.wait(...) time (excluding the final 0.5s hold)
  must land within ±0.5s of {duration:.1f}s. Take each beat's run_time from the
  timeline above rather than dumping the difference into one wait.
- At least {min_plays} distinct self.play calls that each advance the explanation,
  and at least {min_labels} short Text labels besides the title. Total self.wait()
  time must stay under {max(1.0, 0.15 * duration):.1f}s including the final hold.
- Use the palette hex values above verbatim and render the recurring elements listed
  above so this scene visually matches the rest of the video.

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
    # Repair before handing off: shipping code we already know is invalid just
    # moves the failure into the render loop, which then spends its budget
    # re-reporting "render failed" instead of fixing anything.
    for _ in range(2):
        if ok:
            break
        code = revise_scene_code(
            client,
            code=code,
            scene=scene,
            revision_instructions=(
                f"The previous output was invalid ({err}). "
                "Rewrite a complete, syntactically valid Manim Community Scene "
                "with a Scene subclass whose construct() animates every beat "
                "with self.play(...)."
            ),
            target_duration_seconds=duration,
            surgical=False,
            language=lang,
        )
        ok, err = validate_manim_code(code)
    if not ok:
        return code
    return _fix_filler_motion(
        client,
        code=code,
        scene=scene,
        duration=duration,
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
    # Carry the beat/narration pairing into revisions too — otherwise a fix for
    # layout or timing quietly re-orders the animation away from the voiceover.
    timeline_block = format_beat_timeline(
        beat_timeline(scene, max(0.5, duration - 0.5), language=language)
    )
    user = f"""Fix this Manim Community scene. Output ONLY a complete valid Python file.

Scene title: {scene.title}
Visual goal: {scene.visual_description}
Visual device: {scene.visual_device or "(unspecified)"}
Output language: keep all on-screen Text in {lang_name}.

Beat timeline the animation must stay locked to (voiceover is fixed at {duration:.1f}s;
keep every beat in this order and inside its window):
{timeline_block}

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
    system = (
        MANIM_SYSTEM
        + "\nWhen revising, output the FULL Python file. Never output checklists or rule audits."
        + "\nSurgical priority: (1) pull off-frame content back with arrange + move_to(ORIGIN),"
        + " (2) fix overlaps by FadeOut prior labels / next_to,"
        + " (3) fix cutoffs with smaller font or two-line Text — never hide/truncate glyphs,"
        + " (4) remove only decorative filler shapes."
        + " Keep the core diagram visible in the final hold."
    )
    revised = clean_manim_code(
        client.chat(
            system=system,
            user=user,
            temperature=0.12,
            max_tokens=8192,
            model=client.manim_model,
        )
    )

    # A revision that answers with a fragment (a few self.play lines, no class or
    # construct) renders as a syntax error, and the caller's loop then reports
    # "render failed" and asks again — burning its whole budget without ever
    # telling the model what was actually wrong. Catch it here, once, for every
    # call site.
    ok, err = validate_manim_code(revised)
    if ok:
        return revised
    repaired = clean_manim_code(
        client.chat(
            system=system,
            user=(
                user
                + f"\n\nYour previous answer was not a usable file ({err}). You "
                "returned a fragment or invalid Python. Return the COMPLETE file "
                "again from the first import to the last line: the imports, the "
                "full `class ...(Scene):` and its entire `construct(self)` body "
                "with every self.play(...) call. Output nothing but Python."
            ),
            temperature=0.05,
            max_tokens=8192,
            model=client.manim_model,
        )
    )
    repaired_ok, _ = validate_manim_code(repaired)
    # Neither is valid — hand back the one the caller can still diff against.
    return repaired if repaired_ok else revised
