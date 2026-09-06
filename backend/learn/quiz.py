"""Standalone quizzes from a teaching blueprint, plus grading."""

from __future__ import annotations

import re
from typing import Any, Callable, Optional

from backend.languages import language_display_name, normalize_language
from backend.learn.schemas import (
    QuizAnswer,
    QuizGradeResult,
    QuizPaper,
    QuizQuestion,
    QuizQuestionGrade,
)
from backend.llm import OpenRouterClient
from backend.pipeline.pedagogy import format_blueprint_for_planner
from backend.schemas import TeachingBlueprint

Progress = Callable[[str, dict[str, Any]], None]

QUIZ_SYSTEM = """You write quizzes that check whether a concept actually clicked.

Each question maps to one teaching-step checkpoint. Wrong answers should be
the misconceptions a real learner would hold — not silly distractors.

RULES:
- Mix types: mostly multiple_choice (4 choices, ids a/b/c/d), some true_false,
  1–2 numeric (correct is a number as a string), optional short_answer.
- For multiple_choice, `correct` is the choice id (a/b/c/d).
- For true_false, choices are [{id:"true", text:"True"}, {id:"false", text:"False"}]
  and correct is "true" or "false".
- For numeric, correct is the number as a string (e.g. "0.5"); set numeric_tolerance.
- For short_answer, correct is the expected phrase in lowercase; grading is
  generous on wording so keep the expected answer short and canonical.
- explanation: teach the idea in 2–4 sentences using the running example.
  Do not just restate the correct option.
- hint: a nudge that does not give the answer away.
- why_it_matters: one sentence on what this question proves the learner can do.
- Order: easy → medium → hard, following the teaching steps.

Return ONLY JSON:
{
  "title": string,
  "intro": string,
  "pass_score": 0.7,
  "questions": [
    {
      "id": "q1",
      "type": "multiple_choice"|"true_false"|"numeric"|"short_answer",
      "prompt": string,
      "choices": [{"id": "a", "text": string}],
      "correct": string,
      "numeric_tolerance": 0.05,
      "explanation": string,
      "hint": string,
      "covers_step": "step_1",
      "difficulty": "easy"|"medium"|"hard",
      "why_it_matters": string
    }
  ]
}
"""


def generate_quiz_paper(
    client: OpenRouterClient,
    prompt: str,
    blueprint: TeachingBlueprint,
    *,
    audience: str = "general",
    language: str = "en",
    question_count: int = 8,
    difficulty: str = "mixed",
    on_progress: Optional[Progress] = None,
) -> QuizPaper:
    lang = normalize_language(language)
    lang_name = language_display_name(lang)
    user = f"""Learner prompt:
{prompt}

Audience: {audience}
Output language: write all learner-facing text in {lang_name}.
Question count: {question_count}
Difficulty mix: {difficulty}

Teaching plan — write one question per step where possible, plus a couple
that combine steps. Use the running example's real numbers:
{format_blueprint_for_planner(blueprint)}
"""
    last_err: Optional[Exception] = None
    for attempt in range(3):
        if on_progress:
            on_progress(
                f"Writing questions (attempt {attempt + 1}/3)…",
                {"step": "quiz.llm", "attempt": attempt + 1},
            )
        try:
            data = client.chat_json(
                system=QUIZ_SYSTEM,
                user=user,
                temperature=0.35 + attempt * 0.1,
                max_tokens=8192,
            )
            paper = QuizPaper.model_validate(data)
            _validate_paper(paper, question_count)
            return paper
        except Exception as exc:  # noqa: BLE001
            last_err = exc
            user += f"\n\nERROR on last attempt: {exc}\nReturn valid JSON matching the schema."
    raise ValueError(f"Failed to write quiz: {last_err}") from last_err


def _validate_paper(paper: QuizPaper, question_count: int) -> None:
    if len(paper.questions) < min(3, question_count):
        raise ValueError("quiz has too few questions")
    for q in paper.questions:
        if not q.prompt.strip() or not str(q.correct).strip():
            raise ValueError(f"{q.id} is missing a prompt or correct answer")
        if q.type in {"multiple_choice", "true_false"}:
            ids = {c.id for c in q.choices}
            if q.correct not in ids:
                raise ValueError(f"{q.id} correct={q.correct!r} is not a choice id")
            if q.type == "multiple_choice" and len(q.choices) < 3:
                raise ValueError(f"{q.id} needs at least 3 choices")


def grade_paper(paper: QuizPaper, answers: list[QuizAnswer]) -> QuizGradeResult:
    by_id = {a.question_id: a.answer for a in answers}
    grades: list[QuizQuestionGrade] = []
    correct_count = 0
    for q in paper.questions:
        given = by_id.get(q.id)
        ok = _is_correct(q, given)
        if ok:
            correct_count += 1
        grades.append(
            QuizQuestionGrade(
                question_id=q.id,
                correct=ok,
                expected=q.correct if q.type != "multiple_choice" else q.correct,
                explanation=q.explanation,
                hint="" if ok else q.hint,
            )
        )
    total = max(len(paper.questions), 1)
    score = correct_count / total
    return QuizGradeResult(
        id="",
        score=score,
        correct_count=correct_count,
        total=total,
        passed=score >= float(paper.pass_score or 0.7),
        questions=grades,
    )


def _is_correct(question: QuizQuestion, given: Any) -> bool:
    if given is None:
        return False
    expected = str(question.correct).strip()
    if question.type == "numeric":
        try:
            value = float(str(given).replace(",", "").strip())
            target = float(expected.replace(",", "").strip())
        except ValueError:
            return False
        tol = float(question.numeric_tolerance or 0.0)
        if tol <= 0:
            tol = max(0.01, abs(target) * 0.02)
        return abs(value - target) <= tol
    if question.type == "true_false":
        return _truthy(given) == _truthy(expected)
    if question.type == "short_answer":
        return _normalize_text(str(given)) == _normalize_text(expected) or _normalize_text(
            expected
        ) in _normalize_text(str(given))
    return str(given).strip().lower() == expected.lower()


def _truthy(value: Any) -> bool:
    text = str(value).strip().lower()
    return text in {"true", "t", "yes", "1", "correct"}


def _normalize_text(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", " ", text.lower()).strip()
