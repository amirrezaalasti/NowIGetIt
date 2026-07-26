"""Document ingest + ask orchestration (progressive page conversion)."""

from __future__ import annotations

import json
import queue
import threading
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterator, Optional

from backend import artifacts as base
from backend import supabase_db as db
from backend.documents import store
from backend.documents.ask import ask_on_manifest
from backend.documents.convert import (
    count_document_pages,
    iter_convert_pages,
    rewrite_html_asset_names,
    write_assets_namespaced,
)
from backend.documents.enrich import enrich_single_page, split_pages_html, write_slides
from backend.documents.schemas import (
    SUPPORTED_EXTENSIONS,
    DocumentAskRequest,
    DocumentAskResult,
    DocumentBlock,
    DocumentManifest,
    DocumentSlide,
)
from backend.llm import OpenRouterClient

EventCallback = Callable[[str, str, Optional[dict[str, Any]]], None]


def load_document(doc_id: str) -> dict[str, Any]:
    manifest = store.load_manifest(doc_id)
    annotations = store.list_annotations(doc_id)
    return {
        "doc_id": doc_id,
        "manifest": manifest.model_dump(),
        "annotations": annotations,
        "urls": {
            "document": f"/api/jobs/{doc_id}/file/document.json",
            "markdown": f"/api/jobs/{doc_id}/file/document.md",
        },
    }


def _slim_slide(slide: DocumentSlide) -> DocumentSlide:
    return DocumentSlide(
        id=slide.id,
        index=slide.index,
        title=slide.title,
        html="",
        html_url=slide.html_url,
        plain_text=slide.plain_text,
        block_ids=slide.block_ids,
    )


def _slim_blocks(blocks: dict[str, DocumentBlock]) -> dict[str, DocumentBlock]:
    return {
        bid: b.model_copy(update={"html_snippet": b.html_snippet[:500]})
        for bid, b in blocks.items()
    }


def _persist_partial(
    doc_id: str,
    *,
    title: str,
    source_filename: str,
    ext: str,
    status: str,
    slides: list[DocumentSlide],
    blocks: dict[str, DocumentBlock],
    created_at: str,
    expected_pages: Optional[int] = None,
) -> DocumentManifest:
    root = store.doc_dir(doc_id)
    manifest = DocumentManifest(
        doc_id=doc_id,
        title=title,
        source_filename=source_filename,
        source_ext=ext,
        status=status,
        slide_count=len(slides),
        slides=[_slim_slide(s) for s in slides],
        blocks=_slim_blocks(blocks),
        markdown_url=f"/api/jobs/{doc_id}/file/document.md",
        created_at=created_at,
    )
    store.save_manifest(doc_id, manifest)
    base.write_json(
        root / "blocks.json",
        {
            bid: {
                **b.model_dump(),
                "html_snippet": (b.html_snippet[:500] if b.html_snippet else ""),
            }
            for bid, b in blocks.items()
        },
    )
    meta_path = root / "meta.json"
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            meta = {}
        meta["status"] = status
        meta["title"] = title
        meta["slide_count"] = len(slides)
        if expected_pages is not None:
            meta["expected_pages"] = expected_pages
        base.write_json(meta_path, meta)
    return manifest


