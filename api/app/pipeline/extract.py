"""specs/05-redaction-pipeline.md Stage 2: Extraction. Born-digital PDF path only for
Phase 1 (PyMuPDF text+coords) — the Textract/Tesseract OCR path for scanned PDFs is not
implemented yet; pages with no text layer are flagged `has_text_layer=False` /
`ocr_confidence=None` so the review UI can force manual attention on them (Phase 3+ wires
real OCR; specs/05-redaction-pipeline.md already calls for "never mark such pages
auto-complete").

Coordinate space matches the canonical one specs/05-redaction-pipeline.md requires: PDF
points, origin top-left — PyMuPDF's native `page.get_text()`/`page.rect` space, no
conversion needed. Known gap (tracked, not silently ignored): rotated pages are not
coordinate-normalized yet — specs/10-build-plan.md's own risk register lists this as a
Phase 6 hardening item, not a Phase 1 blocker.
"""

from dataclasses import dataclass

import fitz  # PyMuPDF

PREVIEW_DPI = 150


@dataclass
class WordBox:
    text: str
    x0: float
    y0: float
    x1: float
    y1: float


@dataclass
class PageExtraction:
    page_no: int  # 1-indexed, matches specs/03-data-model.md document_pages.page_no
    width: float
    height: float
    rotation: int
    has_text_layer: bool
    full_text: str
    word_spans: list[tuple[int, int, WordBox]]  # (char_start, char_end) into full_text
    preview_png: bytes


def _words_and_text(page: fitz.Page) -> tuple[str, list[tuple[int, int, WordBox]]]:
    raw_words = page.get_text("words")  # x0,y0,x1,y1,word,block_no,line_no,word_no
    full_text_parts: list[str] = []
    spans: list[tuple[int, int, WordBox]] = []
    cursor = 0
    for x0, y0, x1, y1, word, *_ in raw_words:
        if full_text_parts:
            full_text_parts.append(" ")
            cursor += 1
        start = cursor
        full_text_parts.append(word)
        cursor += len(word)
        spans.append((start, cursor, WordBox(word, x0, y0, x1, y1)))
    return "".join(full_text_parts), spans


def extract_pdf(data: bytes) -> list[PageExtraction]:
    doc = fitz.open(stream=data, filetype="pdf")
    try:
        pages = []
        for i, page in enumerate(doc):
            full_text, word_spans = _words_and_text(page)
            pixmap = page.get_pixmap(dpi=PREVIEW_DPI)
            pages.append(
                PageExtraction(
                    page_no=i + 1,
                    width=page.rect.width,
                    height=page.rect.height,
                    rotation=page.rotation,
                    has_text_layer=len(full_text.strip()) > 0,
                    full_text=full_text,
                    word_spans=word_spans,
                    preview_png=pixmap.tobytes("png"),
                )
            )
        return pages
    finally:
        doc.close()


def span_to_bbox(word_spans: list[tuple[int, int, WordBox]], start: int, end: int) -> dict | None:
    """Union the bboxes of every word overlapping [start, end) in the page's full_text."""
    covering = [wb for (ws, we, wb) in word_spans if ws < end and we > start]
    if not covering:
        return None
    x0 = min(w.x0 for w in covering)
    y0 = min(w.y0 for w in covering)
    x1 = max(w.x1 for w in covering)
    y1 = max(w.y1 for w in covering)
    return {"x": x0, "y": y0, "w": x1 - x0, "h": y1 - y0}
