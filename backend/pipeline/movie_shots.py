"""LLM-authored cinematic shot list for one movie-engine scene."""

from __future__ import annotations

import json
from typing import Any, Literal, Optional

from pydantic import BaseModel, Field, field_validator

from backend.languages import language_display_name, normalize_language
from backend.llm import OpenRouterClient
from backend.pipeline.beat_timing import beat_timeline, format_beat_timeline
from backend.pipeline.pedagogy import format_blueprint_for_codegen
from backend.schemas import ScenePlan, SceneSection

MotionKind = Literal["push_in", "pull_out", "pan_left", "pan_right", "hold", "drift"]

SHOT_MOTIONS = frozenset(
    {"push_in", "pull_out", "pan_left", "pan_right", "hold", "drift"}
)


class MovieBeatShot(BaseModel):
    image_prompt: str = Field(..., min_length=8)
    motion: str = "push_in"
    overlay_text: str = ""
    camera: str = ""

    @field_validator("motion")
    @classmethod
    def _motion(cls, value: str) -> str:
        key = (value or "").strip().lower().replace("-", "_").replace(" ", "_")
        aliases = {
            "zoom_in": "push_in",
            "dolly_in": "push_in",
            "zoom_out": "pull_out",
            "dolly_out": "pull_out",
            "static": "hold",
            "still": "hold",
        }
        key = aliases.get(key, key)
        return key if key in SHOT_MOTIONS else "push_in"


class MovieShotSpec(BaseModel):
    engine: str = "movie"
    style: str = ""
    negative_prompt: str = (
        "subtitles, captions, watermarks, UI chrome, extra limbs, blurry, "
        "illegible text, logo"
    )
    beats: list[MovieBeatShot] = Field(default_factory=list)

    @field_validator("engine")
    @classmethod
    def _engine(cls, value: str) -> str:
        return "movie"


SHOT_SYSTEM = """You are a cinematographer for educational explainer films.
Write a shot list for ONE scene. The picture must TEACH — every frame is the
idea made visible, not decorative b-roll.

RULES:
- One beat = one still that will be animated with camera motion while that
  beat's narration is spoken. Beats stay in order and must visually CONTINUE
  (same characters, palette, lighting, spatial layout).
- image_prompt is a concrete English image-generation prompt: subject, action,
  camera, lighting, materials. Include the shared style sentence verbatim.
- No on-image paragraphs. overlay_text is at most 4 words, or empty.
- motion is one of: push_in, pull_out, pan_left, pan_right, hold, drift.
  Match the idea: approaching a detail = push_in, revealing context = pull_out,
  comparing left/right = pan, a settled diagram = hold.
- Do not ask for charts, axes, or typeset equations — those belong in Manim.
  Show the real-world or illustrated metaphor instead.
- Avoid readable body text in the picture; labels are added later if needed.
- Return ONLY JSON.
"""


def dumps_shot_spec(spec: MovieShotSpec) -> str:
    return json.dumps(spec.model_dump(), indent=2, ensure_ascii=False)


def loads_shot_spec(text: str) -> MovieShotSpec:
    raw = (text or "").strip()
    if raw.startswith("```"):
        raw = raw.split("```", 2)[1]
        if raw.startswith("json"):
            raw = raw[4:]
        raw = raw.strip()
    data = json.loads(raw)
    if not isinstance(data, dict):
        raise ValueError("Movie shot spec must be a JSON object")
    return MovieShotSpec.model_validate(data)


def is_movie_shot_spec(text: str) -> bool:
    try:
        spec = loads_shot_spec(text)
    except Exception:  # noqa: BLE001
        return False
    return bool(spec.beats)


def generate_shot_spec(
    client: OpenRouterClient,
    *,
    plan: ScenePlan,
    scene: SceneSection,
    previous_context: str = "",
    next_context: str = "",
    language: str = "en",
    creative_direction: str = "",
) -> MovieShotSpec:
    user = _shot_user_prompt(
        plan=plan,
        scene=scene,
        previous_context=previous_context,
        next_context=next_context,
        language=language,
        creative_direction=creative_direction,
    )
    data = client.chat_json(
        system=SHOT_SYSTEM,
        user=user,
        temperature=0.4,
        max_tokens=2500,
        model=client.manim_model,
    )
    spec = MovieShotSpec.model_validate(data)
    spec = _align_beats(spec, scene)
    return spec


