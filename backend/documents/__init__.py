"""Document → interactive HTML slides pipeline (Docling + LLM-on-DOM)."""

from backend.documents.pipeline import (
    ask_document_block,
    iter_document_ingest_events,
    load_document,
    run_document_ingest,
)
from backend.documents.schemas import DocumentAskRequest, DocumentAskResult

__all__ = [
    "DocumentAskRequest",
    "DocumentAskResult",
    "ask_document_block",
    "iter_document_ingest_events",
    "load_document",
    "run_document_ingest",
]
