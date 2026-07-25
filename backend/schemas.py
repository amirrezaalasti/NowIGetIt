"""Pydantic models for the scene-planning and generation pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


class GenerateRequest(BaseModel):
    prompt: str = Field(..., min_length=3, max_length=4000)
    resolution: str = Field(default="720p", pattern="^(480p|720p|1080p)$")
    skip_render: bool = False


class SceneSection(BaseModel):
    id: str
    title: str
    narration: str = Field(
        ..., description="Voiceover script for TTS for this section"
    )
    visual_description: str = Field(
        ..., description="What should appear on screen in this scene"
    )
    animation_beats: list[str] = Field(default_factory=list)
    duration_seconds: float = Field(default=8.0, ge=2.0, le=60.0)
    camera_notes: str = ""


class ScenePlan(BaseModel):
    title: str
    concept_summary: str
    style_notes: str = ""
    scenes: list[SceneSection]


class VlmReview(BaseModel):
    approved: bool
    issues: list[str] = Field(default_factory=list)
    revision_instructions: str = ""
    confidence: float = Field(default=0.5, ge=0.0, le=1.0)


class PipelineEventType(str, Enum):
    status = "status"
    plan = "plan"
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
