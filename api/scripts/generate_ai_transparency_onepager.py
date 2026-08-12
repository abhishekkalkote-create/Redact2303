"""Phase 6 build-plan item: docs site's "security whitepaper," and
specs/08-security-compliance.md's transparency-artifacts list: "model inventory ...
accuracy report ... bias testing summary ... human-in-the-loop statement ... data-flow
diagram." These answer California EO N-5-26-style vendor AI certifications and local
AI-policy reviews — the audience is a records-office AI-policy reviewer, not a developer.

This is platform-level content (same document for every org, not per-tenant data), so it
generates as a static artifact rather than an authenticated API response — same
fitz-primitives approach as app/services/pilot_service.py's ROI PDF and
app/pipeline/export.py's certificate PDF (plain layout now; a design pass is a frontend
investment for later, not a reason to withhold it).

Deliberately honest about what's NOT true yet — an accuracy report or bias-testing
summary with invented numbers would be worse than no report at all, and specs/08 itself
frames this page as content that should track what's "actually built," not what's
planned (see web/src/app/security/page.tsx's own framing, which this document backs).

Usage: `python -m scripts.generate_ai_transparency_onepager` from /api with the venv
active. Writes to docs/ai-transparency/ (the repo path specs/08-security-compliance.md
names) and mirrors the same bytes into web/public/ so the marketing site can serve it.
"""

import sys
from datetime import UTC, datetime
from pathlib import Path

import fitz

PAGE_WIDTH = 612  # US Letter, points
MARGIN = 56
LINE_HEIGHT = 14.5
BODY_SIZE = 9.5
HEADING_SIZE = 12


def _draw_flow_diagram(page: fitz.Page, top: float) -> float:
    """Upload -> Extract -> Detect (deterministic + contextual) -> Human review -> Export
    -> Audit trail. Six boxes, five arrows — the data-flow diagram specs/08 calls for,
    drawn with fitz's own shape primitives rather than an embedded image."""
    stages = ["Upload", "Extract text", "Detect\n(rules + AI)", "Human\nreview", "Export\n(burn-in)", "Audit\ntrail"]
    box_w, box_h, gap = 78, 40, 10
    total_w = len(stages) * box_w + (len(stages) - 1) * gap
    x = (PAGE_WIDTH - total_w) / 2
    y = top

    for i, label in enumerate(stages):
        rect = fitz.Rect(x, y, x + box_w, y + box_h)
        page.draw_rect(rect, color=(0.15, 0.15, 0.15), fill=(0.95, 0.95, 0.95), width=1)
        lines = label.split("\n")
        line_y = y + box_h / 2 - (len(lines) - 1) * 5.5
        for line in lines:
            width = fitz.get_text_length(line, fontsize=8)
            page.insert_text((x + box_w / 2 - width / 2, line_y), line, fontsize=8)
            line_y += 11
        if i < len(stages) - 1:
            page.draw_line((x + box_w, y + box_h / 2), (x + box_w + gap, y + box_h / 2), color=(0.15, 0.15, 0.15), width=1)
        x += box_w + gap

    return y + box_h + 16


def _write_wrapped(page: fitz.Page, text: str, y: float, *, size: float = BODY_SIZE, bold: bool = False, max_width: float = PAGE_WIDTH - 2 * MARGIN) -> float:
    words = text.split(" ")
    line = ""
    for word in words:
        candidate = f"{line} {word}".strip()
        if fitz.get_text_length(candidate, fontsize=size) > max_width and line:
            page.insert_text((MARGIN, y), line, fontsize=size, fontname="helv" if not bold else "hebo")
            y += LINE_HEIGHT
            line = word
        else:
            line = candidate
    if line:
        page.insert_text((MARGIN, y), line, fontsize=size, fontname="helv" if not bold else "hebo")
        y += LINE_HEIGHT
    return y


def _heading(page: fitz.Page, text: str, y: float) -> float:
    y += 8
    page.insert_text((MARGIN, y), text, fontsize=HEADING_SIZE, fontname="hebo")
    y += 6
    page.draw_line((MARGIN, y), (PAGE_WIDTH - MARGIN, y), color=(0.7, 0.7, 0.7), width=0.5)
    return y + 14


