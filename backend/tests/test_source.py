"""Source extraction for Create / Learn generation."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from backend.documents.source import (
    compose_learner_prompt,
    extract_path,
    extract_upload,
    job_prompt_label,
    load_source_text,
    prepare_generation_prompt,
)
from backend.learn.schemas import LearnGenerateRequest, LearnKind
from backend.schemas import GenerateRequest


def test_compose_learner_prompt_folds_source() -> None:
    text = compose_learner_prompt(
        "Explain the derivative",
        "f'(x) is the slope of the tangent.",
        filenames=["notes.txt"],
    )
    assert "Learner prompt:\nExplain the derivative" in text
    assert "SOURCE MATERIAL:" in text
    assert "f'(x) is the slope" in text
    assert "notes.txt" in text


def test_compose_learner_prompt_empty_user_prompt() -> None:
    text = compose_learner_prompt("", "Newton's second law: F = ma.", filenames=["lec.md"])
    assert "none — teach the attached material" in text
    assert "F = ma" in text


def test_job_prompt_label() -> None:
    assert job_prompt_label("Explain gravity", ["a.pdf"]) == "Explain gravity"
    assert job_prompt_label("  ", ["lecture.pdf"]) == "From lecture.pdf"


def test_extract_txt(tmp_path) -> None:
    path = tmp_path / "notes.txt"
    path.write_text("The chain rule multiplies derivatives.", encoding="utf-8")
    assert "chain rule" in extract_path(path, filename="notes.txt")


def test_extract_upload_roundtrip(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    saved = extract_upload(
        b"# Gradient descent\nTake a step downhill.",
        filename="gd.md",
    )
    assert saved["id"].startswith("src_")
    assert saved["char_count"] > 10
    loaded = load_source_text(saved["id"])
    assert "downhill" in loaded["text"]
    teaching, display, names = prepare_generation_prompt(
        "",
        [saved["id"]],
    )
    assert "SOURCE MATERIAL:" in teaching
    assert display == "From gd.md"
    assert names == ["gd.md"]


def test_prepare_requires_prompt_or_source() -> None:
    with pytest.raises(ValueError, match="prompt or attach"):
        prepare_generation_prompt("", [])


def test_generate_request_accepts_sources_without_prompt() -> None:
    req = GenerateRequest.model_validate({"source_doc_ids": ["src_abc"]})
    assert req.prompt == ""
    assert req.source_doc_ids == ["src_abc"]


def test_generate_request_rejects_empty() -> None:
    with pytest.raises(ValidationError):
        GenerateRequest.model_validate({})


def test_learn_request_accepts_sources() -> None:
    req = LearnGenerateRequest.model_validate(
        {"kind": "podcast", "source_doc_ids": ["doc_1", "doc_1", ""]}
    )
    assert req.kind == LearnKind.podcast
    assert req.source_doc_ids == ["doc_1"]


def test_list_jobs_hides_sources(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ARTIFACTS_ROOT", str(tmp_path))
    from backend import artifacts as store

    extract_upload(b"Hello source notes.", filename="hello.txt")
    (tmp_path / "vid123").mkdir()
    store.write_json(
        tmp_path / "vid123" / "meta.json",
        {"job_id": "vid123", "prompt": "explain pi", "kind": "video"},
    )
    hidden = store.list_jobs(limit=20)
    assert all(not str(j.get("job_id") or "").startswith("src_") for j in hidden)
    shown = store.list_jobs(limit=20, include_sources=True)
    assert any(str(j.get("job_id") or "").startswith("src_") for j in shown)
