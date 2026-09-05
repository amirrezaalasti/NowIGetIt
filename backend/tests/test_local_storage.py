"""SQLite + local files when Supabase is off."""

from __future__ import annotations

import sqlite3

from backend.artifacts import list_jobs, write_json
from backend.local_db import set_storage_mode, storage_mode
from backend.sqlite_db import (
    close,
    delete_job,
    ensure_user,
    get_job_state,
    get_user_usage,
    list_user_jobs,
    record_llm_usage,
    reserve_generation,
    save_job_state,
    upsert_job,
)


def test_local_usage_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    close()
    ensure_user(user_id="u1", email="a@b.c", name="Ada")
    reserve_generation("u1")
    record_llm_usage(user_id="u1", tokens_in=10, tokens_out=5)
    usage = get_user_usage("u1")
    assert usage["unlimited"] is True
    assert usage["llm"]["requests_used"] == 1
    assert usage["llm"]["tokens_used"] == 15
    assert usage["llm"]["tokens_limit"] == 0
    db_path = tmp_path / "_local" / "nowigetit.db"
    assert db_path.exists()
    conn = sqlite3.connect(db_path)
    email = conn.execute("SELECT email FROM users WHERE id = ?", ("u1",)).fetchone()
    conn.close()
    assert email[0] == "a@b.c"


def test_sqlite_job_index(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    close()
    upsert_job(
        job_id="job1",
        user_id="u1",
        prompt="explain gravity",
        title="Gravity",
        status="complete",
    )
    save_job_state(
        job_id="job1",
        user_id="u1",
        prompt="explain gravity",
        title="Gravity",
        status="complete",
        meta={"job_id": "job1", "user_id": "u1", "prompt": "explain gravity"},
        plan={"title": "Gravity", "scenes": []},
        events=[{"type": "complete"}],
    )
    row = get_job_state("job1", "u1")
    assert row is not None
    assert row["title"] == "Gravity"
    assert row["plan"]["title"] == "Gravity"
    jobs = list_user_jobs("u1")
    assert [item["job_id"] for item in jobs] == ["job1"]
    delete_job(job_id="job1", user_id="u1")
    assert get_job_state("job1", "u1") is None


def test_list_jobs_indexes_disk_into_sqlite(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    close()
    monkeypatch.setattr("backend.artifacts.db.supabase_enabled", lambda: False)
    job = tmp_path / "job1"
    job.mkdir()
    write_json(
        job / "meta.json",
        {
            "job_id": "job1",
            "user_id": "u1",
            "prompt": "explain gravity",
            "created_at": "2026-01-01T00:00:00+00:00",
        },
    )
    (job / "result.json").write_text("{}\n", encoding="utf-8")
    jobs = list_jobs(user_id="u1")
    assert [row["job_id"] for row in jobs] == ["job1"]
    indexed = list_user_jobs("u1")
    assert indexed[0]["prompt"] == "explain gravity"


def test_set_storage_mode_local(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    monkeypatch.setenv("USE_SUPABASE", "false")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    close()
    assert set_storage_mode("local") == "local"
    assert storage_mode() == "local"


def test_set_storage_mode_supabase_requires_credentials(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    monkeypatch.setenv("USE_SUPABASE", "false")
    monkeypatch.delenv("MONGODB_URI", raising=False)
    monkeypatch.delenv("MONGO_URI", raising=False)
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("NEXT_PUBLIC_SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_SERVICE_ROLE_KEY", raising=False)
    close()
    try:
        set_storage_mode("supabase")
        raise AssertionError("expected ValueError")
    except ValueError as exc:
        assert "not available" in str(exc)
