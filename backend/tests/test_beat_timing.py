"""The animation is timed off these numbers, so they have to tile the voiceover.

Regression case: codegen received a list of visual actions, one undifferentiated
blob of narration, and an equal slice of time per beat — so a three-word beat got
as many seconds as a thirty-word one and the picture drifted away from the voice.
"""

from __future__ import annotations

import pytest

from backend.pipeline.beat_timing import (
    MIN_BEAT_SECONDS,
    beat_timeline,
    format_beat_timeline,
    narration_is_beat_aligned,
)
from backend.schemas import SceneSection

SHORT_LINE = "A parabola."
LONG_LINE = (
    "We drop our starting point up here on the steep left side of the curve, "
    "a long way from the answer we are looking for."
)


def _scene(beats: list[dict], duration: float = 18.0) -> SceneSection:
    return SceneSection.model_validate(
        {"id": "s1", "title": "T", "duration_seconds": duration, "beats": beats}
    )


def test_time_follows_spoken_length_not_beat_count() -> None:
    scene = _scene(
        [
            {"visual_action": "axes appear", "narration": SHORT_LINE},
            {"visual_action": "dot appears", "narration": LONG_LINE},
        ]
    )
    short, long = beat_timeline(scene, 18.0)
    assert long.duration > short.duration * 2, (short.duration, long.duration)


def test_durations_tile_the_audio_exactly() -> None:
    scene = _scene(
        [
            {"visual_action": f"beat {i}", "narration": LONG_LINE if i % 2 else SHORT_LINE}
            for i in range(5)
        ]
    )
    timings = beat_timeline(scene, 23.5)
    assert sum(t.duration for t in timings) == pytest.approx(23.5)
    # No gaps and no overlaps: each beat starts where the previous ended.
    assert timings[0].start == pytest.approx(0.0)
    for prev, curr in zip(timings, timings[1:]):
        assert curr.start == pytest.approx(prev.end)
    assert timings[-1].end == pytest.approx(23.5)


def test_measured_audio_wins_over_the_word_count_estimate() -> None:
    # TTS pacing is not proportional to word count; once measured, use it.
    scene = _scene(
        [
            {"visual_action": "a", "narration": SHORT_LINE, "audio_duration_seconds": 1.6},
            {"visual_action": "b", "narration": LONG_LINE, "audio_duration_seconds": 8.9},
            {"visual_action": "c", "narration": SHORT_LINE, "audio_duration_seconds": 7.0},
        ]
    )
    timings = beat_timeline(scene, 17.5)
    assert [round(t.duration, 2) for t in timings] == [1.6, 8.9, 7.0]


def test_silent_beats_get_staging_time_not_an_equal_share() -> None:
    scene = _scene(
        [
            {"visual_action": "camera settles", "narration": ""},
            {"visual_action": "dot appears", "narration": LONG_LINE},
        ]
    )
    silent, spoken = beat_timeline(scene, 14.0)
    assert silent.duration < spoken.duration
    assert silent.duration >= MIN_BEAT_SECONDS


def test_every_beat_clears_the_floor_when_time_is_tight() -> None:
    scene = _scene(
        [{"visual_action": f"b{i}", "narration": SHORT_LINE} for i in range(6)],
        duration=8.0,
    )
    timings = beat_timeline(scene, 8.0)
    assert all(t.duration >= MIN_BEAT_SECONDS - 1e-9 for t in timings)
    assert sum(t.duration for t in timings) == pytest.approx(8.0)


def test_more_beats_than_seconds_still_tiles_without_negative_time() -> None:
    scene = _scene(
        [{"visual_action": f"b{i}", "narration": ""} for i in range(9)], duration=3.0
    )
    timings = beat_timeline(scene, 3.0)
    assert all(t.duration > 0 for t in timings)
    assert sum(t.duration for t in timings) == pytest.approx(3.0)


def test_no_beats_or_no_time_yields_no_timeline() -> None:
    assert beat_timeline(_scene([]), 10.0) == []
    assert beat_timeline(_scene([{"visual_action": "a", "narration": "x"}]), 0.0) == []


def test_timeline_text_pairs_each_action_with_its_line() -> None:
    scene = _scene(
        [
            {"visual_action": "axes appear", "narration": SHORT_LINE},
            {"visual_action": "dot slides down", "narration": LONG_LINE},
        ]
    )
    text = format_beat_timeline(beat_timeline(scene, 18.0))
    axes_at = text.index("axes appear")
    dot_at = text.index("dot slides down")
    # Each line is quoted directly beneath the action it plays under.
    assert axes_at < text.index(SHORT_LINE) < dot_at
    assert "run_time" in text


def test_legacy_block_narration_is_flagged_as_not_beat_aligned() -> None:
    # Pre-beats plans (and every artifact on disk) carry one narration blob.
    legacy = SceneSection.model_validate(
        {
            "id": "s1",
            "title": "T",
            "duration_seconds": 12,
            "narration": "One block of script.",
            "animation_beats": ["a", "b", "c"],
        }
    )
    assert not narration_is_beat_aligned(legacy)
    # It must still produce a usable timeline rather than collapsing to one beat.
    timings = beat_timeline(legacy, 12.0)
    assert len(timings) == 3
    assert sum(t.duration for t in timings) == pytest.approx(12.0)

    aligned = _scene(
        [
            {"visual_action": "a", "narration": "First."},
            {"visual_action": "b", "narration": "Second."},
        ]
    )
    assert narration_is_beat_aligned(aligned)
