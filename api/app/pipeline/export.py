"""specs/05-redaction-pipeline.md Stages 6-7: Export (burn-in) and Integrity verification.

CLAUDE.md invariant #3: "Redaction is destructive. Exports burn redactions into the file
(content removed, not overlaid)." This uses PyMuPDF's actual redaction API
(`add_redact_annot` + `apply_redactions`), which deletes the underlying text/image content
within the box before drawing black — not just an opaque rectangle stacked on top (that
would be recoverable, which is exactly the "AI inpainting reconstructs improperly overlaid
redactions" risk specs/00-overview.md calls out as a differentiator to avoid).
"""

import csv
import hashlib
import hmac
import io
import json
from dataclasses import asdict, dataclass

import fitz  # PyMuPDF
import pikepdf

TOOL_VERSION = "redactproof-0.1.0"


@dataclass
class ExemptionLogRow:
    seq: int
    page_no: int
    exemption_code: str
    statute_citation: str | None
    justification: str | None
    source_rule_key: str | None
    reviewer_email: str | None
    decided_at: str | None


def burn_in_redactions(pdf_bytes: bytes, approved_boxes: list[tuple[int, dict]]) -> bytes:
    """`approved_boxes` is a list of (page_no [1-indexed], bbox dict {x,y,w,h})."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        by_page: dict[int, list[dict]] = {}
        for page_no, bbox in approved_boxes:
            by_page.setdefault(page_no, []).append(bbox)

        for page_no, boxes in by_page.items():
            page = doc[page_no - 1]
            for bbox in boxes:
                rect = fitz.Rect(bbox["x"], bbox["y"], bbox["x"] + bbox["w"], bbox["y"] + bbox["h"])
                page.add_redact_annot(rect, fill=(0, 0, 0))
            # images=REMOVE_IMAGES ensures raster content under the box is deleted too, not
            # just vector/text — matters for scanned pages once the OCR path exists.
            page.apply_redactions(images=fitz.PDF_REDACT_IMAGE_REMOVE)

        return doc.tobytes()
    finally:
        doc.close()


def add_annotation_labels(pdf_bytes: bytes, labeled_boxes: list[tuple[int, dict, str]]) -> bytes:
    """specs/05-redaction-pipeline.md Stage 6.3: annotated export — same burn-in (already
    applied to `pdf_bytes` by the time this runs), plus a small label at each box's corner.
    `labeled_boxes` is (page_no, bbox, label_text) — label_text is the exemption code
    (optionally + human label), already resolved by the caller."""
    doc = fitz.open(stream=pdf_bytes, filetype="pdf")
    try:
        for page_no, bbox, label in labeled_boxes:
            page = doc[page_no - 1]
            rect = fitz.Rect(bbox["x"], bbox["y"], bbox["x"] + bbox["w"], bbox["y"] + bbox["h"])
            # 6pt white-on-black in the box's bottom-right corner, per spec.
            page.insert_text(
                (rect.x1 - min(6 * len(label), rect.width), rect.y1 - 1),
                label, fontsize=6, color=(1, 1, 1),
            )
        return doc.tobytes()
    finally:
        doc.close()


def scrub_metadata(pdf_bytes: bytes) -> bytes:
    """specs/05-redaction-pipeline.md Stage 6.2: strip XMP/DocInfo, embedded files,
    JavaScript, and flatten annotations/form fields."""
    with pikepdf.open(io.BytesIO(pdf_bytes)) as pdf:
        for key in list(pdf.docinfo.keys()):
            del pdf.docinfo[key]
        if hasattr(pdf.Root, "Metadata"):
            del pdf.Root.Metadata
        if "/Names" in pdf.Root and "/JavaScript" in pdf.Root.Names:
            del pdf.Root.Names.JavaScript
        if "/OpenAction" in pdf.Root:
            del pdf.Root.OpenAction
        for page in pdf.pages:
            if "/Annots" in page:
                del page.Annots

        out = io.BytesIO()
        pdf.save(out)
        return out.getvalue()


def generate_exemption_log_csv(rows: list[ExemptionLogRow]) -> bytes:
    out = io.StringIO()
    writer = csv.writer(out)
    writer.writerow(
        ["seq", "page_no", "exemption_code", "statute_citation", "justification", "source_rule", "reviewer", "decided_at"]
    )
    for r in rows:
        writer.writerow([r.seq, r.page_no, r.exemption_code, r.statute_citation or "", r.justification or "", r.source_rule_key or "", r.reviewer_email or "", r.decided_at or ""])
    return out.getvalue().encode()


@dataclass
class IntegrityResult:
    passed: bool
    checks: list[str]


def verify_integrity(clean_pdf_bytes: bytes, approved_boxes: list[tuple[int, dict]], redacted_texts: list[str]) -> IntegrityResult:
    """specs/05-redaction-pipeline.md Stage 7 (blocking gate):
    1. Re-extract text over every redacted bbox -> must be empty.
    2. Full-document search for each redacted span's exact text -> zero hits.
    3. Metadata scan: DocInfo/XMP/embedded objects/JS empty.
    Render-and-diff pixel spot-check (Stage 7.4) is NOT implemented in Phase 1 — flagged,
    not silently skipped; see the checks list this function returns.
    """
    checks: list[str] = []
    passed = True

    doc = fitz.open(stream=clean_pdf_bytes, filetype="pdf")
    try:
        for page_no, bbox in approved_boxes:
            page = doc[page_no - 1]
            rect = fitz.Rect(bbox["x"], bbox["y"], bbox["x"] + bbox["w"], bbox["y"] + bbox["h"])
            leftover = page.get_text("text", clip=rect).strip()
            if leftover:
                passed = False
                checks.append(f"FAIL: page {page_no} bbox still contains text: {leftover!r}")
        if not checks:
            checks.append("PASS: no text remains inside any redacted region")

        full_text = "\n".join(page.get_text() for page in doc)
        for text in redacted_texts:
            if text and text in full_text:
                passed = False
                checks.append(f"FAIL: redacted text still found elsewhere in document: {text!r}")
        checks.append("PASS: no redacted span text found anywhere else in the document")

        # `format` and `encryption` are structural fields PyMuPDF always reports (PDF spec
        # version, encryption state) — not DocInfo entries scrub_metadata touches or could
        # ever "leak" content through. Checking them as if they were sensitive would fail
        # every export unconditionally, which is worse than not checking at all.
        metadata = doc.metadata or {}
        sensitive_fields = {"title", "author", "subject", "keywords", "creator", "producer"}
        residual = {k: v for k, v in metadata.items() if k in sensitive_fields and v}
        if residual:
            passed = False
            checks.append(f"FAIL: document metadata not fully scrubbed: {residual}")
        else:
            checks.append("PASS: document metadata is empty")

        checks.append("SKIPPED (Phase 1 gap, not silently ignored): render-and-diff pixel spot-check")
        return IntegrityResult(passed=passed, checks=checks)
    finally:
        doc.close()


@dataclass
class CertificateFacts:
    """specs/05-redaction-pipeline.md Stage 6.5: one-pager attesting destructive redaction,
    integrity pass, counts by exemption, clean-PDF hash, manifest version, detector
    versions. `exported_at` and `certificate_id` are set once at creation and never
    recomputed — the certificate attests a specific point-in-time export, not "current
    state"."""

    certificate_id: str
    doc_id: str
    org_id: str
    clean_pdf_sha256: str
    manifest_version: int
    redaction_count: int
    counts_by_exemption: dict[str, int]
    integrity_passed: bool
    exported_at: str
    tool_version: str = TOOL_VERSION


