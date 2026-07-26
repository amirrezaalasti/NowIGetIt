"""Code-first review when Manim isn't rendered; image VLM only for real frames."""

from __future__ import annotations

import re
from pathlib import Path

from backend.llm import OpenRouterClient
from backend.schemas import SceneSection, VlmReview

_FORBIDDEN_LATEX_RE = re.compile(
    r"\b(mathtex|textext|latex)\b|\btex\s*\(",
    re.IGNORECASE,
)

_JSON_SHAPE = """
Return ONLY a complete JSON object (no markdown). Keep strings short:
- issues: max 4 items, each ≤ 140 chars
- revision_instructions: ≤ 400 chars, concrete spatial fixes only
{
  "approved": boolean,
  "issues": [string],
  "revision_instructions": string,
  "confidence": number,
  "clarity_score": number,
  "misconception_risk": number
}
"""

CODE_REVIEW_SYSTEM = f"""You are a Manim Community Edition code reviewer for educational animations.
Manim was NOT rendered — you only see Python code + the intended scene brief.
Do NOT complain about missing pixels, empty frames, or inspection overlays.
Do NOT ask to "render the frame" or "display graphical elements in the image".

Approve if the code looks complete and would plausibly produce the intended scene.
Reject for real code problems OR obvious layout disasters in the code:
- syntax errors / truncated code / non-Python commentary mixed into the file
- missing Scene class or construct()
- clear API misuse that would crash (MathTex, Wait(), hallucinated methods)
- scene clearly misses core visual beats from the brief
- dangerous/incomplete expressions cut mid-line
- many absolute overlapping Text/Arrow placements with no FadeOut between beats
- dumping long narration/bitstreams onto the frame

CRITICAL CONSTRAINTS for revision_instructions:
- NEVER suggest MathTex, Tex, TexText, or LaTeX — the render host has no LaTeX.
- Use plain Text("...") only. Write subscripts as ASCII: "C(t)", "h(t-1)", "x_t" → "x(t)".
- Prefer repositioning with next_to / to_edge (small buff ~0.25–0.3) / FadeOut.
- RUNTIME: Text is auto-recentered; to_edge(UP/DOWN) forces X=0 only (no width clamp).
  Do NOT suggest to_edge(UP)+shift(LEFT/RIGHT), scale_to_fit_width, stretch_to_fit_*,
  Text width=/height=, NBSP padding, or `_ManimText`.
- NEVER tell the model to truncate words/formula terms or invent large margins.
- Shorten only redundant UI labels (e.g. "Forget Gate Mechanism" → "Forget Gate"),
  not mathematical content. Remove decorative filler shapes that do not teach.

Also score teaching quality (0–1):
- clarity_score: how clearly the code would teach the concept
  (penalize clutter AND meaningless decorative shapes; do not penalize complete formulas)
- misconception_risk: how likely a learner is to walk away confused

{_JSON_SHAPE}
"""

IMAGE_VLM_SYSTEM = f"""You are a visual QA reviewer for educational Manim animations.
One or more REAL rendered preview frames are attached (not text storyboards).
When multiple images are present: earlier = mid-scene, last = near end.
Compare frames + code against the intended scene description.

Approve when the frames clearly teach the intended concept AND are readable.
REJECT (approved=false) when ANY of these are true:
- text/labels/formulas overlap each other or sit on top of arrows/paths
- labels/formulas are cut off at box or frame edges (missing letters, truncated equations)
- main diagram / panels shifted off-center so content exits the frame
- more than one dense formula fights with a busy diagram
- illegible text, broken letter spacing, empty frame, off-brief
- clutter that would confuse a learner in a pause-frame screenshot
- decorative filler shapes (random morphs, unexplained geometry) that obscure the idea

Do NOT reject for:
- clean layouts with intentional white space
- progressive scenes where mid-frame is denser than the end hold
- missing decorative polish if the core diagram + title are clear
- complete formulas that use a slightly smaller font to stay fully visible
- lively motion / multiple reveal steps if the frame stays readable
- partial title text ONLY on an earlier frame while Write/FadeIn is still running —
  judge truncation from the LAST attached frame. If the final frame shows the
  full title/subtitle, do not reject for mid-reveal "Sou…" / "Direc…" clips.

Scoring calibration (be consistent):
- 0.75–1.0: clean teaching frame; concept obvious; little/no overlap
- 0.55–0.74: readable with minor spacing issues
- 0.35–0.54: messy or partially illegible; needs layout fixes
- <0.35: broken, empty, or badly off-brief

When rejecting, revision_instructions MUST be concrete and spatial, e.g.:
"FadeOut the bitstream overlay; move formula to bottom with buff 0.3;
rename box label to 'Input Gate'; keep sigma+tanh inside the box; remove the
decorative Circle→Square morph."
If the scene is already clear enough, set approved=true and keep revision_instructions short.

CRITICAL CONSTRAINTS for revision_instructions:
- NEVER suggest MathTex, Tex, TexText, or LaTeX — unavailable on this host.
- Fix cut-off text by smaller font_size, two-line arrange(DOWN), or next_to/to_edge
  with small buff (~0.25–0.3) — e.g. Text("Cell State C(t)", font_size=24).
- RUNTIME: Text auto-recenters; to_edge(UP/DOWN) only centers X (no shrink/clamp).
  For side labels prefer next_to/move_to. Never suggest scale_to_fit_width,
  stretch_to_fit_*, Text width=, or `_ManimText`.
- NEVER truncate words/formula terms or demand large hardcoded margins.
- Prefer 1–3 surgical fixes; do not demand a full redesign of a mostly-good scene.
- Reject decorative filler shapes / collisions that obscure the teaching idea.

Also score teaching quality (0–1):
- clarity_score: how clearly the frames teach the concept
  (penalize clutter and meaningless shapes; do not penalize complete formulas)
- misconception_risk: how likely a learner is to walk away confused

{_JSON_SHAPE}
"""


