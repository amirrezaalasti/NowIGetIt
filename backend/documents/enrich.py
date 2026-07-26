"""Turn Docling HTML into selectable per-slide DOM with stable block ids."""

from __future__ import annotations

import re
from html.parser import HTMLParser
from pathlib import Path
from urllib.parse import unquote

from backend.documents.schemas import DocumentBlock, DocumentBlockType, DocumentSlide

_BLOCK_TAGS = {
    "h1": DocumentBlockType.heading,
    "h2": DocumentBlockType.heading,
    "h3": DocumentBlockType.heading,
    "h4": DocumentBlockType.heading,
    "h5": DocumentBlockType.heading,
    "h6": DocumentBlockType.heading,
    "p": DocumentBlockType.paragraph,
    "li": DocumentBlockType.list,
    "table": DocumentBlockType.table,
    "figure": DocumentBlockType.figure,
    "img": DocumentBlockType.figure,
    "pre": DocumentBlockType.code,
    "math": DocumentBlockType.formula,
    "div": DocumentBlockType.formula,
}


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []

    def handle_data(self, data: str) -> None:
        text = data.strip()
        if text:
            self.parts.append(text)

    def get_text(self) -> str:
        return " ".join(self.parts)


def html_to_text(html: str) -> str:
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001
        return re.sub(r"<[^>]+>", " ", html)
    return parser.get_text()


def split_pages_html(full_html: str, pages_html: list[str] | None = None) -> list[str]:
    if pages_html:
        cleaned = [p.strip() for p in pages_html if p and p.strip()]
        if cleaned:
            return cleaned

    patterns = [
        r'(?is)<div[^>]*class=["\'][^"\']*\bpage\b[^"\']*["\'][^>]*>.*?</div>',
        r'(?is)<section[^>]*class=["\'][^"\']*\bpage\b[^"\']*["\'][^>]*>.*?</section>',
    ]
    for pattern in patterns:
        matches = re.findall(pattern, full_html)
        if len(matches) >= 2:
            return matches

    parts = re.split(
        r'(?is)<hr[^>]*class=["\'][^"\']*page-break[^"\']*["\'][^>]*/?>',
        full_html,
    )
    parts = [p.strip() for p in parts if p and p.strip()]
    if len(parts) >= 2:
        return parts

    body = _extract_body(full_html)
    heading_splits = re.split(r"(?i)(?=<h1\b)", body)
    heading_splits = [p.strip() for p in heading_splits if p and p.strip()]
    if len(heading_splits) >= 2:
        return heading_splits

    return [body or full_html]


def _extract_body(html: str) -> str:
    m = re.search(r"(?is)<body[^>]*>(.*)</body>", html)
    if m:
        return m.group(1).strip()
    return html.strip()


def _extract_styles(html: str) -> str:
    """Keep Docling <style> blocks so formulas/tables keep their layout."""
    return "\n".join(re.findall(r"(?is)<style[^>]*>.*?</style>", html or ""))


def _clean_pdf_bullets(html: str) -> str:
    """Replace PDF private-use / dingbat bullets that render as weird icons."""
    # Leading symbol bullets inside list items / paragraphs
    html = re.sub(
        r"(?is)(<(?:li|p)[^>]*>)\s*"
        r"(?:[●○•◦▪▫■□◆◇►▶➢➔➜➔➔]|&[a-z]+;|&#\d+;)\s*",
        r"\1",
        html,
    )
    # Private-use area chars often used as list markers in PPT/PDF text
    html = re.sub(r"[\uf000-\uf8ff]", "", html)
    return html


def _guess_title(html: str, fallback: str) -> str:
    for tag in ("h1", "h2", "title"):
        m = re.search(rf"(?is)<{tag}[^>]*>(.*?)</{tag}>", html)
        if m:
            text = html_to_text(m.group(1)).strip()
            if text:
                return text[:160]
    text = html_to_text(html).strip()
    if text:
        return text[:80] + ("…" if len(text) > 80 else "")
    return fallback


def _rewrite_asset_urls(html: str, *, doc_id: str) -> str:
    def repl(match: re.Match[str]) -> str:
        attr = match.group(1)
        quote = match.group(2)
        src = match.group(3)
        if src.startswith(("http://", "https://", "data:", "/api/")):
            return match.group(0)
        name = Path(unquote(src)).name
        return f"{attr}={quote}/api/jobs/{doc_id}/file/assets/{name}{quote}"

    return re.sub(r'(?i)\b(src|href)=([\'"])([^\'"]+)\2', repl, html)


