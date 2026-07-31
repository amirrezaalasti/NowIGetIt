"""Pydantic models for the scene-planning and generation pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator

from backend.languages import DEFAULT_LANGUAGE, normalize_language
from backend.tts_voices import DEFAULT_TTS_VOICE, normalize_tts_voice


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=32000)
    resolution: str = Field(default="720p", pattern="^(480p|720p|1080p)$")
    skip_render: bool = False
    # short ≈ 60s intuition · standard ≈ 90s · deep ≈ 3 min
    length_preset: str = Field(
        default="standard", pattern="^(short|standard|deep)$"
    )
    # hs | undergrad | general — steers metaphor depth and jargon
    audience: str = Field(
        default="general", pattern="^(hs|undergrad|general)$"
    )
    # Narration + on-screen label language (ISO-ish code, e.g. en, fa, es)
    language: str = Field(default=DEFAULT_LANGUAGE, max_length=16)
    # Gemini TTS narrator voice (OpenRouter google/gemini-3.1-flash-tts-preview)
    tts_voice: str = Field(default=DEFAULT_TTS_VOICE, max_length=64)
    # Generate spoken narration audio (default on). Subtitles can still be on.
    include_audio: bool = True
    # Burn narration as on-screen subtitles (default on)
    include_subtitles: bool = True
    # If true, stop after planning so the UI can edit the storyboard
    plan_only: bool = False

    @field_validator("tts_voice")
    @classmethod
    def _normalize_voice(cls, value: str) -> str:
        return normalize_tts_voice(value)

    @field_validator("language")
    @classmethod
    def _normalize_language(cls, value: str) -> str:
        return normalize_language(value)


class ContinueRequest(BaseModel):
    resolution: Optional[str] = Field(
        default=None, pattern="^(480p|720p|1080p)$"
    )
    skip_render: bool = False
    language: Optional[str] = Field(default=None, max_length=16)
    tts_voice: Optional[str] = Field(default=None, max_length=64)
    include_audio: Optional[bool] = None
    include_subtitles: Optional[bool] = None

    @field_validator("tts_voice")
    @classmethod
    def _normalize_voice(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        return normalize_tts_voice(value)

    @field_validator("language")
    @classmethod
    def _normalize_language(cls, value: Optional[str]) -> Optional[str]:
        if value is None or not str(value).strip():
            return None
        return normalize_language(value)


class SceneSection(BaseModel):
    id: str
    title: str
    narration: str = Field(
        ..., description="Voiceover script for TTS for this section"
    )
    visual_description: str = Field(
        default="", description="What should appear on screen in this scene"
    )
    animation_beats: list[str] = Field(default_factory=list)
    duration_seconds: float = Field(default=8.0, ge=2.0, le=60.0)
    camera_notes: str = ""
    # Pedagogical visual device, e.g. number_line, equation_reveal, particle_flow
    visual_device: str = ""
    # Keyword tags used for Manim template retrieval
    style_tags: list[str] = Field(default_factory=list)


class ScenePlan(BaseModel):
    title: str
    concept_summary: str
    style_notes: str = ""
    # Visual identity: palette + metaphor direction for consistent look
    visual_identity: str = ""
    # Concrete visual anchors (named object/shape/color role) reused verbatim
    # across every scene so scenes look like one video, not disconnected clips.
    recurring_elements: list[str] = Field(default_factory=list)
    palette: dict[str, str] = Field(
        default_factory=dict,
        description="Named colors e.g. background, accent, text, highlight",
    )
    scenes: list[SceneSection]


class UpdatePlanRequest(BaseModel):
    plan: ScenePlan


class RevisePlanRequest(BaseModel):
    """Ask the AI planner to add/remove/edit scenes via natural language."""

    instructions: str = Field(..., min_length=2, max_length=2000)


class RegenerateSceneRequest(BaseModel):
    """Regenerate one scene from its plan section (optionally edited)."""

    direction: str = Field(
        default="",
        max_length=500,
        description="Optional creative direction, e.g. 'more visual, less text'",
    )
    section: Optional[SceneSection] = None
    skip_render: bool = False


class VlmReview(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    revision_instructions: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)
    # Teacher-style scores (0–1); optional for backward compatibility
    clarity_score: float = Field(default=0.5, ge=0.0, le=1.0)
    misconception_risk: float = Field(default=0.5, ge=0.0, le=1.0)


class SceneCommentRequest(BaseModel):
    comment: str = Field(..., min_length=1, max_length=2000)
    timestamp: Optional[float] = Field(default=None, ge=0.0)
    author: str = "Human Reviewer"


class SceneComment(BaseModel):
    id: str
    job_id: str
    scene_id: str
    comment: str
    timestamp: Optional[float] = None
    author: str
    created_at: str


class PipelineEventType(str, Enum):
    status = "status"
    plan = "plan"
    plan_ready = "plan_ready"
    scene_start = "scene_start"
    scene_code = "scene_code"
    scene_render = "scene_render"
    scene_vlm = "scene_vlm"
    scene_revise = "scene_revise"
    scene_tts = "scene_tts"
    scene_done = "scene_done"
    final_debug = "final_debug"
    complete = "complete"
    error = "error"


class PipelineEvent(BaseModel):
    type: PipelineEventType
    message: str
    data: Optional[dict[str, Any]] = None


class SceneArtifact(BaseModel):
    scene_id: str
    title: str
    narration: str
    code: str
    revision_count: int = 0
    vlm_approved: bool = False
    vlm_issues: list[str] = Field(default_factory=list)
    video_path: Optional[str] = None
    video_url: Optional[str] = None
    preview_note: Optional[str] = None
    audio_path: Optional[str] = None
    audio_skipped: bool = False
    vlm_frame_urls: list[str] = Field(default_factory=list)
    vlm_reviews: list[dict[str, Any]] = Field(default_factory=list)
    artifact_dir: Optional[str] = None


class GenerateResult(BaseModel):
    title: str
    plan: ScenePlan
    scenes: list[SceneArtifact]
    final_debug_notes: str = ""
    final_video_path: Optional[str] = None
    final_video_url: Optional[str] = None
    render_enabled: bool = False
    job_id: str = ""
    artifact_url: Optional[str] = None
    scene_plan_url: Optional[str] = None
    awaiting_plan_confirm: bool = False
