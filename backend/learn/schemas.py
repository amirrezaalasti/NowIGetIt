"""Pydantic models for podcasts, quizzes, and interactive labs."""

from __future__ import annotations

from enum import Enum
from typing import Any, Literal, Optional, Union

from pydantic import BaseModel, Field, field_validator, model_validator

from backend.languages import DEFAULT_LANGUAGE, normalize_language
from backend.schemas import TeachingBlueprint
from backend.tts_voices import DEFAULT_TTS_VOICE, normalize_tts_voice


class LearnKind(str, Enum):
    podcast = "podcast"
    quiz = "quiz"
    interactive = "interactive"


class LearnGenerateRequest(BaseModel):
    kind: LearnKind
    prompt: str = Field(default="", max_length=8000)
    source_doc_ids: list[str] = Field(default_factory=list, max_length=6)
    audience: str = Field(default="general", pattern="^(hs|undergrad|general)$")
    language: str = Field(default=DEFAULT_LANGUAGE, max_length=16)
    length_preset: str = Field(default="standard", pattern="^(short|standard|deep)$")
    tts_voice: str = Field(default=DEFAULT_TTS_VOICE, max_length=64)
    partner_voice: str = Field(default="Puck", max_length=64)
    style: str = Field(default="dialogue", pattern="^(dialogue|solo)$")
    question_count: int = Field(default=8, ge=3, le=20)
    difficulty: str = Field(default="mixed", pattern="^(easy|medium|hard|mixed)$")

    @field_validator("tts_voice", "partner_voice")
    @classmethod
    def _voice(cls, value: str) -> str:
        return normalize_tts_voice(value)

    @field_validator("language")
    @classmethod
    def _lang(cls, value: str) -> str:
        return normalize_language(value)

    @field_validator("source_doc_ids")
    @classmethod
    def _source_ids(cls, value: list[str]) -> list[str]:
        cleaned: list[str] = []
        seen: set[str] = set()
        for raw in value or []:
            item_id = str(raw or "").strip()
            if not item_id or item_id in seen:
                continue
            seen.add(item_id)
            cleaned.append(item_id)
            if len(cleaned) >= 6:
                break
        return cleaned

    @model_validator(mode="after")
    def _prompt_or_source(self) -> "LearnGenerateRequest":
        if not (self.prompt or "").strip() and not self.source_doc_ids:
            raise ValueError("Provide a prompt or attach a file")
        return self


# ---- Podcast ----------------------------------------------------------------


class PodcastLine(BaseModel):
    speaker: Literal["host", "guide"] = "guide"
    text: str = Field(..., min_length=1, max_length=1200)


class PodcastChapter(BaseModel):
    id: str
    title: str
    covers_step: str = ""
    summary: str = ""
    lines: list[PodcastLine] = Field(default_factory=list)
    duration_seconds: float = 0.0
    start_seconds: float = 0.0


class PodcastScript(BaseModel):
    title: str
    tagline: str = ""
    style: Literal["dialogue", "solo"] = "dialogue"
    host_name: str = "Alex"
    guide_name: str = "Sam"
    chapters: list[PodcastChapter] = Field(default_factory=list)
    takeaways: list[str] = Field(default_factory=list)


class PodcastResult(BaseModel):
    id: str
    kind: Literal["podcast"] = "podcast"
    title: str
    prompt: str
    status: str = "ready"
    language: str = "en"
    tts_voice: str = DEFAULT_TTS_VOICE
    partner_voice: str = "Puck"
    style: str = "dialogue"
    duration_seconds: float = 0.0
    audio_url: Optional[str] = None
    audio_skipped: bool = False
    script: PodcastScript
    blueprint: Optional[TeachingBlueprint] = None
    takeaways: list[str] = Field(default_factory=list)
    created_at: str = ""


# ---- Quiz -------------------------------------------------------------------


class QuizChoice(BaseModel):
    id: str = ""
    text: str = ""

    @model_validator(mode="before")
    @classmethod
    def _shape(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"id": "", "text": data}
        if isinstance(data, dict):
            text = data.get("text") or data.get("label") or data.get("answer")
            cid = data.get("id") or data.get("key")
            if text is None and data.get("value") is not None and cid is None:
                text = data.get("value")
            elif cid is None and data.get("value") is not None:
                cid = data.get("value")
            return {
                "id": "" if cid is None else str(cid).strip(),
                "text": "" if text is None else str(text).strip(),
            }
        return data


class QuizQuestion(BaseModel):
    id: str
    type: Literal["multiple_choice", "true_false", "numeric", "short_answer"] = (
        "multiple_choice"
    )
    prompt: str
    choices: list[QuizChoice] = Field(default_factory=list)
    correct: str = ""
    numeric_tolerance: float = 0.05
    explanation: str = ""
    hint: str = ""
    covers_step: str = ""
    difficulty: Literal["easy", "medium", "hard"] = "medium"
    why_it_matters: str = ""


