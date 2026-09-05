"""Pydantic models for the scene-planning and generation pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import (
    BaseModel,
    Field,
    computed_field,
    field_validator,
    model_validator,
)

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
    # short = many quick scenes · balanced = default · long = fewer deeper scenes
    scene_pacing: str = Field(
        default="balanced", pattern="^(short|balanced|long)$"
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
    # Host-authored storyboard (ChatGPT/Claude MCP). Skips OpenRouter planning.
    scene_plan: Optional["ScenePlan"] = None

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
    # Use Manim already saved via PUT .../scenes/{id}/code (no OpenRouter codegen).
    skip_codegen: bool = False
    # Skip VLM review/auto-revise (MCP host is the reviewer).
    skip_vlm: bool = False

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


class NotationEntry(BaseModel):
    """One symbol/quantity and the visual role it owns for the whole video."""

    symbol: str
    meaning: str = ""
    # The persistent visual identity of this quantity (color, shape, axis, or
    # position) so the same thing looks the same in every scene.
    visual_encoding: str = ""

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, data: Any) -> Any:
        return {"symbol": data} if isinstance(data, str) else data


class Relation(BaseModel):
    """One equation/relationship, plus how it is earned rather than asserted."""

    expression: str
    reads_as: str = ""
    why_true: str = ""
    how_to_show: str = ""

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, data: Any) -> Any:
        return {"expression": data} if isinstance(data, str) else data


class Misconception(BaseModel):
    belief: str
    correction: str = ""
    how_the_visual_prevents_it: str = ""

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, data: Any) -> Any:
        return {"belief": data} if isinstance(data, str) else data


class BlueprintStep(BaseModel):
    """One rung of the explanation ladder, decided before any scene exists."""

    id: str = ""
    claim: str
    why_it_follows: str = ""
    # Symbols / relations (by name) this step introduces or uses.
    uses: list[str] = Field(default_factory=list)
    visual_strategy: str = ""
    checkpoint: str = ""

    @model_validator(mode="before")
    @classmethod
    def _accept_plain_string(cls, data: Any) -> Any:
        return {"claim": data} if isinstance(data, str) else data


class TeachingBlueprint(BaseModel):
    """How to teach the concept — decided BEFORE the storyboard is written.

    The planner turns these steps into scenes and the code generator reads the
    notation/visual grammar, so the mathematics is introduced in one deliberate
    order with one consistent visual language instead of being improvised per
    scene.
    """

    core_question: str = ""
    payoff: str = ""
    prerequisites: list[str] = Field(default_factory=list)
    running_example: str = ""
    math_treatment: str = ""
    notation: list[NotationEntry] = Field(default_factory=list)
    relations: list[Relation] = Field(default_factory=list)
    steps: list[BlueprintStep] = Field(default_factory=list)
    misconceptions: list[Misconception] = Field(default_factory=list)
    # Invariant rules for the visual language, e.g. "time always runs left→right".
    visual_grammar: list[str] = Field(default_factory=list)
    out_of_scope: list[str] = Field(default_factory=list)


class AnimationBeat(BaseModel):
    visual_action: str = Field(
        ..., description="What happens on screen during this exact beat"
    )
    narration: str = Field(
        ..., description="The spoken narration for this exact beat"
    )
    audio_duration_seconds: float = Field(
        default=0.0, description="Injected post-TTS to guide scene generation"
    )


class SceneSection(BaseModel):
    id: str
    title: str
    beats: list[AnimationBeat] = Field(
        default_factory=list,
        description="List of paired visual actions and spoken narration chunks"
    )
    duration_seconds: float = Field(default=8.0, ge=2.0, le=120.0)
    visual_description: str = ""
    camera_notes: str = ""
    # Pedagogical visual device, e.g. number_line, equation_reveal, particle_flow
    visual_device: str = ""
    # Keyword tags used for Manim template retrieval
    style_tags: list[str] = Field(default_factory=list)
    # Ids of the TeachingBlueprint steps this scene delivers (in order).
    covers_steps: list[str] = Field(default_factory=list)

    # `beats` is the canonical shape, but the UI, every saved scene_plan.json,
    # and section.json on disk all speak the flat `narration` + `animation_beats`
    # shape. Accept both on the way in (below) and emit both on the way out
    # (computed fields) — otherwise a plan round-tripped through the storyboard
    # editor comes back with no narration at all: no TTS, no subtitles, and a
    # codegen prompt with an empty script.
    @model_validator(mode="before")
    @classmethod
    def _accept_flat_narration(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            return data
        beats = data.get("beats")
        if isinstance(beats, list) and beats:
            return data

        actions = data.get("animation_beats")
        actions = (
            [str(a) for a in actions if str(a).strip()]
            if isinstance(actions, list)
            else []
        )
        narration = data.get("narration")
        narration = str(narration).strip() if narration is not None else ""
        if not actions and not narration:
            return data

        data = dict(data)
        if actions:
            # Whole narration rides on the first beat: splitting prose across
            # visual actions would invent sentence boundaries that were never
            # authored, and only the joined text is ever spoken.
            data["beats"] = [
                {"visual_action": action, "narration": narration if i == 0 else ""}
                for i, action in enumerate(actions)
            ]
        else:
            data["beats"] = [{"visual_action": "", "narration": narration}]
        return data

    @model_validator(mode="after")
    def _fill_visual_description(self) -> SceneSection:
        if not self.visual_description and self.beats:
            self.visual_description = " ".join(b.visual_action for b in self.beats if b.visual_action)
        return self

    @computed_field  # type: ignore[prop-decorator]
    @property
    def narration(self) -> str:
        return " ".join(b.narration for b in self.beats if b.narration)

    @computed_field  # type: ignore[prop-decorator]
    @property
    def animation_beats(self) -> list[str]:
        return [b.visual_action for b in self.beats if b.visual_action]


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
    # The teaching plan the scenes were derived from (step 0 of the pipeline).
    blueprint: Optional[TeachingBlueprint] = None
    scenes: list[SceneSection]


class UpdatePlanRequest(BaseModel):
    plan: ScenePlan


class JobSettingsRequest(BaseModel):
    tts_voice: Optional[str] = Field(default=None, max_length=64)
    language: Optional[str] = Field(default=None, max_length=16)
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


class PatchSceneRequest(BaseModel):
    title: Optional[str] = Field(default=None, max_length=200)
    narration: Optional[str] = Field(default=None, max_length=8000)
    visual_description: Optional[str] = Field(default=None, max_length=4000)
    duration_seconds: Optional[float] = Field(default=None, ge=2.0, le=120.0)
    visual_device: Optional[str] = Field(default=None, max_length=200)
    camera_notes: Optional[str] = Field(default=None, max_length=2000)
    beats: Optional[list[AnimationBeat]] = None


class SubmitSceneCodeRequest(BaseModel):
    code: str = Field(..., min_length=40, max_length=120_000)


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


class StorageModeRequest(BaseModel):
    mode: str = Field(..., pattern="^(local|mongo|supabase)$")


GenerateRequest.model_rebuild()