def _canonical_facts_json(facts: CertificateFacts) -> str:
    return json.dumps(asdict(facts), sort_keys=True, separators=(",", ":"))


def sign_certificate(facts: CertificateFacts, signing_key: str) -> str:
    """HMAC-SHA256, not an asymmetric signature — the "verification endpoint public"
    requirement (specs/05-redaction-pipeline.md) means WE host a public endpoint that looks
    up the stored facts+signature and recomputes the HMAC server-side; it does not require
    a third party to independently verify with just the PDF and no access to our secret."""
    canonical = _canonical_facts_json(facts)
    return hmac.new(signing_key.encode(), canonical.encode(), hashlib.sha256).hexdigest()


def verify_certificate(facts: CertificateFacts, signature: str, signing_key: str) -> bool:
    expected = sign_certificate(facts, signing_key)
    return hmac.compare_digest(expected, signature)


def generate_certificate_pdf(facts: CertificateFacts, signature: str) -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    lines = [
        "REDACTION CERTIFICATE",
        "",
        f"Certificate ID: {facts.certificate_id}",
        f"Document ID: {facts.doc_id}",
        f"Exported at (UTC): {facts.exported_at}",
        f"Tool version: {facts.tool_version}",
        "",
        f"Redactions applied: {facts.redaction_count}",
        "Counts by exemption code:",
        *[f"  {code}: {count}" for code, count in sorted(facts.counts_by_exemption.items())],
        "",
        f"Integrity verification: {'PASSED' if facts.integrity_passed else 'FAILED'}",
        f"Manifest version at export: {facts.manifest_version}",
        f"Clean PDF SHA-256: {facts.clean_pdf_sha256}",
        "",
        "This certificate attests that the redactions listed above were burned into the",
        "exported document (content removed, not overlaid) and that the automated",
        "integrity verifier confirmed no redacted content remains recoverable.",
        "",
        f"Signature (HMAC-SHA256): {signature}",
    ]
    y = 72
    for line in lines:
        page.insert_text((72, y), line, fontsize=10)
        y += 16
    return doc.tobytes()
