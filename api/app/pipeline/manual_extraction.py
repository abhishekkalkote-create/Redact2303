"""specs/06-exemption-taxonomy.md § Manual-to-rule extraction: "Upload manual ... LLM
proposes draft rules: trigger config, suggested exemption code (matched against org
taxonomy), exclusions, source_ref (section anchor + quoted text), ambiguity notes."

Section classification + rule proposal happen in ONE LLM call per page (not two passes)
— the prompt asks for both `section_type` and `draft_rules` together. `source_quote`
uses the exact same fuzzy-grounding hallucination guard as the contextual detection pass
(app/pipeline/contextual.py's best_fuzzy_span) — a proposed rule whose claimed quote
doesn't actually appear in the source page is dropped, not trusted.
"""

import json
import re
from dataclasses import dataclass
from pathlib import Path

from app.llm.provider import LLMProvider
from app.pipeline.contextual import GROUNDING_SIMILARITY_THRESHOLD, best_fuzzy_span
from app.pipeline.nl_rule_edit import VALID_TRIGGER_TYPES, validate_regex

PROMPT_VERSION = "1"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"manual_extraction_v{PROMPT_VERSION}.md"


@dataclass
class ExtractedDraftRule:
    name: str
    trigger_type: str
    config: dict
    exemption_code: str | None
    exclusions: list
    source_ref: str
    ambiguity_notes: str
    invalid_reason: str | None = None

    @property
    def is_valid(self) -> bool:
        return self.invalid_reason is None


def render_prompt(page_text: str, exemption_code_options: str) -> tuple[str, str]:
    template = _PROMPT_PATH.read_text()
    user = (
        template
        .replace("<<EXEMPTION_CODE_OPTIONS>>", exemption_code_options)
        .replace("<<PAGE_TEXT>>", page_text)
    )
    system = "You are a precise rules-engine assistant. Output strict JSON only."
    return system, user


def _validate_draft(raw: dict, allowed_codes: set[str]) -> str | None:
    trigger_type = raw.get("trigger_type")
    if trigger_type not in VALID_TRIGGER_TYPES:
        return f"invalid trigger_type {trigger_type!r} (must be one of {VALID_TRIGGER_TYPES})"
    if not raw.get("config"):
        return "missing config"

    exemption_code = raw.get("exemption_code")
    if exemption_code is not None and exemption_code not in allowed_codes:
        return f"exemption_code {exemption_code!r} is not in the org's taxonomy — the model invented a code"

    if trigger_type == "regex" and "pattern" in raw["config"]:
        error = validate_regex(raw["config"]["pattern"])
        if error:
            return error

    return None


def parse_and_ground_page(
    response_text: str, page_text: str, page_no: int, allowed_codes: set[str]
) -> tuple[str, list[ExtractedDraftRule]]:
    """Returns (section_type, drafts). Never raises — a malformed response yields
    ("other", []), matching app/pipeline/contextual.py's parse_findings() failure
    behavior."""
    try:
        match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if not match:
            return "other", []
        payload = json.loads(match.group(0))
        section_type = str(payload.get("section_type", "other"))
        raw_drafts = payload.get("draft_rules", [])
    except (json.JSONDecodeError, TypeError):
        return "other", []

    drafts = []
    for raw in raw_drafts:
        if not isinstance(raw, dict):
            continue
        quote = str(raw.get("source_quote", ""))
        _start, _end, ratio = best_fuzzy_span(page_text, quote) if quote else (0, 0, 0.0)

        invalid_reason: str | None
        if ratio < GROUNDING_SIMILARITY_THRESHOLD:
            invalid_reason = "source_quote does not match the page text closely enough (possible hallucination)"
        else:
            invalid_reason = _validate_draft(raw, allowed_codes)

        drafts.append(
            ExtractedDraftRule(
                name=str(raw.get("name", "")), trigger_type=str(raw.get("trigger_type", "")),
                config=raw.get("config") or {}, exemption_code=raw.get("exemption_code"),
                exclusions=raw.get("exclusions") or [], source_ref=f"page {page_no}: {quote!r}",
                ambiguity_notes=str(raw.get("ambiguity_notes", ""))[:500], invalid_reason=invalid_reason,
            )
        )
    return section_type, drafts


def run_extraction_for_page(
    provider: LLMProvider, page_text: str, page_no: int, allowed_codes: set[str]
) -> tuple[str, list[ExtractedDraftRule], int, int]:
    """Returns (section_type, drafts, input_tokens, output_tokens)."""
    if not page_text.strip():
        return "other", [], 0, 0
    system, user = render_prompt(page_text, ", ".join(sorted(allowed_codes)))
    response = provider.complete(system, user)
    section_type, drafts = parse_and_ground_page(response.text, page_text, page_no, allowed_codes)
    return section_type, drafts, response.input_tokens, response.output_tokens