def _fallback_review(reason: str) -> VlmReview:
    return VlmReview(
        approved=False,
        issues=[f"Reviewer JSON parse failed: {reason[:200]}"],
        revision_instructions=(
            "Simplify layout: keep formulas COMPLETE (ASCII like C(t)), fit labels "
            "inside boxes, move formulas to a bottom zone with buff~0.3, FadeOut prior "
            "labels before new ones, remove decorative filler shapes. "
            "Do NOT use Tex/MathTex. Do NOT truncate formula terms."
        ),
        confidence=0.2,
        clarity_score=0.35,
        misconception_risk=0.55,
    )


def _clamp01(value: object, default: float) -> float:
    try:
        num = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return default
    return max(0.0, min(1.0, num))


def _coerce_review(data: dict) -> VlmReview:
    """Tolerate partial salvaged JSON from truncated model output."""
    raw_issues = data.get("issues") or []
    if isinstance(raw_issues, str):
        issues = [raw_issues]
    elif isinstance(raw_issues, list):
        issues = [str(x) for x in raw_issues if str(x).strip()]
    else:
        issues = []
    instructions = str(data.get("revision_instructions") or "").strip()
    if instructions and not instructions.endswith((".", "!", "?", "…")):
        # Truncated mid-sentence — keep usable prefix, drop dangling fragment.
        if " " in instructions:
            instructions = instructions.rsplit(" ", 1)[0] + "…"
    # Strip forbidden LaTeX suggestions if the model ignored the prompt.
    if _FORBIDDEN_LATEX_RE.search(instructions):
        instructions = (
            "Shorten cut-off labels with Text() ASCII only "
            "(e.g. Text('Cell State C(t)', font_size=24)); "
            "fit labels inside boxes; do not use LaTeX."
        )
    return VlmReview(
        approved=bool(data.get("approved", False)),
        issues=issues[:6],
        revision_instructions=instructions[:800],
        confidence=_clamp01(data.get("confidence", 0.4), 0.4),
        clarity_score=_clamp01(data.get("clarity_score", 0.4), 0.4),
        misconception_risk=_clamp01(data.get("misconception_risk", 0.5), 0.5),
    )


def review_scene(
    client: OpenRouterClient,
    *,
    scene: SceneSection,
    code: str,
    frame_path: str | None = None,
    frame_paths: list[str] | None = None,
    frame_source: str = "none",
) -> VlmReview:
    # Keep prompt lean so the model has room to finish JSON.
    code_excerpt = code if len(code) <= 6000 else code[:6000] + "\n# ... truncated ..."
    prompt = f"""Scene title: {scene.title}
Intended visual description:
{scene.visual_description}

Animation beats:
{chr(10).join(f"- {b}" for b in scene.animation_beats)}

Narration (context only):
{scene.narration}

Manim code:
```python
{code_excerpt}
```
"""
    paths: list[str] = []
    if frame_paths:
        paths.extend(p for p in frame_paths if p and Path(p).exists())
    elif frame_path and Path(frame_path).exists():
        paths.append(frame_path)

    # Only use vision when we have a true Manim preview.
    try:
        if frame_source == "manim_preview" and paths:
            images = [Path(p).read_bytes() for p in paths]
            mime = "image/png" if paths[-1].endswith(".png") else "image/jpeg"
            n = len(images)
            attach_note = (
                f"\n{n} real rendered preview frame(s) attached "
                "(mid-scene then end, if both present). "
                "Score the teaching quality across them; do not fail solely because "
                "the end hold is sparser than the mid-frame."
            )
            data = client.chat_with_image(
                system=IMAGE_VLM_SYSTEM,
                prompt=prompt + attach_note,
                image_bytes=images,
                mime_type=mime,
                json_mode=True,
                max_tokens=4096,
            )
            assert isinstance(data, dict)
            return _coerce_review(data)

        data = client.chat_json(
            system=CODE_REVIEW_SYSTEM,
            user=prompt
            + "\nNOTE: frame_source="
            + frame_source
            + ". Review CODE ONLY. Storyboard/plan cards are not failures.",
            temperature=0.15,
            max_tokens=3072,
            model=client.manim_model,
        )
        return _coerce_review(data)
    except (ValueError, AssertionError) as exc:
        return _fallback_review(str(exc))


FINAL_DEBUG_SYSTEM = """You are the final QA editor for a multi-scene educational video.
Review the full plan and scene codes (rendering may be disabled).
Focus on code completeness, continuity across scenes, and narration coverage.
Do not request pixel-perfect frames if Manim was not rendered.
Only suggest scene_fixes for serious code defects.
Return JSON:
{
  "ok": boolean,
  "notes": string,
  "scene_fixes": [{"scene_id": string, "instructions": string}]
}
"""


def final_debug_pass(
    client: OpenRouterClient,
    *,
    plan_json: str,
    scene_summaries: str,
) -> dict:
    return client.chat_json(
        system=FINAL_DEBUG_SYSTEM,
        user=f"Scene plan JSON:\n{plan_json}\n\nBuilt scenes:\n{scene_summaries}",
        temperature=0.2,
        max_tokens=3072,
        model=client.manim_model,
    )
