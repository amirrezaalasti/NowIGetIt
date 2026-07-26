"""Unit tests for document HTML enrichment (no Docling required)."""

from __future__ import annotations

from backend.documents.enrich import (
    enrich_pages,
    enrich_single_page,
    html_to_text,
    split_pages_html,
)


def test_split_and_enrich_pages():
    html = """
    <html><body>
      <div class="page"><h1>Heat</h1><p>Conduction moves energy.</p>
      <img src="plot.png" alt="plot"/></div>
      <div class="page"><h2>Next</h2><table><tr><td>1</td></tr></table></div>
    </body></html>
    """
    pages = split_pages_html(html)
    assert len(pages) == 2
    slides, blocks = enrich_pages(pages, doc_id="doc_abc", title="Heat")
    assert len(slides) == 2
    assert slides[0].html_url.endswith("/slides/slide_001.html")
    assert "data-block-id=" in slides[0].html
    assert "nig-block-select" in slides[0].html
    assert any(b.type.value == "figure" for b in blocks.values())
    assert any(b.type.value == "table" for b in blocks.values())
    assert "Conduction" in html_to_text(slides[0].html)


def test_heading_split_fallback():
    html = "<h1>A</h1><p>one</p><h1>B</h1><p>two</p>"
    pages = split_pages_html(html)
    assert len(pages) == 2


def test_enrich_single_page_incremental_ids():
    slide1, blocks1, c1 = enrich_single_page(
        "<h1>One</h1><p>alpha</p>",
        doc_id="doc_x",
        title="Doc",
        page_index=0,
        start_block_counter=0,
    )
    slide2, blocks2, c2 = enrich_single_page(
        "<h1>Two</h1><p>beta</p>",
        doc_id="doc_x",
        title="Doc",
        page_index=1,
        start_block_counter=c1,
    )
    assert slide1.id == "slide_001"
    assert slide2.id == "slide_002"
    assert set(blocks1) & set(blocks2) == set()
    assert c2 > c1
