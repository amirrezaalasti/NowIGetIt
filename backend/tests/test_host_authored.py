"""Host-authored MCP storyboards skip OpenRouter planning."""

from __future__ import annotations

import json

import pytest

from backend.pipeline.orchestrator import continue_pipeline, run_pipeline
from backend.pipeline.planner import planning_spec_payload
from backend.schemas import ContinueRequest, GenerateRequest, ScenePlan


def _host_plan() -> dict:
    spec = planning_spec_payload()
    return {
        "title": "Backpropagation",
        "concept_summary": "Gradients from the loss.",
        "scenes": [spec["example_scene"]],
    }


def _stub_db(monkeypatch) -> None:
    from backend.pipeline import orchestrator as orch

    monkeypatch.setattr(orch.db, "ensure_user", lambda **_k: None)
    monkeypatch.setattr(orch.db, "upsert_job", lambda **_k: None)
    monkeypatch.setattr(orch.db, "save_job_state", lambda **_k: None)


def test_planning_spec_example_is_a_valid_scene_plan() -> None:
    spec = planning_spec_payload()
    assert "plan_schema" in spec
    plan = ScenePlan.model_validate(
        {
            "title": "Backpropagation",
            "concept_summary": "Error flows backward so weights can share the blame.",
            "scenes": [spec["example_scene"]],
        }
    )
    assert plan.scenes[0].id == "scene_1"
    assert plan.scenes[0].beats
    assert plan.scenes[0].narration


def test_generate_request_accepts_host_scene_plan() -> None:
    spec = planning_spec_payload()
    req = GenerateRequest.model_validate(
        {
            "prompt": "Explain backpropagation",
            "plan_only": True,
            "scene_plan": {
                "title": "Backpropagation",
                "concept_summary": "Gradients from the loss.",
                "scenes": [spec["example_scene"]],
            },
        }
    )
    assert req.scene_plan is not None
    assert req.scene_plan.title == "Backpropagation"


