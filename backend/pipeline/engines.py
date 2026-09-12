"""Which renderer should draw a scene: Manim diagrams or cinematic movie shots."""

from __future__ import annotations

import re
from typing import Optional

from backend.schemas import ScenePlan, SceneSection

JOB_ENGINES = frozenset({"auto", "manim", "movie"})
SCENE_ENGINES = frozenset({"manim", "movie"})

DEFAULT_JOB_ENGINE = "auto"
DEFAULT_SCENE_ENGINE = "manim"

MANIM_DEVICES = frozenset(
    {
        "number_line",
        "unit_circle",
        "equation_reveal",
        "axes_graph",
        "lattice_grid",
        "morph_transform",
        "vector_field",
        "angle_tracker",
        "boolean_sets",
        "path_trace",
        "comparison_split",
        "labeled_box_flow",
        "gate_mechanism",
        "before_after",
    }
)
MOVIE_DEVICES = frozenset(
    {
        "cinematic_shot",
        "illustrated_metaphor",
        "process_in_world",
        "character_story",
        "macroscopic_cutaway",
        "live_action_metaphor",
    }
)

_MANIM_HINTS = re.compile(
    r"\b(graph|axis|axes|equation|theorem|proof|derivative|integral|matrix|"
    r"vector|parabola|sine|cosine|limit|gradient descent|eigen|"
    r"number line|unit circle|pythagoras|pythagorean|fourier)\b",
    re.I,
)
_MOVIE_HINTS = re.compile(
    r"\b(cell|neuron as a|immune|vaccine|planet|earth|storm|lightning|"
    r"history|photograph|cinematic|blood|organ|animal|ecosystem|"
    r"molecule in (?:the )?body|real[- ]world|microscope|telescope|"
    r"people|person|crowd|city|factory|engine of a car)\b",
    re.I,
)


def normalize_job_engine(value: Optional[str]) -> str:
    key = (value or "").strip().lower()
    return key if key in JOB_ENGINES else DEFAULT_JOB_ENGINE


def normalize_scene_engine(value: Optional[str]) -> Optional[str]:
    key = (value or "").strip().lower()
    return key if key in SCENE_ENGINES else None


def resolve_scene_engine(
    scene: SceneSection,
    job_engine: str = DEFAULT_JOB_ENGINE,
    *,
    prompt: str = "",
) -> str:
    """Pick manim vs movie for one scene.

    Explicit scene.visual_engine wins, then a locked job engine, then heuristics
    on the visual device / copy. Ambiguous auto scenes stay on Manim so existing
    math videos do not silently switch to image generation.
    """
    locked = normalize_scene_engine(scene.visual_engine)
    if locked:
        return locked
    job = normalize_job_engine(job_engine)
    if job in SCENE_ENGINES:
        return job

    device = (scene.visual_device or "").strip().lower()
    if device in MOVIE_DEVICES:
        return "movie"
    if device in MANIM_DEVICES:
        return "manim"

    blob = " ".join(
        [
            scene.title,
            scene.visual_description,
            " ".join(scene.animation_beats),
            prompt,
        ]
    )
    if _MOVIE_HINTS.search(blob) and not _MANIM_HINTS.search(blob):
        return "movie"
    return DEFAULT_SCENE_ENGINE


def bake_scene_engines(
    plan: ScenePlan,
    job_engine: str = DEFAULT_JOB_ENGINE,
    *,
    prompt: str = "",
) -> ScenePlan:
    """Stamp a concrete manim|movie engine onto every scene."""
    scenes = [
        scene.model_copy(
            update={
                "visual_engine": resolve_scene_engine(
                    scene, job_engine, prompt=prompt
                )
            }
        )
        for scene in plan.scenes
    ]
    return plan.model_copy(update={"scenes": scenes})


def plan_has_movie_scenes(plan: ScenePlan, job_engine: str = DEFAULT_JOB_ENGINE) -> bool:
    return any(
        resolve_scene_engine(scene, job_engine) == "movie" for scene in plan.scenes
    )


def plan_has_manim_scenes(plan: ScenePlan, job_engine: str = DEFAULT_JOB_ENGINE) -> bool:
    return any(
        resolve_scene_engine(scene, job_engine) == "manim" for scene in plan.scenes
    )