def generate_ai_transparency_onepager(generated_at: datetime) -> bytes:
    doc = fitz.open()
    page = doc.new_page(width=PAGE_WIDTH, height=792)
    y: float = MARGIN

    page.insert_text((MARGIN, y), "REDACTPROOF - AI TRANSPARENCY STATEMENT", fontsize=15, fontname="hebo")
    y += 20
    page.insert_text((MARGIN, y), f"Generated (UTC): {generated_at.isoformat()}  ·  Platform-level document (applies to every organization)", fontsize=8)
    y += 22

    y = _heading(page, "Model inventory", y)
    y = _write_wrapped(
        page,
        "Detection runs two passes. The deterministic pass (Microsoft Presidio + org-configured regex/dictionary/entity "
        "rules) never calls a language model - it's pattern and NER matching, fully explainable per match. The contextual "
        "pass calls a large language model only on pages/chunks needing judgment (narrative text, ambiguous entities) and "
        "only proposes redactions with a citation and plain-language justification - a human decides on every one before "
        "it's ever applied.",
        y,
    )
    y = _write_wrapped(
        page,
        "Production configuration targets Amazon Bedrock (model id set per-deployment via BEDROCK_MODEL_ID, "
        "default region us-east-1), under Bedrock's zero-retention configuration - customer content is never used to "
        "train Bedrock's underlying models or ours. Every AI-proposed redaction records which model id and prompt "
        "version produced it, so any past decision is explainable after the fact, not just at review time.",
        y,
    )
    y += 4

    y = _heading(page, "Data flow", y)
    y = _draw_flow_diagram(page, y)
    y = _write_wrapped(
        page,
        "Original content is stored once (per-org encryption key) and never leaves this pipeline: extraction and "
        "detection read it, redaction candidates reference spans and boxes (not copies of the source file), export "
        "burns approved redactions into a new file and scrubs metadata, and every step writes an immutable, "
        "hash-chained audit record. Nothing downstream of the LLM call is allowed to auto-apply a redaction - the "
        "human-review step below is a hard gate, not a configurable one.",
        y,
    )
    y += 4

    y = _heading(page, "Human-in-the-loop statement", y)
    y = _write_wrapped(
        page,
        "No document can reach an exported state without at least one human review action. Every AI-proposed "
        "redaction is stored as a candidate in a 'suggested' state, never a final decision - a human must approve, "
        "reject, or modify each one, with a mandatory exemption code, before export is possible. This is enforced at "
        "the API layer (not just the review UI), and every decision is attributed to a specific user and timestamped "
        "in the audit trail.",
        y,
    )
    y += 4

    y = _heading(page, "Accuracy report", y)
    y = _write_wrapped(
        page,
        "NOT YET AVAILABLE. The golden-fixture measurement suite this report depends on "
        "(specs/05-redaction-pipeline.md: ~30 fixture documents, recall >= 95% / precision >= 80% targets) has not "
        "been built or run yet in this codebase as of this document's generation date. We are not publishing invented "
        "numbers here. This section will report actual measured precision/recall against that suite, updated per "
        "release, once it exists.",
        y,
    )
    y += 4

    y = _heading(page, "Bias testing summary", y)
    y = _write_wrapped(
        page,
        "NOT YET AVAILABLE, for the same reason as the accuracy report above - no name-ethnicity or demographic-"
        "representation testing on detection recall has been conducted yet. This section will report the actual "
        "methodology and results once that testing exists, not before.",
        y,
    )
    y += 10

    page.insert_text(
        (MARGIN, 760),
        "This document tracks what is actually true of the system as built, not the product roadmap. "
        "It is reviewed and regenerated at least once per release.",
        fontsize=7.5,
    )

    return doc.tobytes()


def main() -> int:
    generated_at = datetime.now(UTC)
    pdf_bytes = generate_ai_transparency_onepager(generated_at)

    repo_root = Path(__file__).resolve().parent.parent.parent
    ai_transparency_dir = repo_root / "docs" / "ai-transparency"
    ai_transparency_dir.mkdir(parents=True, exist_ok=True)
    out_path = ai_transparency_dir / "ai-transparency-one-pager.pdf"
    out_path.write_bytes(pdf_bytes)

    public_dir = repo_root / "web" / "public"
    if public_dir.is_dir():
        (public_dir / "ai-transparency-one-pager.pdf").write_bytes(pdf_bytes)

    print(f"Wrote {out_path} ({len(pdf_bytes)} bytes)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
