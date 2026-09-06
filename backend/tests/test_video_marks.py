"""Learner-marked video frames: storage, timeline, scene resolution."""

from __future__ import annotations

import base64

from backend.artifacts import (
    add_scene_comment,
    add_video_mark,
    job_timeline,
    list_job_marks,
    load_comment_frame_bytes,
    resolve_timeline_time,
    scene_dir,
    write_json,
)


TINY_JPEG = base64.b64encode(
    b"\xff\xd8\xff\xdb\x00C\x00" + b"\x08" * 64 + b"\xff\xd9"
).decode("ascii")


def _scene(job_id: str, scene_id: str, title: str, duration: float) -> None:
    write_json(
        scene_dir(job_id, scene_id) / "section.json",
        {"id": scene_id, "title": title, "duration_seconds": duration},
    )


def test_add_comment_stores_marked_frame(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    _scene("job1", "scene_1", "Axes", 8.0)
    entry = add_scene_comment(
        "job1",
        "scene_1",
        comment="Make the x-axis label larger",
        timestamp=2.5,
        global_timestamp=2.5,
        frame_base64=f"data:image/jpeg;base64,{TINY_JPEG}",
        author="Ada",
    )
    assert entry["timestamp"] == 2.5
    assert entry["frame_url"]
    assert "marks/" in entry["frame_url"]
    loaded = load_comment_frame_bytes("job1", "scene_1", entry["id"])
    assert loaded is not None
    data, mime = loaded
    assert mime == "image/jpeg"
    assert data.startswith(b"\xff\xd8")


def test_resolve_global_time_to_scene(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    _scene("job1", "scene_1", "Intro", 10.0)
    _scene("job1", "scene_2", "Proof", 12.0)
    timeline = job_timeline("job1")
    assert [e["scene_id"] for e in timeline] == ["scene_1", "scene_2"]
    assert timeline[0]["start"] == 0
    assert timeline[1]["start"] == 10.0

    first = resolve_timeline_time("job1", 3.2, timeline=timeline)
    assert first is not None
    assert first["scene_id"] == "scene_1"
    assert first["local_timestamp"] == 3.2

    second = resolve_timeline_time("job1", 14.5, timeline=timeline)
    assert second is not None
    assert second["scene_id"] == "scene_2"
    assert second["local_timestamp"] == 4.5


def test_add_video_mark_maps_stitched_time(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    _scene("job1", "scene_1", "Intro", 10.0)
    _scene("job1", "scene_2", "Proof", 12.0)
    mark = add_video_mark(
        "job1",
        comment="The brace is covering the formula",
        global_timestamp=14.0,
        author="Ada",
    )
    assert mark["scene_id"] == "scene_2"
    assert mark["timestamp"] == 4.0
    assert mark["global_timestamp"] == 14.0
    marks = list_job_marks("job1")
    assert len(marks) == 1
    assert marks[0]["comment"] == "The brace is covering the formula"