class QuizPaper(BaseModel):
    title: str
    intro: str = ""
    questions: list[QuizQuestion] = Field(default_factory=list)
    pass_score: float = 0.7


class QuizResult(BaseModel):
    id: str
    kind: Literal["quiz"] = "quiz"
    title: str
    prompt: str
    status: str = "ready"
    language: str = "en"
    difficulty: str = "mixed"
    paper: QuizPaper
    blueprint: Optional[TeachingBlueprint] = None
    created_at: str = ""


class QuizAnswer(BaseModel):
    question_id: str
    answer: Union[str, float, bool, None] = None


class QuizGradeRequest(BaseModel):
    answers: list[QuizAnswer] = Field(default_factory=list)


class QuizQuestionGrade(BaseModel):
    question_id: str
    correct: bool
    expected: str = ""
    explanation: str = ""
    hint: str = ""


class QuizGradeResult(BaseModel):
    id: str
    score: float
    correct_count: int
    total: int
    passed: bool
    questions: list[QuizQuestionGrade] = Field(default_factory=list)


# ---- Interactive lab --------------------------------------------------------


VisualKind = Literal[
    "function_plot",
    "projectile",
    "wave",
    "compound_growth",
    "unit_circle",
    "spring",
    "vector_2d",
    "slope_line",
    "geometry",
]


class LabParameter(BaseModel):
    id: str = Field(..., pattern=r"^[A-Za-z_][A-Za-z0-9_]*$")
    label: str
    min: float
    max: float
    step: float = 0.1
    default: float
    unit: str = ""
    description: str = ""

    @model_validator(mode="after")
    def _bounds(self) -> "LabParameter":
        if self.max <= self.min:
            raise ValueError(f"parameter {self.id}: max must be greater than min")
        if self.default < self.min or self.default > self.max:
            self.default = min(max(self.default, self.min), self.max)
        if self.step <= 0:
            self.step = (self.max - self.min) / 100.0
        return self


class LabReadout(BaseModel):
    id: str
    label: str
    expr: str
    unit: str = ""
    precision: int = 2


class LabPoint(BaseModel):
    id: str
    x: str
    y: str
    label: str = ""


class LabVisual(BaseModel):
    kind: VisualKind
    title: str = ""
    x_label: str = ""
    y_label: str = ""
    x_min: float = -10.0
    x_max: float = 10.0
    y_min: Optional[float] = None
    y_max: Optional[float] = None
    # function_plot / slope_line / wave
    expr: str = ""
    # projectile / spring / wave animation
    animate: bool = True
    # geometry
    points: list[LabPoint] = Field(default_factory=list)
    segments: list[list[str]] = Field(default_factory=list)
    fills: list[list[str]] = Field(default_factory=list)
    # projectile target overlay (world units)
    target_x: Optional[float] = None
    target_y: Optional[float] = None
    target_radius: float = 1.0


def _first_text(*values: Any) -> str:
    for value in values:
        text = str(value or "").strip()
        if text:
            return text
    return ""


def _normalize_lab_quiz(raw: Any, *, fallback_prompt: str = "") -> Optional[dict[str, Any]]:
    """Accept nested quiz objects, flat prompt/choices, or a bare question string."""
    prompt = fallback_prompt
    choices: Any = []
    correct = ""
    explanation = ""
    if isinstance(raw, str):
        prompt = raw.strip() or prompt
    elif isinstance(raw, dict):
        nested = raw.get("quiz")
        if isinstance(nested, str):
            prompt = nested.strip() or prompt
        elif isinstance(nested, dict):
            prompt = _first_text(
                nested.get("prompt"), nested.get("question"), prompt
            )
            choices = nested.get("choices") or nested.get("options") or []
            correct = str(nested.get("correct") or nested.get("answer") or "")
            explanation = str(nested.get("explanation") or "")
        prompt = _first_text(
            raw.get("prompt"),
            raw.get("question"),
            raw.get("quiz_prompt"),
            prompt,
        )
        if not choices:
            choices = raw.get("choices") or raw.get("options") or []
        if not correct:
            correct = str(raw.get("correct") or raw.get("answer") or "")
        if not explanation:
            explanation = str(raw.get("explanation") or "")
    prompt = (prompt or "").strip()
    if not prompt:
        return None
    return {
        "prompt": prompt,
        "choices": choices or [],
        "correct": correct,
        "explanation": explanation,
    }


