"""specs/05-redaction-pipeline.md Stage 4: Contextual LLM detection.

Fully unit-testable without a live model via app/llm/provider.py's FakeLLMProvider — the
chunking, prompt rendering, JSON parsing, and grounding/hallucination-guard logic here are
real, exercised logic, not stubs waiting on Bedrock access. Only BedrockProvider itself
needs a real AWS account.
"""

import difflib
import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.llm.provider import LLMProvider

PROMPT_VERSION = "1"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"contextual_v{PROMPT_VERSION}.md"
MAX_CHUNK_CHARS = 16_000  # ~4K tokens at ~4 chars/token (specs/05-redaction-pipeline.md)
GROUNDING_SIMILARITY_THRESHOLD = 0.95


@dataclass
class Chunk:
    text: str
    start_offset: int  # offset into the page's full_text where this chunk begins


@dataclass
class RawFinding:
    quote: str
    entity_kind: str
    exemption_code: str
    confidence: float
    justification: str


@dataclass
class GroundedFinding(RawFinding):
    start: int  # offset into the page's full_text (not the chunk)
    end: int


def chunk_text(full_text: str, max_chars: int = MAX_CHUNK_CHARS) -> list[Chunk]:
    """Paragraph-level chunking (specs/05-redaction-pipeline.md: "semantic blocks
    (paragraph-level..."). Splits on blank-line paragraph breaks, then packs consecutive
    paragraphs into chunks up to max_chars."""
    if not full_text.strip():
        return []

    paragraphs = re.split(r"\n\s*\n", full_text)
    chunks: list[Chunk] = []
    cursor = 0
    current_parts: list[str] = []
    current_start = 0
    current_len = 0

    for para in paragraphs:
        para_start = full_text.index(para, cursor)
        cursor = para_start + len(para)
        if current_len + len(para) > max_chars and current_parts:
            chunks.append(Chunk(text="\n\n".join(current_parts), start_offset=current_start))
            current_parts, current_len, current_start = [], 0, para_start
        if not current_parts:
            current_start = para_start
        current_parts.append(para)
        current_len += len(para)

    if current_parts:
        chunks.append(Chunk(text="\n\n".join(current_parts), start_offset=current_start))
    return chunks


def render_prompt(
    document_type: str, llm_context_rules: str, exemption_taxonomy_summary: str, chunk: str
) -> tuple[str, str]:
    # Plain .replace() on distinctive <<MARKER>> tokens, not str.format() — the template's
    # JSON output example legitimately contains braces, which .format() would try (and
    # fail) to parse as placeholders. See git history for the KeyError this caused once.
    template = _PROMPT_PATH.read_text()
    user = (
        template
        .replace("<<DOCUMENT_TYPE>>", document_type)
        .replace("<<LLM_CONTEXT_RULES>>", llm_context_rules or "(none configured)")
        .replace("<<EXEMPTION_TAXONOMY_SUMMARY>>", exemption_taxonomy_summary)
        .replace("<<CHUNK_TEXT>>", chunk)
    )
    system = "You are a precise, conservative redaction-proposal assistant. Output strict JSON only."
    return system, user


def parse_findings(response_text: str) -> list[RawFinding]:
    """Never raises — a malformed response yields zero findings (logged by the caller via
    the hallucination/parse-failure counter), not a pipeline crash."""
    try:
        match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if not match:
            return []
        payload = json.loads(match.group(0))
        raw_findings = payload.get("findings", [])
        results = []
        for f in raw_findings:
            results.append(
                RawFinding(
                    quote=str(f["quote"]),
                    entity_kind=str(f.get("entity_kind", "")),
                    exemption_code=str(f["exemption_code"]),
                    confidence=float(f.get("confidence", 0.5)),
                    justification=str(f.get("justification", ""))[:240],
                )
            )
        return results
    except (json.JSONDecodeError, KeyError, TypeError, ValueError):
        return []


def best_fuzzy_span(haystack: str, needle: str) -> tuple[int, int, float]:
    """Slides a needle-length window across haystack and returns the best-matching span's
    (start, end, similarity_ratio). Exact substring match short-circuits to ratio=1.0."""
    exact = haystack.find(needle)
    if exact != -1:
        return exact, exact + len(needle), 1.0

    best_ratio, best_start = 0.0, 0
    step = max(1, len(needle) // 4)
    for start in range(0, max(1, len(haystack) - len(needle) + 1), step):
        window = haystack[start : start + len(needle)]
        ratio = difflib.SequenceMatcher(None, window, needle).ratio()
        if ratio > best_ratio:
            best_ratio, best_start = ratio, start
    return best_start, best_start + len(needle), best_ratio


def ground_findings(
    findings: list[RawFinding], chunk: Chunk
) -> tuple[list[GroundedFinding], int]:
    """specs/05-redaction-pipeline.md: "model quote must string-match extracted text
    (fuzzy >= 0.95) or the finding is dropped and logged (hallucination counter metric)."
    Returns (grounded_findings, hallucination_count)."""
    grounded = []
    hallucinated = 0
    for finding in findings:
        start, end, ratio = best_fuzzy_span(chunk.text, finding.quote)
        if ratio < GROUNDING_SIMILARITY_THRESHOLD:
            hallucinated += 1
            continue
        grounded.append(
            GroundedFinding(
                quote=finding.quote, entity_kind=finding.entity_kind,
                exemption_code=finding.exemption_code, confidence=finding.confidence,
                justification=finding.justification,
                start=chunk.start_offset + start, end=chunk.start_offset + end,
            )
        )
    return grounded, hallucinated


def confidence_band(score: float) -> str:
    if score >= 0.85:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"


def run_contextual_pass(
    provider: LLMProvider,
    full_text: str,
    *,
    document_type: str,
    llm_context_rules: str,
    exemption_taxonomy_summary: str,
) -> tuple[list[GroundedFinding], int, int, int]:
    """Returns (grounded_findings, hallucination_count, input_tokens, output_tokens)."""
    all_findings: list[GroundedFinding] = []
    total_hallucinated = 0
    total_input_tokens = 0
    total_output_tokens = 0

    for chunk in chunk_text(full_text):
        system, user = render_prompt(document_type, llm_context_rules, exemption_taxonomy_summary, chunk.text)
        response = provider.complete(system, user)
        total_input_tokens += response.input_tokens
        total_output_tokens += response.output_tokens

        raw_findings = parse_findings(response.text)
        grounded, hallucinated = ground_findings(raw_findings, chunk)
        all_findings.extend(grounded)
        total_hallucinated += hallucinated

    return all_findings, total_hallucinated, total_input_tokens, total_output_tokens