def _annotate_blocks(
    page_html: str,
    *,
    slide_id: str,
    start_counter: int,
) -> tuple[str, dict[str, DocumentBlock], int]:
    blocks: dict[str, DocumentBlock] = {}
    counter = start_counter
    parts: list[str] = []
    pos = 0
    tag_re = re.compile(
        r"(?is)<(h[1-6]|p|li|table|figure|img|pre|math|"
        r"div(?=[^>]*\bformula\b))(\s[^>]*)?>"
    )

    for match in tag_re.finditer(page_html):
        start = match.start()
        if start < pos:
            continue
        if start > pos:
            parts.append(page_html[pos:start])

        tag = match.group(1).lower()
        attrs = match.group(2) or ""
        if "data-block-id=" in attrs:
            parts.append(match.group(0))
            pos = match.end()
            continue

        counter += 1
        block_id = f"b{counter:04d}"
        btype = _BLOCK_TAGS.get(tag, DocumentBlockType.other)
        self_closing = tag == "img" or match.group(0).rstrip().endswith("/>")

        if self_closing:
            end = match.end()
            element_html = (
                f'<{tag}{attrs} data-block-id="{block_id}" '
                f'data-block-type="{btype.value}" tabindex="0" '
                f'class="nig-block nig-block-{btype.value}" />'
            )
        else:
            close = re.search(rf"(?is)</{tag}\s*>", page_html[match.end() :])
            end = match.end() + close.end() if close else match.end()
            inner = page_html[match.end() : end]
            element_html = (
                f'<{tag}{attrs} data-block-id="{block_id}" '
                f'data-block-type="{btype.value}" tabindex="0" '
                f'class="nig-block nig-block-{btype.value}">'
                f"{inner}"
            )

        parts.append(element_html)

        text = html_to_text(element_html)
        image_path = None
        image_url = None
        src_m = re.search(r'(?i)\bsrc=[\'"]([^\'"]+)[\'"]', element_html)
        if src_m:
            image_url = src_m.group(1)
            if "/file/assets/" in image_url:
                image_path = "assets/" + image_url.rsplit("/file/assets/", 1)[-1]
        if btype == DocumentBlockType.figure and not text:
            text = "[figure]"

        blocks[block_id] = DocumentBlock(
            id=block_id,
            slide_id=slide_id,
            type=btype,
            text=text[:4000],
            html_snippet=element_html[:8000],
            image_path=image_path,
            image_url=image_url,
        )
        pos = end

    parts.append(page_html[pos:])
    return "".join(parts), blocks, counter


def enrich_single_page(
    page_html: str,
    *,
    doc_id: str,
    title: str,
    page_index: int,
    start_block_counter: int = 0,
) -> tuple[DocumentSlide, dict[str, DocumentBlock], int]:
    """Enrich one page into a selectable slide. page_index is 0-based."""
    slide_id = f"slide_{page_index + 1:03d}"
    docling_styles = _extract_styles(page_html)
    body = _extract_body(page_html)
    body = _clean_pdf_bullets(body)
    rewritten = _rewrite_asset_urls(body, doc_id=doc_id)
    # Also annotate formula containers from Docling
    rewritten = re.sub(
        r'(?is)<(div)(\s[^>]*class=["\'][^"\']*\bformula\b[^"\']*["\'][^>]*)>',
        r'<\1\2 data-nig-formula="1">',
        rewritten,
    )
    body_html, page_blocks, counter = _annotate_blocks(
        rewritten, slide_id=slide_id, start_counter=start_block_counter
    )
    # Promote formula divs to formula block type when annotated as blocks via p/div miss
    for bid, block in list(page_blocks.items()):
        if "formula" in (block.html_snippet or "").lower() or "<math" in (
            block.html_snippet or ""
        ).lower():
            page_blocks[bid] = block.model_copy(update={"type": DocumentBlockType.formula})

    slide_html = _wrap_slide_html(
        body_html,
        slide_id=slide_id,
        title=title,
        extra_styles=docling_styles,
    )
    slide = DocumentSlide(
        id=slide_id,
        index=page_index,
        title=_guess_title(body_html, f"Slide {page_index + 1}"),
        html=slide_html,
        html_url=f"/api/jobs/{doc_id}/file/slides/{slide_id}.html",
        plain_text=html_to_text(body_html)[:12000],
        block_ids=list(page_blocks.keys()),
    )
    return slide, page_blocks, counter


def enrich_pages(
    pages: list[str],
    *,
    doc_id: str,
    title: str,
    start_index: int = 0,
    start_block_counter: int = 0,
) -> tuple[list[DocumentSlide], dict[str, DocumentBlock]]:
    slides: list[DocumentSlide] = []
    blocks: dict[str, DocumentBlock] = {}
    counter = start_block_counter

    for offset, raw in enumerate(pages):
        slide, page_blocks, counter = enrich_single_page(
            raw,
            doc_id=doc_id,
            title=title,
            page_index=start_index + offset,
            start_block_counter=counter,
        )
        slides.append(slide)
        blocks.update(page_blocks)

    return slides, blocks