class LabQuiz(BaseModel):
    prompt: str = ""
    choices: list[QuizChoice] = Field(default_factory=list)
    correct: str = ""
    explanation: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"prompt": data}
        return data

    @model_validator(mode="after")
    def _fill_ids(self) -> "LabQuiz":
        letters = "abcdefghijklmnopqrstuvwxyz"
        for i, choice in enumerate(self.choices):
            if not (choice.id or "").strip():
                choice.id = letters[i] if i < len(letters) else f"c{i}"
        if self.choices and (self.correct or "").strip():
            ids = {c.id for c in self.choices}
            given = self.correct.strip()
            if given not in ids:
                low = given.lower()
                matched = next(
                    (
                        c.id
                        for c in self.choices
                        if c.id.lower() == low or c.text.strip().lower() == low
                    ),
                    None,
                )
                if matched:
                    self.correct = matched
                elif len(low) == 1 and "a" <= low <= "z":
                    idx = ord(low) - 97
                    if 0 <= idx < len(self.choices):
                        self.correct = self.choices[idx].id
        if self.choices and not (self.correct or "").strip():
            self.correct = self.choices[0].id
        return self


class LabGoal(BaseModel):
    type: Literal[
        "observe",
        "change_param",
        "quiz",
        "target",
        "acknowledge",
    ] = "observe"
    param: str = ""
    min_delta: float = 0.0
    readout: str = ""
    value: float = 0.0
    tolerance: float = 1.0
    quiz: Optional[LabQuiz] = None

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if isinstance(data, str):
            return {"type": data}
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        gtype = str(payload.get("type") or "observe")
        if gtype == "quiz":
            quiz = _normalize_lab_quiz(payload)
            if quiz:
                payload["quiz"] = quiz
        return payload


class LabPhase(BaseModel):
    id: str
    kind: Literal[
        "orient",
        "explore",
        "predict",
        "test",
        "challenge",
        "check",
        "reflect",
    ]
    title: str
    coach: str = ""
    locked_params: list[str] = Field(default_factory=list)
    suggested_params: dict[str, float] = Field(default_factory=dict)
    goal: LabGoal = Field(default_factory=LabGoal)
    hint: str = ""
    success: str = ""

    @model_validator(mode="before")
    @classmethod
    def _coerce(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        payload = dict(data)
        kind = str(payload.get("kind") or "")
        goal = payload.get("goal")
        if isinstance(goal, str):
            goal = {"type": goal}
        if goal is None:
            goal = {
                "type": {
                    "orient": "observe",
                    "explore": "change_param",
                    "predict": "quiz",
                    "test": "observe",
                    "challenge": "target",
                    "check": "quiz",
                    "reflect": "acknowledge",
                }.get(kind, "observe")
            }
        if isinstance(goal, dict):
            goal = dict(goal)
            if str(goal.get("type") or "") == "quiz" or kind in {"predict", "check"}:
                quiz = _normalize_lab_quiz(
                    {
                        **goal,
                        "quiz": goal.get("quiz"),
                        "prompt": goal.get("prompt") or payload.get("prompt"),
                        "question": goal.get("question") or payload.get("question"),
                        "choices": goal.get("choices") or payload.get("choices"),
                        "options": goal.get("options") or payload.get("options"),
                        "correct": goal.get("correct") or payload.get("correct"),
                    },
                    fallback_prompt=str(
                        payload.get("question")
                        or payload.get("prompt")
                        or payload.get("coach")
                        or payload.get("title")
                        or ""
                    ),
                )
                if quiz:
                    goal["type"] = "quiz"
                    goal["quiz"] = quiz
            payload["goal"] = goal
        return payload


class InteractiveLesson(BaseModel):
    title: str
    tagline: str = ""
    core_question: str = ""
    payoff: str = ""
    running_example: str = ""
    visual: LabVisual
    parameters: list[LabParameter] = Field(default_factory=list)
    readouts: list[LabReadout] = Field(default_factory=list)
    phases: list[LabPhase] = Field(default_factory=list)
    misconceptions: list[str] = Field(default_factory=list)


class InteractiveResult(BaseModel):
    id: str
    kind: Literal["interactive"] = "interactive"
    title: str
    prompt: str
    status: str = "ready"
    language: str = "en"
    lesson: InteractiveLesson
    blueprint: Optional[TeachingBlueprint] = None
    created_at: str = ""


class LabProgressRequest(BaseModel):
    phase_id: str = ""
    params: dict[str, float] = Field(default_factory=dict)
    answers: dict[str, str] = Field(default_factory=dict)
    completed_phases: list[str] = Field(default_factory=list)


class LabProgressResult(BaseModel):
    id: str
    phase_id: str
    goal_met: bool
    message: str = ""
    readouts: dict[str, float] = Field(default_factory=dict)
    completed_phases: list[str] = Field(default_factory=list)


LearnItem = Union[PodcastResult, QuizResult, InteractiveResult]