def revise_shot_spec(
    client: OpenRouterClient,
    *,
    spec: MovieShotSpec,
    scene: SceneSection,
    revision_instructions: str,
    language: str = "en",
) -> MovieShotSpec:
    user = (
        f"Revise this educational shot list.\n"
        f"Language for overlay_text: {language_display_name(normalize_language(language))}.\n"
        f"Scene title: {scene.title}\n"
        f"Instructions:\n{revision_instructions}\n\n"
        f"Current spec:\n{dumps_shot_spec(spec)}\n\n"
        "Return the full JSON spec, same number of beats, same engine=movie."
    )
    data = client.chat_json(
        system=SHOT_SYSTEM,
        user=user,
        temperature=0.3,
        max_tokens=2500,
        model=client.manim_model,
    )
    revised = MovieShotSpec.model_validate(data)
    return _align_beats(revised, scene)


def shot_spec_payload(
    *,
    plan: ScenePlan,
    scene: SceneSection,
    previous_context: str = "",
    next_context: str = "",
    language: str = "en",
) -> dict[str, Any]:
    """Prompt pack so a host LLM can write a movie shot spec."""
    return {
        "engine": "movie",
        "scene_id": scene.id,
        "title": scene.title,
        "target_duration_seconds": float(scene.duration_seconds),
        "system": SHOT_SYSTEM,
        "user": _shot_user_prompt(
            plan=plan,
            scene=scene,
            previous_context=previous_context,
            next_context=next_context,
            language=language,
        ),
        "output_schema": MovieShotSpec.model_json_schema(),
        "submit_as": (
            "submit_scene_code with a JSON object (engine, style, beats[]). "
            "Not Manim Python."
        ),
    }


def _align_beats(spec: MovieShotSpec, scene: SceneSection) -> MovieShotSpec:
    """One shot per scene beat so Ken Burns lines up with TTS."""
    needed = max(1, len(scene.beats) or 1)
    shots = list(spec.beats)
    if not shots:
        shots = [
            MovieBeatShot(
                image_prompt=scene.visual_description or scene.title,
                motion="push_in",
            )
        ]
    if len(shots) < needed:
        shots.extend([shots[-1].model_copy() for _ in range(needed - len(shots))])
    elif len(shots) > needed:
        shots = shots[:needed]
    return spec.model_copy(update={"beats": shots, "engine": "movie"})


def _shot_user_prompt(
    *,
    plan: ScenePlan,
    scene: SceneSection,
    previous_context: str,
    next_context: str,
    language: str,
    creative_direction: str = "",
) -> str:
    lang = language_display_name(normalize_language(language))
    palette = ", ".join(f"{k}={v}" for k, v in (plan.palette or {}).items()) or "(none)"
    recurring = (
        "; ".join(plan.recurring_elements)
        if plan.recurring_elements
        else "(none — still keep one visual identity)"
    )
    blueprint = ""
    if plan.blueprint is not None:
        blueprint = format_blueprint_for_codegen(plan.blueprint)
    direction = (
        f"\nCreative direction from the learner: {creative_direction.strip()}\n"
        if creative_direction.strip()
        else ""
    )
    beat_lines = format_beat_timeline(
        beat_timeline(scene, float(scene.duration_seconds), language=language)
    )
    return f"""Film one educational scene as illustrated cinematic shots.

Title: {plan.title}
Concept: {plan.concept_summary}
Visual identity: {plan.visual_identity or "(none)"}
Style notes: {plan.style_notes or "(none)"}
Palette: {palette}
Recurring elements (keep these identical): {recurring}
Overlay / label language: {lang}

Scene id: {scene.id}
Scene title: {scene.title}
Visual description: {scene.visual_description}
Camera notes: {scene.camera_notes or "(none)"}
Visual device: {scene.visual_device or "cinematic_shot"}

Beat timeline (picture must match the voice at each timestamp):
{beat_lines}

Previous scene context:
{previous_context or "(this is the first scene)"}
Next scene context:
{next_context or "(this is the last scene)"}
{blueprint}{direction}

JSON shape:
{{
  "engine": "movie",
  "style": "one sentence of look + lighting + medium (e.g. painted editorial illustration, warm key light, 16:9)",
  "negative_prompt": "string",
  "beats": [
    {{
      "image_prompt": "detailed English prompt including the style sentence",
      "motion": "push_in",
      "overlay_text": "",
      "camera": "slow dolly in on the ... "
    }}
  ]
}}
Exactly {max(1, len(scene.beats) or 1)} beats, in order.
"""