def _wrap_slide_html(
    body: str,
    *,
    slide_id: str,
    title: str,
    extra_styles: str = "",
) -> str:
    # Always light, high-contrast slide chrome. Docling content is authored for
    # a white page; following prefers-color-scheme made body text light-on-white.
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8" />
  <meta name="viewport" content="width=device-width, initial-scale=1" />
  <title>{_escape(title)} — {slide_id}</title>
  {extra_styles}
  <style>
    :root {{
      color-scheme: light;
      --nig-ink: #1a1f1c;
      --nig-muted: #4a6358;
      --nig-line: rgba(18, 32, 27, 0.16);
      --nig-accent: #1f9a66;
      --nig-bg: #ffffff;
      --nig-select: rgba(31, 154, 102, 0.14);
    }}
    html, body {{
      margin: 0; padding: 0;
      background: var(--nig-bg) !important;
      color: var(--nig-ink) !important;
      font: 16px/1.55 ui-sans-serif, system-ui, "Segoe UI", sans-serif;
    }}
    .nig-slide {{
      box-sizing: border-box;
      min-height: 100vh;
      padding: 1.75rem 1.5rem 3rem;
      max-width: 56rem;
      margin: 0 auto;
      color: var(--nig-ink);
      background: #fff;
    }}
    .nig-slide, .nig-slide * {{
      color: inherit;
    }}
    .nig-slide a {{ color: #0b6e4f; }}
    .nig-slide h1, .nig-slide h2, .nig-slide h3,
    .nig-slide h4, .nig-slide h5, .nig-slide h6 {{
      color: #15201b !important;
      line-height: 1.25;
    }}
    .nig-slide p, .nig-slide li, .nig-slide td, .nig-slide th,
    .nig-slide figcaption, .nig-slide span {{
      color: #1a1f1c !important;
    }}
    .nig-slide ul, .nig-slide ol {{
      padding-left: 1.35rem;
    }}
    .nig-slide li {{
      margin: 0.35em 0;
      list-style: disc;
    }}
    .nig-slide img, .nig-slide svg {{
      max-width: 100%;
      height: auto;
      display: inline-block;
    }}
    .nig-slide figure {{
      margin: 1.25rem 0;
      text-align: center;
    }}
    .nig-slide table {{
      border-collapse: collapse;
      width: 100%;
      margin: 1rem 0;
    }}
    .nig-slide th, .nig-slide td {{
      border: 1px solid var(--nig-line);
      padding: 0.4rem 0.55rem;
    }}
    .nig-slide .formula, .nig-slide math {{
      display: block;
      overflow-x: auto;
      margin: 0.85rem 0;
      padding: 0.65rem 0.75rem;
      background: #f4f7f5;
      border-radius: 0.4rem;
      font-size: 1.05em;
    }}
    .nig-block {{
      border-radius: 0.35rem;
      transition: background 0.15s ease, outline-color 0.15s ease;
      cursor: pointer;
    }}
    .nig-block:hover {{ background: var(--nig-select); }}
    .nig-block.nig-selected {{
      outline: 2px solid var(--nig-accent);
      background: var(--nig-select);
    }}
    img.nig-block {{ display: inline-block; max-width: 100%; }}
  </style>
</head>
<body>
  <article class="nig-slide" data-slide-id="{slide_id}">
    {body}
  </article>
  <script>
    (function () {{
      function clear() {{
        document.querySelectorAll(".nig-selected").forEach(function (el) {{
          el.classList.remove("nig-selected");
        }});
      }}
      function select(el) {{
        clear();
        el.classList.add("nig-selected");
        var img = el.tagName === "IMG" ? el : el.querySelector("img");
        var payload = {{
          type: "nig-block-select",
          slideId: {slide_id!r},
          blockId: el.getAttribute("data-block-id"),
          blockType: el.getAttribute("data-block-type") || "other",
          text: (el.innerText || "").trim().slice(0, 4000),
          imageSrc: img ? img.getAttribute("src") : null
        }};
        if (window.parent) window.parent.postMessage(payload, "*");
      }}
      document.addEventListener("click", function (e) {{
        var el = e.target && e.target.closest
          ? e.target.closest("[data-block-id]") : null;
        if (!el) return;
        e.preventDefault();
        select(el);
      }});
    }})();
  </script>
</body>
</html>
"""


def _escape(value: str) -> str:
    return (
        value.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def write_slides(slides: list[DocumentSlide], *, slides_dir: Path) -> None:
    slides_dir.mkdir(parents=True, exist_ok=True)
    for slide in slides:
        (slides_dir / f"{slide.id}.html").write_text(slide.html, encoding="utf-8")
