"""Job file paths stay inside the job, and Manim never sees server secrets."""

from __future__ import annotations

import pytest

from backend.artifacts import resolve_job_file
from backend.pipeline.renderer import _scene_env


def test_resolve_job_file_rejects_sibling_prefix(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    (tmp_path / "job1").mkdir()
    (tmp_path / "job1" / "final.mp4").write_bytes(b"ok")
    # "job10" shares the "job1" prefix; a string prefix check would allow it.
    (tmp_path / "job10").mkdir()
    (tmp_path / "job10" / "secret.mp4").write_bytes(b"other user")

    assert resolve_job_file("job1", "final.mp4").read_bytes() == b"ok"
    with pytest.raises(ValueError):
        resolve_job_file("job1", "../job10/secret.mp4")


def test_scene_env_strips_secrets(monkeypatch) -> None:
    monkeypatch.setenv("OPENROUTER_API_KEY", "sk-test")
    monkeypatch.setenv("AUTH_SECRET", "s")
    monkeypatch.setenv("MONGODB_URI", "mongodb://u:p@h")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "k")
    monkeypatch.setenv("PATH", "/usr/bin")

    env = _scene_env()

    assert env["PATH"] == "/usr/bin"
    for name in ("OPENROUTER_API_KEY", "AUTH_SECRET", "MONGODB_URI", "SUPABASE_SERVICE_ROLE_KEY"):
        assert name not in env
