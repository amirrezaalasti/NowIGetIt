"""Docling conversion: local when available, else Railway Docling worker.

Supports progressive page-by-page conversion so the UI can show early slides.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import zipfile
from io import BytesIO
from pathlib import Path
from typing import Any, Iterator, Optional

import httpx

from backend.config import get_settings
from backend.documents.schemas import ConvertWorkerPayload

logger = logging.getLogger(__name__)

_PAGE_RANGE_EXTS = frozenset({".pdf", ".pptx", ".ppt", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif"})


def convert_document(source_path: Path) -> ConvertWorkerPayload:
    """Convert a local file to HTML/markdown via Docling (local or remote)."""
    settings = get_settings()
    worker_url = settings.docling_worker_url
    worker_mode = os.getenv("DOCLING_WORKER_MODE", "").lower() in {
        "1",
        "true",
        "yes",
    }

    if worker_url and not worker_mode:
        remote = _convert_remote(
            source_path,
            worker_url=worker_url,
            worker_secret=settings.docling_worker_secret,
        )
        if remote.ok:
            return remote
        logger.warning("Docling worker failed, trying local: %s", remote.error)
        local = _convert_local(source_path)
        if local.ok:
            return local
        return remote

    return _convert_local(source_path)


def iter_convert_pages(
    source_path: Path,
    *,
    page_from: int = 1,
    page_to: Optional[int] = None,
) -> Iterator[tuple[int, int, ConvertWorkerPayload]]:
    """
    Yield (page_no, total_pages, payload) as each page finishes.

    For PDFs/PPTX uses Docling page_range one page at a time.
    Otherwise falls back to a full convert and yields page 1 of 1.
    """
    settings = get_settings()
    worker_url = settings.docling_worker_url
    worker_mode = os.getenv("DOCLING_WORKER_MODE", "").lower() in {
        "1",
        "true",
        "yes",
    }
    use_remote = bool(worker_url) and not worker_mode
    ext = source_path.suffix.lower()
    total = count_document_pages(source_path)
    can_range = ext in _PAGE_RANGE_EXTS and total is not None and total >= 1

    if not can_range:
        payload = (
            _convert_remote(
                source_path,
                worker_url=worker_url,
                worker_secret=settings.docling_worker_secret,
            )
            if use_remote
            else _convert_local(source_path)
        )
        yield 1, 1, payload
        return

    assert total is not None
    start = max(1, page_from)
    end = min(total, page_to or total)

    if not use_remote:
        full_payload = _convert_local(source_path)
        if not full_payload.ok:
            yield 1, total, full_payload
            return

        pages_html = full_payload.pages_html or []
        actual_total = max(total, len(pages_html)) if pages_html else total
        if pages_html:
            for page_no in range(start, min(end, len(pages_html)) + 1):
                idx = page_no - 1
                page_html = pages_html[idx]
                page_payload = ConvertWorkerPayload(
                    ok=True,
                    html=page_html,
                    markdown=full_payload.markdown if page_no == start else "",
                    pages_html=[page_html],
                    assets=full_payload.assets if page_no == start else [],
                    title=full_payload.title,
                )
                yield page_no, actual_total, page_payload
            return
        else:
            yield 1, 1, full_payload
            return

    for page_no in range(start, end + 1):
        payload = _convert_remote(
            source_path,
            worker_url=worker_url,
            worker_secret=settings.docling_worker_secret,
            page_range=(page_no, page_no),
        )
        if not payload.ok and page_no == start:
            # Worker may not support page_range — fall back to full remote once.
            full = _convert_remote(
                source_path,
                worker_url=worker_url,
                worker_secret=settings.docling_worker_secret,
            )
            yield page_no, total, full
            return
        yield page_no, total, payload


def count_document_pages(source_path: Path) -> Optional[int]:
    """Best-effort page/slide count. None if unknown."""
    ext = source_path.suffix.lower()
    if ext == ".pdf":
        try:
            import pypdfium2 as pdfium

            pdf = pdfium.PdfDocument(str(source_path))
            try:
                return len(pdf)
            finally:
                pdf.close()
        except Exception as exc:  # noqa: BLE001
            logger.debug("PDF page count failed: %s", exc)
            return None
    if ext in {".pptx", ".ppt"}:
        try:
            with zipfile.ZipFile(source_path) as zf:
                names = zf.namelist()
            slides = [
                n
                for n in names
                if re.fullmatch(r"ppt/slides/slide\d+\.xml", n)
            ]
            return len(slides) or None
        except Exception as exc:  # noqa: BLE001
            logger.debug("PPTX slide count failed: %s", exc)
            return None
    if ext in {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".webp", ".bmp", ".gif"}:
        return 1
    return None


def _build_converter():
    from docling.document_converter import DocumentConverter

    do_ocr = os.getenv("DOCLING_DO_OCR", "false").lower() in {"1", "true", "yes"}
    do_formulas = os.getenv("DOCLING_FORMULA_ENRICHMENT", "true").lower() in {
        "1",
        "true",
        "yes",
    }
    images_scale = float(os.getenv("DOCLING_IMAGES_SCALE", "1.5") or "1.5")
    try:
        from docling.datamodel.base_models import InputFormat
        from docling.datamodel.pipeline_options import PdfPipelineOptions
        from docling.document_converter import PdfFormatOption

        pipeline_options = PdfPipelineOptions()
        pipeline_options.do_ocr = do_ocr
        # Required so export_to_html(EMBEDDED) can keep figures instead of placeholders.
        pipeline_options.generate_picture_images = True
        pipeline_options.generate_page_images = True
        pipeline_options.images_scale = images_scale
        # Decode LaTeX/math regions into enrichable formulas (MathML on export).
        pipeline_options.do_formula_enrichment = do_formulas
        return DocumentConverter(
            format_options={
                InputFormat.PDF: PdfFormatOption(pipeline_options=pipeline_options),
            }
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("Custom PdfPipelineOptions unavailable (%s); using defaults", exc)
        return DocumentConverter()


def _export_html(doc: Any, *, page_no: Optional[int] = None) -> str:
    """Export HTML with embedded images + MathML formulas (not placeholders)."""
    from docling_core.types.doc import ImageRefMode

    kwargs: dict[str, Any] = {
        "image_mode": ImageRefMode.EMBEDDED,
        "formula_to_mathml": True,
        "include_annotations": True,
    }
    if page_no is not None:
        kwargs["page_no"] = page_no
    try:
        return doc.export_to_html(**kwargs) or ""
    except TypeError:
        # Older docling-core without some kwargs
        try:
            if page_no is not None:
                return doc.export_to_html(
                    page_no=page_no, image_mode=ImageRefMode.EMBEDDED
                ) or ""
            return doc.export_to_html(image_mode=ImageRefMode.EMBEDDED) or ""
        except TypeError:
            if page_no is not None:
                try:
                    return doc.export_to_html(page_no=page_no) or ""
                except TypeError:
                    return ""
            return doc.export_to_html() or ""


def _convert_local(
    source_path: Path,
    *,
    page_range: Optional[tuple[int, int]] = None,
) -> ConvertWorkerPayload:
    try:
        from docling.document_converter import DocumentConverter  # noqa: F401
    except ImportError:
        return ConvertWorkerPayload(
            ok=False,
            error=(
                "Docling is not installed locally. Install with "
                "`pip install -r requirements-docling.txt` or set DOCLING_WORKER_URL."
            ),
        )

    try:
        converter = _build_converter()
        kwargs: dict[str, Any] = {}
        if page_range is not None:
            kwargs["page_range"] = page_range
        result = converter.convert(str(source_path), **kwargs)
        return _payload_from_docling_result(result, source_path)
    except Exception as exc:  # noqa: BLE001
        logger.exception("Local Docling convert failed (page_range=%s)", page_range)
        return ConvertWorkerPayload(ok=False, error=str(exc))


def _payload_from_docling_result(result: Any, source_path: Path) -> ConvertWorkerPayload:
    doc = result.document
    title = getattr(doc, "name", None) or source_path.stem
    markdown = ""
    html = ""
    pages_html: list[str] = []
    assets: list[dict[str, Any]] = []

    from docling_core.types.doc import ImageRefMode

    if hasattr(doc, "export_to_markdown"):
        try:
            markdown = (
                doc.export_to_markdown(image_mode=ImageRefMode.PLACEHOLDER) or ""
            )
        except TypeError:
            markdown = doc.export_to_markdown() or ""

    html = _export_html(doc)

    pages = getattr(doc, "pages", None) or {}
    page_nos: list[int] = []
    if isinstance(pages, dict):
        page_nos = sorted(int(k) for k in pages.keys())
    elif isinstance(pages, (list, tuple)):
        page_nos = list(range(1, len(pages) + 1))

    for page_no in page_nos:
        page_html = _export_html(doc, page_no=page_no)
        if page_html:
            pages_html.append(page_html)

    # Persist picture bytes for VLM explain + non-embedded fallbacks
    pictures = getattr(doc, "pictures", None) or []
    for i, pic in enumerate(pictures):
        try:
            pil = None
            if hasattr(pic, "get_image"):
                pil = pic.get_image(doc)
            if pil is None:
                img = getattr(pic, "image", None)
                pil = getattr(img, "pil_image", None) if img else None
            if pil is None:
                continue
            buf = BytesIO()
            pil.save(buf, format="PNG")
            assets.append(
                {
                    "name": f"figure_{i + 1:03d}.png",
                    "content_base64": base64.b64encode(buf.getvalue()).decode("ascii"),
                    "content_type": "image/png",
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.debug("Skip picture %s: %s", i, exc)

    # Also pull any data-URI images from HTML into assets (named by index)
    assets.extend(_extract_data_uri_assets(html, prefix="embed"))

    if not html and markdown:
        html = f"<article><pre>{_escape_html(markdown)}</pre></article>"

    if not html and not pages_html:
        return ConvertWorkerPayload(
            ok=False,
            error="Docling produced empty HTML/markdown.",
            log="empty export",
        )

    if not html and pages_html:
        html = "\n".join(pages_html)

    return ConvertWorkerPayload(
        ok=True,
        title=str(title),
        markdown=markdown,
        html=html,
        pages_html=pages_html,
        assets=assets,
        log=(
            f"local docling convert ok "
            f"(pictures={len(pictures)}, assets={len(assets)}, "
            f"img_tags={html.lower().count('<img')}, "
            f"math={html.lower().count('<math')})"
        ),
    )


def _extract_data_uri_assets(html: str, *, prefix: str) -> list[dict[str, Any]]:
    assets: list[dict[str, Any]] = []
    pattern = re.compile(
        r'(?is)<img[^>]+src=["\'](data:image/(png|jpeg|jpg|gif|webp);base64,([^"\']+))["\']'
    )
    for i, match in enumerate(pattern.finditer(html or ""), start=1):
        mime = match.group(2).lower()
        b64 = match.group(3)
        ext = "jpg" if mime in {"jpeg", "jpg"} else mime
        try:
            # Validate
            base64.b64decode(b64, validate=False)
        except Exception:  # noqa: BLE001
            continue
        assets.append(
            {
                "name": f"{prefix}_{i:03d}.{ext}",
                "content_base64": b64,
                "content_type": f"image/{'jpeg' if ext == 'jpg' else ext}",
            }
        )
    return assets


def _convert_remote(
    source_path: Path,
    *,
    worker_url: str,
    worker_secret: str,
    page_range: Optional[tuple[int, int]] = None,
) -> ConvertWorkerPayload:
    headers: dict[str, str] = {}
    if worker_secret:
        headers["Authorization"] = f"Bearer {worker_secret}"

    data: dict[str, str] = {}
    if page_range is not None:
        data["page_from"] = str(page_range[0])
        data["page_to"] = str(page_range[1])

    try:
        with httpx.Client(timeout=httpx.Timeout(600.0, connect=30.0)) as client:
            with source_path.open("rb") as fh:
                res = client.post(
                    f"{worker_url.rstrip('/')}/convert",
                    headers=headers,
                    data=data or None,
                    files={
                        "file": (
                            source_path.name,
                            fh,
                            "application/octet-stream",
                        )
                    },
                )
    except Exception as exc:  # noqa: BLE001
        return ConvertWorkerPayload(
            ok=False, error=f"Docling worker request failed: {exc}"
        )

    if res.status_code >= 400:
        return ConvertWorkerPayload(
            ok=False,
            error=f"Docling worker HTTP {res.status_code}: {res.text[:2000]}",
        )

    try:
        payload = res.json()
    except Exception as exc:  # noqa: BLE001
        return ConvertWorkerPayload(
            ok=False, error=f"Docling worker returned non-JSON: {exc}"
        )

    try:
        return ConvertWorkerPayload.model_validate(payload)
    except Exception as exc:  # noqa: BLE001
        return ConvertWorkerPayload(
            ok=False, error=f"Invalid worker payload: {exc}", log=str(payload)[:500]
        )


def write_assets(assets: list[dict[str, Any]], assets_dir: Path) -> set[str]:
    assets_dir.mkdir(parents=True, exist_ok=True)
    names: set[str] = set()
    for item in assets:
        name = str(item.get("name") or "").strip()
        b64 = item.get("content_base64")
        if not name or not b64:
            continue
        safe = Path(name).name
        # Namespace by hash of content when reusing figure_001 across pages
        raw = base64.b64decode(b64)
        (assets_dir / safe).write_bytes(raw)
        names.add(safe)
    return names


def write_assets_namespaced(
    assets: list[dict[str, Any]],
    assets_dir: Path,
    *,
    prefix: str,
) -> dict[str, str]:
    """Write assets with a prefix; return map original_name -> stored_name."""
    assets_dir.mkdir(parents=True, exist_ok=True)
    mapping: dict[str, str] = {}
    for item in assets:
        name = str(item.get("name") or "").strip()
        b64 = item.get("content_base64")
        if not name or not b64:
            continue
        original = Path(name).name
        stored = f"{prefix}_{original}"
        (assets_dir / stored).write_bytes(base64.b64decode(b64))
        mapping[original] = stored
        mapping[name] = stored
    return mapping


def rewrite_html_asset_names(html: str, mapping: dict[str, str]) -> str:
    if not mapping:
        return html

    def repl(match: re.Match[str]) -> str:
        attr, quote, src = match.group(1), match.group(2), match.group(3)
        base = Path(src).name
        if base in mapping:
            return f"{attr}={quote}{mapping[base]}{quote}"
        if src in mapping:
            return f"{attr}={quote}{mapping[src]}{quote}"
        return match.group(0)

    return re.sub(r'(?i)\b(src|href)=([\'"])([^\'"]+)\2', repl, html)


def _escape_html(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
    )