def run_document_ingest(
    source_path: Path,
    *,
    original_filename: str,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
    doc_id: Optional[str] = None,
    on_event: Optional[EventCallback] = None,
) -> DocumentManifest:
    ext = Path(original_filename).suffix.lower()
    if ext not in SUPPORTED_EXTENSIONS:
        raise ValueError(
            f"Unsupported file type '{ext}'. Supported: "
            + ", ".join(sorted(SUPPORTED_EXTENSIONS))
        )

    doc_id = doc_id or store.new_doc_id()
    root = store.init_document(
        doc_id,
        source_filename=original_filename,
        user_id=user_id,
        user_email=user_email,
        user_name=user_name,
    )

    safe_name = store.safe_filename(original_filename)
    dest = root / "source" / safe_name
    if source_path.resolve() != dest.resolve():
        dest.write_bytes(source_path.read_bytes())

    def emit(etype: str, message: str, data: Optional[dict[str, Any]] = None) -> None:
        if on_event:
            on_event(etype, message, data)

    created_at = datetime.now(timezone.utc).isoformat()
    title = Path(original_filename).stem.strip() or "Document"
    expected = count_document_pages(dest)
    slides: list[DocumentSlide] = []
    blocks: dict[str, DocumentBlock] = {}
    md_parts: list[str] = []
    raw_parts: list[str] = []
    block_counter = 0
    errors: list[str] = []

    emit(
        "status",
        (
            f"Converting page-by-page ({expected} pages)…"
            if expected
            else "Converting document…"
        ),
        {"doc_id": doc_id, "expected_pages": expected, "status": "converting"},
    )
    _persist_partial(
        doc_id,
        title=title,
        source_filename=original_filename,
        ext=ext,
        status="converting",
        slides=slides,
        blocks=blocks,
        created_at=created_at,
        expected_pages=expected,
    )

    page_index = 0
    for page_no, total, converted in iter_convert_pages(dest):
        if not converted.ok:
            errors.append(f"page {page_no}: {converted.error}")
            emit(
                "status",
                f"Page {page_no}/{total} failed — continuing…",
                {
                    "doc_id": doc_id,
                    "page": page_no,
                    "total": total,
                    "error": converted.error,
                },
            )
            continue

        if converted.title and title in {
            original_filename,
            Path(original_filename).stem,
        }:
            title = converted.title.strip() or title

        mapping = write_assets_namespaced(
            converted.assets,
            root / "assets",
            prefix=f"p{page_no:03d}",
        )
        html = rewrite_html_asset_names(converted.html or "", mapping)
        pages_html = [
            rewrite_html_asset_names(p, mapping) for p in (converted.pages_html or [])
        ]
        if converted.markdown:
            md_parts.append(converted.markdown)

        chunk_pages = split_pages_html(html, pages_html or None)
        multi_from_full = total == 1 and len(chunk_pages) > 1

        for chunk in chunk_pages:
            slide, page_blocks, block_counter = enrich_single_page(
                chunk,
                doc_id=doc_id,
                title=title,
                page_index=page_index,
                start_block_counter=block_counter,
            )
            write_slides([slide], slides_dir=root / "slides")
            slides.append(slide)
            blocks.update(page_blocks)
            raw_parts.append(chunk)
            page_index += 1

            _persist_partial(
                doc_id,
                title=title,
                source_filename=original_filename,
                ext=ext,
                status="converting",
                slides=slides,
                blocks=blocks,
                created_at=created_at,
                expected_pages=expected or total,
            )
            emit(
                "slide_ready",
                f"Slide {len(slides)} ready"
                + (f" ({page_no}/{total})" if total else ""),
                {
                    "doc_id": doc_id,
                    "title": title,
                    "slide": _slim_slide(slide).model_dump(),
                    "slide_count": len(slides),
                    "page": page_no,
                    "total": total,
                    "expected_pages": expected or total,
                    "status": "converting",
                },
            )

        if multi_from_full:
            break

    if not slides:
        msg = "; ".join(errors) if errors else "Docling conversion produced no slides"
        _persist_partial(
            doc_id,
            title=title,
            source_filename=original_filename,
            ext=ext,
            status="error",
            slides=[],
            blocks={},
            created_at=created_at,
            expected_pages=expected,
        )
        emit("error", msg, {"doc_id": doc_id})
        raise RuntimeError(msg)

    (root / "document.md").write_text("\n\n".join(md_parts), encoding="utf-8")
    (root / "raw.html").write_text("\n".join(raw_parts), encoding="utf-8")
    base.write_json(root / "result.json", {"kind": "document", "doc_id": doc_id})

    manifest = _persist_partial(
        doc_id,
        title=title,
        source_filename=original_filename,
        ext=ext,
        status="ready",
        slides=slides,
        blocks=blocks,
        created_at=created_at,
        expected_pages=expected,
    )
    emit(
        "complete",
        f"Ready — {manifest.slide_count} slide(s)",
        {
            "doc_id": doc_id,
            "title": title,
            "slide_count": manifest.slide_count,
            "status": "ready",
        },
    )
    return manifest


def iter_document_ingest_events(
    source_path: Path,
    *,
    original_filename: str,
    user_id: Optional[str] = None,
    user_email: Optional[str] = None,
    user_name: Optional[str] = None,
) -> Iterator[str]:
    """Yield SSE chunks as each page/slide becomes ready (true streaming)."""
    q: queue.Queue[Optional[str]] = queue.Queue()

    def encode(etype: str, message: str, data: Optional[dict[str, Any]] = None) -> str:
        return (
            f"data: {json.dumps({'type': etype, 'message': message, 'data': data})}\n\n"
        )

    def on_event(
        etype: str, message: str, data: Optional[dict[str, Any]] = None
    ) -> None:
        q.put(encode(etype, message, data))

    def worker() -> None:
        try:
            run_document_ingest(
                source_path,
                original_filename=original_filename,
                user_id=user_id,
                user_email=user_email,
                user_name=user_name,
                on_event=on_event,
            )
        except Exception as exc:  # noqa: BLE001
            q.put(encode("error", str(exc), None))
        finally:
            q.put(None)

    thread = threading.Thread(target=worker, daemon=True)
    thread.start()
    while True:
        item = q.get()
        if item is None:
            break
        yield item
    thread.join(timeout=1.0)


def ask_document_block(
    doc_id: str,
    request: DocumentAskRequest,
    *,
    user_id: Optional[str] = None,
) -> DocumentAskResult:
    manifest = store.load_manifest(doc_id)
    if manifest.status not in {"ready", "converting"}:
        raise RuntimeError(f"Document is not ready (status={manifest.status})")
    if request.slide_id not in {s.id for s in manifest.slides}:
        raise ValueError(f"Slide not ready yet: {request.slide_id}")

    client = OpenRouterClient()
    result = ask_on_manifest(
        client,
        manifest,
        request,
        root=store.doc_dir(doc_id),
    )
    if user_id:
        db.flush_client_usage(
            user_id=user_id,
            job_id=doc_id,
            usage_log=client.drain_usage_log(),
        )
    return result
