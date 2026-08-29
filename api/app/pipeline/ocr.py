"""specs/05-redaction-pipeline.md Stage 2: OCR path for scanned/image pages (no native
PDF text layer). Textract first, via its synchronous single-page `detect_document_text`
API rather than the spec's async multi-page job API - app/pipeline/extract.py already
renders each page to a PNG for previews, so reusing that image per page solves the same
problem without standing up S3-round-trip + SNS/polling infra for it. Tesseract (fully
local, no AWS call) is the fallback when Textract errors, matching specs/05's "Tesseract
fallback if Textract errors."

Word-level bounding boxes come back in different coordinate spaces per engine - Textract
returns fractions (0-1) of the image's width/height; Tesseract returns pixel offsets at
whatever DPI the image was rendered. Both are converted here to the canonical PDF-point,
origin-top-left space app/pipeline/extract.py's born-digital path already uses (see its
own module docstring), so nothing downstream (detect.py/merge.py/export.py) needs to
know or care which engine - or neither - produced a given page's text.
"""

import io
import logging
from dataclasses import dataclass

import pytesseract
from PIL import Image

from app.pipeline.word_box import WordBox

logger = logging.getLogger(__name__)

_RawWord = tuple[str, float, float, float, float, float]  # text, x0, y0, x1, y1, confidence(0-100)


@dataclass
class OcrResult:
    full_text: str
    word_spans: list[tuple[int, int, WordBox]]
    confidence: float  # 0-1, mean per-word confidence - specs/05: "pages < 0.6 flagged"


def _build_result(words: list[_RawWord]) -> OcrResult:
    full_text_parts: list[str] = []
    spans: list[tuple[int, int, WordBox]] = []
    confidences: list[float] = []
    cursor = 0
    for text, x0, y0, x1, y1, confidence in words:
        if not text.strip():
            continue
        if full_text_parts:
            full_text_parts.append(" ")
            cursor += 1
        start = cursor
        full_text_parts.append(text)
        cursor += len(text)
        spans.append((start, cursor, WordBox(text, x0, y0, x1, y1)))
        confidences.append(confidence)
    mean_confidence = (sum(confidences) / len(confidences) / 100.0) if confidences else 0.0
    return OcrResult(full_text="".join(full_text_parts), word_spans=spans, confidence=mean_confidence)


def _ocr_via_textract(png_bytes: bytes, page_width_pt: float, page_height_pt: float) -> OcrResult:
    import boto3

    client = boto3.client("textract")
    response = client.detect_document_text(Document={"Bytes": png_bytes})
    words: list[_RawWord] = []
    for block in response.get("Blocks", []):
        if block.get("BlockType") != "WORD":
            continue
        bbox = block["Geometry"]["BoundingBox"]
        x0 = bbox["Left"] * page_width_pt
        y0 = bbox["Top"] * page_height_pt
        x1 = x0 + bbox["Width"] * page_width_pt
        y1 = y0 + bbox["Height"] * page_height_pt
        words.append((block.get("Text", ""), x0, y0, x1, y1, block.get("Confidence", 0.0)))
    return _build_result(words)


def _ocr_via_tesseract(png_bytes: bytes, dpi: int) -> OcrResult:
    image = Image.open(io.BytesIO(png_bytes))
    data = pytesseract.image_to_data(image, output_type=pytesseract.Output.DICT)
    scale = 72.0 / dpi  # PDF points <- pixels rendered at `dpi`
    words: list[_RawWord] = []
    for i in range(len(data["text"])):
        text = data["text"][i]
        confidence = float(data["conf"][i])
        if not text.strip() or confidence < 0:  # tesseract uses conf=-1 for non-word layout blocks
            continue
        left, top, width, height = data["left"][i], data["top"][i], data["width"][i], data["height"][i]
        words.append((text, left * scale, top * scale, (left + width) * scale, (top + height) * scale, confidence))
    return _build_result(words)


def extract_page_via_ocr(png_bytes: bytes, page_width_pt: float, page_height_pt: float, dpi: int) -> OcrResult:
    try:
        return _ocr_via_textract(png_bytes, page_width_pt, page_height_pt)
    except Exception:
        logger.warning("ocr.textract_failed_falling_back_to_tesseract", exc_info=True, extra={"event": "ocr.textract_failed"})
        return _ocr_via_tesseract(png_bytes, dpi)
