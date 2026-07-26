"""Pydantic models for the document / interactive-slides pipeline."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field


SUPPORTED_EXTENSIONS = frozenset(
    {
        ".pdf",
        ".pptx",
        ".ppt",
        ".docx",
        ".doc",
        ".xlsx",
        ".xls",
        ".html",
        ".htm",
        ".md",
        ".markdown",
        ".txt",
        ".asciidoc",
        ".adoc",
        ".png",
        ".jpg",
        ".jpeg",
        ".tif",
        ".tiff",
        ".webp",
        ".bmp",
        ".gif",
    }
)


class DocumentBlockType(str, Enum):
    heading = "heading"
    paragraph = "paragraph"
    list = "list"
    table = "table"
    figure = "figure"
    formula = "formula"
    code = "code"
    other = "other"


class DocumentAskAction(str, Enum):
    explain = "explain"
    explain_figure = "explain_figure"
    comment = "comment"
    simplify = "simplify"
    translate = "translate"
    quiz = "quiz"
    deepen = "deepen"
    relate = "relate"
    critique = "critique"
    summarize_slide = "summarize_slide"
    extract_formula = "extract_formula"
    key_takeaways = "key_takeaways"
    misconceptions = "misconceptions"
    turn_into_video_prompt = "turn_into_video_prompt"
    freeform = "freeform"


class DocumentBlock(BaseModel):
    id: str
    slide_id: str
    type: DocumentBlockType = DocumentBlockType.other
    text: str = ""
    html_snippet: str = ""
    image_path: Optional[str] = None
    image_url: Optional[str] = None


class DocumentSlide(BaseModel):
    id: str
    index: int
    title: str = ""
    html: str = ""
    html_url: Optional[str] = None
    plain_text: str = ""
    block_ids: list[str] = Field(default_factory=list)


class DocumentManifest(BaseModel):
    doc_id: str
    title: str
    source_filename: str
    source_ext: str
    status: str = "ready"
    slide_count: int = 0
    slides: list[DocumentSlide] = Field(default_factory=list)
    blocks: dict[str, DocumentBlock] = Field(default_factory=dict)
    markdown_url: Optional[str] = None
    created_at: str = ""


class DocumentAskRequest(BaseModel):
    action: DocumentAskAction = DocumentAskAction.explain
    slide_id: str = Field(..., min_length=1, max_length=80)
    block_id: Optional[str] = Field(default=None, max_length=120)
    message: str = Field(default="", max_length=4000)
    language: str = Field(default="en", max_length=16)
    # Default off — UI offers an explicit "Save as comment" on the reply.
    save_as_comment: bool = False


class DocumentAskResult(BaseModel):
    doc_id: str
    slide_id: str
    block_id: Optional[str] = None
    action: DocumentAskAction
    reply: str
    comment_id: Optional[str] = None
    video_prompt: Optional[str] = None


class DocumentCommentRequest(BaseModel):
    """Persist an LLM reply (or note) as a comment on a slide."""

    slide_id: str = Field(..., min_length=1, max_length=80)
    block_id: Optional[str] = Field(default=None, max_length=120)
    action: str = Field(default="comment", max_length=64)
    message: str = Field(default="", max_length=4000)
    reply: str = Field(..., min_length=1, max_length=20000)
    author: str = Field(default="user+llm", max_length=80)


class DocumentAnnotation(BaseModel):
    id: str
    doc_id: str
    slide_id: str
    block_id: Optional[str] = None
    action: str
    message: str = ""
    reply: str = ""
    author: str = "user"
    created_at: str
    pinned: bool = True


class DocumentListItem(BaseModel):
    doc_id: str
    title: Optional[str] = None
    source_filename: Optional[str] = None
    created_at: Optional[str] = None
    status: Optional[str] = None
    slide_count: int = 0
    kind: str = "document"


class ConvertWorkerPayload(BaseModel):
    """Response from the Docling worker."""

    ok: bool
    title: str = ""
    markdown: str = ""
    html: str = ""
    pages_html: list[str] = Field(default_factory=list)
    assets: list[dict[str, Any]] = Field(default_factory=list)
    log: str = ""
    error: Optional[str] = None
