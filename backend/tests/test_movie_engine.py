"""Manim vs cinematic movie engine selection and Ken Burns fallback."""

from __future__ import annotations

from pathlib import Path

import pytest

from backend.pipeline.engines import bake_scene_engines, resolve_scene_engine
from backend.pipeline.movie_shots import (
    MovieShotSpec,
    dumps_shot_spec,
    is_movie_shot_spec,
    loads_shot_spec,
)
from backend.schemas import GenerateRequest, SceneSection


def _scene(**kwargs) -> SceneSection:
    data = {
        "id": "scene_1",
        "title": "T",
        "duration_seconds": 10,
        "beats": [{"visual_action": "move", "narration": "Hello there."}],
    }
    data.update(kwargs)
    return SceneSection.model_validate(data)


def test_generate_request_accepts_visual_engine() -> None:
    req = GenerateRequest.model_validate(
        {"prompt": "Explain lightning", "visual_engine": "movie"}
    )
    assert req.visual_engine == "movie"
    auto = GenerateRequest.model_validate({"prompt": "Explain parabolas"})
    assert auto.visual_engine == "auto"


def test_explicit_scene_engine_wins() -> None:
    scene = _scene(visual_engine="movie", visual_device="axes_graph")
    assert resolve_scene_engine(scene, "manim") == "movie"


def test_job_engine_locks_unspecified_scenes() -> None:
    scene = _scene(title="Gradient descent on a parabola")
    assert resolve_scene_engine(scene, "movie") == "movie"
    assert resolve_scene_engine(scene, "manim") == "manim"


def test_auto_picks_manim_for_math() -> None:
    scene = _scene(
        title="The derivative as slope",
        visual_description="Axes and a parabola with a tangent line.",
        visual_device="axes_graph",
    )
    assert resolve_scene_engine(scene, "auto") == "manim"


def test_auto_picks_movie_for_biology() -> None:
    scene = _scene(
        title="A vaccine trains immune cells",
        visual_description="Macrophage swallows a virus particle under a microscope.",
        visual_device="cinematic_shot",
    )
    assert resolve_scene_engine(scene, "auto") == "movie"


def test_bake_stamps_concrete_engines() -> None:
    from backend.schemas import ScenePlan

    plan = ScenePlan.model_validate(
        {
            "title": "Mix",
            "concept_summary": "Both.",
            "scenes": [
                _scene(
                    id="scene_1",
                    title="Parabola",
                    visual_device="axes_graph",
                ).model_dump(),
                _scene(
                    id="scene_2",
                    title="Storm",
                    visual_description="Lightning equalizes charge between cloud and earth.",
                    visual_device="cinematic_shot",
                ).model_dump(),
            ],
        }
    )
    baked = bake_scene_engines(plan, "auto")
    assert baked.scenes[0].visual_engine == "manim"
    assert baked.scenes[1].visual_engine == "movie"


def test_shot_spec_roundtrip() -> None:
    spec = MovieShotSpec.model_validate(
        {
            "style": "painted editorial, warm light",
            "beats": [
                {
                    "image_prompt": "A glowing antigen floating in lymph fluid",
                    "motion": "zoom_in",
                    "overlay_text": "Antigen",
                }
            ],
        }
    )
    assert spec.beats[0].motion == "push_in"
    raw = dumps_shot_spec(spec)
    assert is_movie_shot_spec(raw)
    assert loads_shot_spec(raw).beats[0].overlay_text == "Antigen"
    assert not is_movie_shot_spec("from manim import *\nclass S(Scene):\n    pass")


def test_ken_burns_writes_mp4(tmp_path: Path) -> None:
    import shutil

    from PIL import Image

    if not shutil.which("ffmpeg"):
        pytest.skip("ffmpeg not installed")
    from backend.pipeline.movie_render import ken_burns_clip

    still = tmp_path / "still.png"
    Image.new("RGB", (1280, 720), color=(20, 40, 50)).save(still)
    dest = tmp_path / "out.mp4"
    path, log = ken_burns_clip(
        still, dest, duration=1.2, motion="push_in", size=(640, 360)
    )
    assert path, log
    assert dest.exists() and dest.stat().st_size > 1000