def test_run_pipeline_host_plan_skips_openrouter(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    from backend.pipeline import orchestrator as orch

    def _boom(*_a, **_k):
        raise AssertionError("OpenRouterClient must not be constructed for host plans")

    monkeypatch.setattr(orch, "OpenRouterClient", _boom)
    _stub_db(monkeypatch)
    spec = planning_spec_payload()
    req = GenerateRequest.model_validate(
        {
            "prompt": "Explain backpropagation",
            "plan_only": True,
            "scene_plan": {
                "title": "Backpropagation",
                "concept_summary": "Gradients from the loss.",
                "scenes": [spec["example_scene"]],
            },
        }
    )
    result = run_pipeline(req, user_id="mcp-connector")
    assert result.awaiting_plan_confirm is True
    assert result.job_id
    assert result.plan.title == "Backpropagation"


def test_job_status_saved_code_is_awaiting_render(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    from backend import job_runner

    job_id = "codeonly1234"
    root = tmp_path / job_id
    (root / "scenes" / "scene_1").mkdir(parents=True)
    (root / "meta.json").write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
    (root / "scene_plan.json").write_text(json.dumps(_host_plan()), encoding="utf-8")
    (root / "scenes" / "scene_1" / "code_final.py").write_text("x = 1\n", encoding="utf-8")
    status = job_runner.job_status(job_id)
    assert status["status"] == "awaiting_render"
    assert status["running"] is False
    assert not status["error"]


def test_job_status_clip_without_final_is_interrupted(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    from backend import job_runner

    job_id = "partialclip12"
    root = tmp_path / job_id
    (root / "scenes" / "scene_1").mkdir(parents=True)
    (root / "meta.json").write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
    (root / "scene_plan.json").write_text(json.dumps(_host_plan()), encoding="utf-8")
    (root / "scenes" / "scene_1" / "code_final.py").write_text("x = 1\n", encoding="utf-8")
    (root / "scenes" / "scene_1" / "scene.mp4").write_bytes(b"fake")
    status = job_runner.job_status(job_id)
    assert status["status"] == "interrupted"


def test_job_status_persisted_error_is_error(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    from backend import job_runner

    job_id = "renderfail123"
    root = tmp_path / job_id
    (root / "scenes" / "scene_1").mkdir(parents=True)
    (root / "meta.json").write_text(json.dumps({"job_id": job_id}), encoding="utf-8")
    (root / "scene_plan.json").write_text(json.dumps(_host_plan()), encoding="utf-8")
    (root / "scenes" / "scene_1" / "code_final.py").write_text("x = 1\n", encoding="utf-8")
    (root / "last_error.txt").write_text(
        "Manim render failed for scene_1", encoding="utf-8"
    )
    status = job_runner.job_status(job_id)
    assert status["status"] == "error"
    assert "Manim render failed" in (status["error"] or "")


def test_patch_scene_and_settings(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    from backend.pipeline import orchestrator as orch
    from backend.pipeline.orchestrator import patch_scene_section, update_job_settings

    _stub_db(monkeypatch)
    spec = planning_spec_payload()
    req = GenerateRequest.model_validate(
        {
            "prompt": "Explain backpropagation",
            "plan_only": True,
            "scene_plan": {
                "title": "Backpropagation",
                "concept_summary": "Gradients from the loss.",
                "scenes": [spec["example_scene"]],
            },
        }
    )
    result = orch.run_pipeline(req, user_id="mcp-connector")
    plan = patch_scene_section(
        result.job_id,
        "scene_1",
        title="Error flows backward",
        narration="The loss sends a message back through every layer.",
    )
    assert plan.scenes[0].title == "Error flows backward"
    assert "message back" in plan.scenes[0].narration
    settings = update_job_settings(
        result.job_id,
        tts_voice="alloy",
        language="en",
        include_audio=False,
        include_subtitles=True,
    )
    assert settings["tts_voice"] == "alloy"
    assert settings["include_audio"] is False
    assert settings["include_subtitles"] is True
    assert settings["production_options_confirmed"] is True


def test_production_options_are_chosen_after_plan(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    from backend import artifacts as store
    from backend.pipeline import orchestrator as orch
    from backend.pipeline.orchestrator import (
        ProductionOptionsRequired,
        job_codegen_spec,
        update_job_settings,
    )

    _stub_db(monkeypatch)
    spec = planning_spec_payload()
    req = GenerateRequest.model_validate(
        {
            "prompt": "Explain backpropagation",
            "plan_only": True,
            "scene_plan": {
                "title": "Backpropagation",
                "concept_summary": "Gradients from the loss.",
                "scenes": [spec["example_scene"]],
            },
        }
    )
    result = orch.run_pipeline(req, user_id="mcp-connector")
    meta = store.load_job(result.job_id).get("meta") or {}
    settings = meta.get("settings") or {}
    assert settings.get("production_options_confirmed") is False
    assert "include_audio" not in settings
    assert "include_subtitles" not in settings
    with pytest.raises(ProductionOptionsRequired):
        job_codegen_spec(result.job_id, "scene_1")
    with pytest.raises(ProductionOptionsRequired):
        continue_pipeline(result.job_id, ContinueRequest(), user_id="mcp-connector")
    update_job_settings(
        result.job_id,
        include_audio=True,
        include_subtitles=False,
        tts_voice="alloy",
    )
    spec_payload = job_codegen_spec(result.job_id, "scene_1")
    assert spec_payload["scene_id"] == "scene_1"


def test_continue_host_authored_skips_openrouter_without_flags(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    from backend.pipeline import orchestrator as orch

    _stub_db(monkeypatch)
    spec = planning_spec_payload()
    req = GenerateRequest.model_validate(
        {
            "prompt": "Explain backpropagation",
            "plan_only": True,
            "scene_plan": {
                "title": "Backpropagation",
                "concept_summary": "Gradients from the loss.",
                "scenes": [spec["example_scene"]],
            },
        }
    )
    result = run_pipeline(req, user_id="mcp-connector")

    from backend.pipeline.orchestrator import update_job_settings

    update_job_settings(
        result.job_id,
        include_audio=True,
        include_subtitles=True,
        tts_voice="Kore",
    )

    def _boom(*_a, **_k):
        raise AssertionError(
            "OpenRouterClient must not be constructed for host-authored continue"
        )

    captured: dict = {}

    def _fake_loop(**kwargs):
        captured.update(kwargs)
        raise RuntimeError("stop-after-flags")

    monkeypatch.setattr(orch, "OpenRouterClient", _boom)
    monkeypatch.setattr(orch, "_run_scenes_loop", _fake_loop)
    with pytest.raises(RuntimeError, match="stop-after-flags"):
        continue_pipeline(result.job_id, ContinueRequest(), user_id="mcp-connector")
    assert captured["skip_codegen"] is True
    assert captured["skip_vlm"] is True
    assert captured["client"] is None
