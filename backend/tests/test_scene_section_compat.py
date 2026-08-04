"""A scene may never lose its narration on the way through the schema.

Regression case: `narration` and `animation_beats` became read-only properties
derived from `beats`, but the UI, every saved `scene_plan.json`, and every
`section.json` on disk speak the flat shape. Pydantic dropped the unknown keys
in silence, so a plan round-tripped through the storyboard editor came back with
empty narration: no TTS, no subtitles, and a codegen prompt with no script.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from backend.schemas import ScenePlan, SceneSection

FLAT = {
    "id": "scene_1",
    "title": "Rolling downhill",
    "narration": "Here is a loss curve. We start on the steep left side.",
    "animation_beats": ["Axes fade in", "Dot appears left", "Dot steps down"],
    "duration_seconds": 12.0,
}

PAIRED = {
    "id": "scene_1",
    "title": "Rolling downhill",
    "duration_seconds": 12.0,
    "beats": [
        {"visual_action": "Axes fade in", "narration": "Here is a loss curve."},
        {"visual_action": "Dot appears left", "narration": "We start on the left."},
    ],
}


def test_flat_narration_survives_ingest() -> None:
    scene = SceneSection.model_validate(FLAT)
    assert scene.narration == FLAT["narration"]
    assert scene.animation_beats == FLAT["animation_beats"]


def test_dump_still_carries_the_keys_the_ui_reads() -> None:
    dumped = SceneSection.model_validate(PAIRED).model_dump()
    assert dumped["narration"] == "Here is a loss curve. We start on the left."
    assert dumped["animation_beats"] == ["Axes fade in", "Dot appears left"]
    # The canonical pairing is still what gets persisted.
    assert [b["visual_action"] for b in dumped["beats"]] == dumped["animation_beats"]


@pytest.mark.parametrize("payload", [FLAT, PAIRED], ids=["flat", "paired"])
def test_round_trip_is_lossless_and_idempotent(payload: dict) -> None:
    once = SceneSection.model_validate(payload)
    twice = SceneSection.model_validate(once.model_dump())
    assert twice.narration == once.narration
    assert twice.animation_beats == once.animation_beats
    assert twice.model_dump() == once.model_dump()


def test_paired_beats_win_when_both_shapes_are_present() -> None:
    # A dump carries both; the canonical `beats` must not be rebuilt from the
    # flattened copy, or per-beat narration would collapse into beat one.
    both = {**PAIRED, "narration": "stale text", "animation_beats": ["stale"]}
    scene = SceneSection.model_validate(both)
    assert scene.animation_beats == ["Axes fade in", "Dot appears left"]
    assert "stale" not in scene.narration


def test_flat_beats_keep_their_order_and_count() -> None:
    scene = SceneSection.model_validate(FLAT)
    assert len(scene.beats) == 3
    assert scene.beats[0].visual_action == "Axes fade in"
    # The whole script rides on beat one rather than being split at invented
    # sentence boundaries; only the joined text is ever spoken.
    assert scene.beats[0].narration == FLAT["narration"]
    assert scene.beats[1].narration == ""


def test_narration_only_scene_is_still_usable() -> None:
    scene = SceneSection.model_validate(
        {"id": "s", "title": "t", "narration": "Just a line.", "duration_seconds": 5}
    )
    assert scene.narration == "Just a line."


def test_every_saved_job_plan_still_loads_with_narration() -> None:
    """The artifacts/ directory is the real back-compat corpus."""
    checked = 0
    for path in sorted(Path("artifacts").glob("*/scene_plan.json")):
        plan = ScenePlan.model_validate(json.loads(path.read_text(encoding="utf-8")))
        for scene in plan.scenes:
            assert scene.narration.strip(), f"{path.parent.name}/{scene.id}"
            checked += 1
    if not checked:
        pytest.skip("no saved job plans in artifacts/")
