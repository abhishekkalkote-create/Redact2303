"""specs/06-exemption-taxonomy.md § Rule anatomy: executes `Rule` rows (regex/
dictionary/entity trigger types) against extracted page text, then evaluates exclusions
on the resulting matches ("Exclusions ... evaluated after match"). `metadata` rules run
against document-level fields, not page text (specs/06: "document properties (author,
custodian)... Intake stage") — a separate entry point, `run_metadata_rule`, below.
`llm_context` rules are NOT executed here — they're LLM-driven, handled by
app/pipeline/detect_llm.py, which folds org-authored instructions into the contextual
prompt rather than pattern-matching them deterministically.
"""

import re
from dataclasses import dataclass
from functools import lru_cache

from presidio_analyzer import AnalyzerEngine

from app.models.rule import Rule

DETERMINISTIC_TRIGGER_TYPES = ("regex", "dictionary", "entity")


@dataclass
class RuleMatch:
    rule_id: str
    rule_key: str
    start: int
    end: int
    text: str
    score: float
    excluded: bool = False
    excluded_reason: str | None = None


@lru_cache
def _analyzer() -> AnalyzerEngine:
    return AnalyzerEngine()


def _luhn_valid(digits: str) -> bool:
    if not digits.isdigit():
        return False
    total = 0
    for i, ch in enumerate(reversed(digits)):
        d = int(ch)
        if i % 2 == 1:
            d *= 2
            if d > 9:
                d -= 9
        total += d
    return total % 10 == 0


def _ssn_format_valid(digits: str) -> bool:
    """Rejects the well-known-invalid SSN ranges (never actually issued), not just any
    9-digit string: all-zero groups, 666 area, and 900-999 (ITIN range, not an SSN)."""
    if len(digits) != 9 or not digits.isdigit():
        return False
    area, group, serial = digits[:3], digits[3:5], digits[5:]
    if area in ("000", "666") or area.startswith("9"):
        return False
    return group != "00" and serial != "0000"


_VALIDATORS = {"luhn": _luhn_valid, "ssn_format": _ssn_format_valid}


def _run_regex_rule(text: str, config: dict) -> list[tuple[int, int, str, float]]:
    pattern = config["pattern"]
    validators = config.get("validators", [])
    context_words = config.get("context_words", [])
    context_window = config.get("context_window", 40)

    matches: list[tuple[int, int, str, float]] = []
    for m in re.finditer(pattern, text):
        matched_text = m.group(0)
        digits = re.sub(r"\D", "", matched_text)
        if any(name in validators and not _VALIDATORS[name](digits) for name in validators if name in _VALIDATORS):
            continue
        if context_words:
            window = text[max(0, m.start() - context_window) : m.end() + context_window].lower()
            if not any(word.lower() in window for word in context_words):
                continue
        matches.append((m.start(), m.end(), matched_text, 0.9))
    return matches


def _run_dictionary_rule(text: str, config: dict) -> list[tuple[int, int, str, float]]:
    terms = config.get("terms", [])
    case_sensitive = config.get("case_sensitive", False)
    flags = 0 if case_sensitive else re.IGNORECASE

    matches: list[tuple[int, int, str, float]] = []
    for term in terms:
        pattern = r"\b" + re.escape(term) + r"\b"
        for m in re.finditer(pattern, text, flags):
            matches.append((m.start(), m.end(), m.group(0), 0.95))
    return matches


def _run_entity_rule(text: str, config: dict) -> list[tuple[int, int, str, float]]:
    entity_type = config["entity_type"]
    results = _analyzer().analyze(text=text, language="en", entities=[entity_type])
    return [(r.start, r.end, text[r.start : r.end], r.score) for r in results]


def _evaluate_exclusions(text: str, start: int, end: int, exclusions: list[dict]) -> tuple[bool, str | None]:
    """specs/06: allowlists, context conditions, pattern carve-outs — evaluated after
    the trigger matched, in the order given; the first hit wins."""
    matched_text = text[start:end]
    for excl in exclusions:
        kind = excl.get("type")
        if kind == "allowlist":
            values = {v.lower() for v in excl.get("values", [])}
            if matched_text.strip().lower() in values:
                return True, f"allowlist: {matched_text}"
        elif kind == "context_not":
            phrase = excl.get("phrase", "")
            window_size = excl.get("window", 60)
            window = text[max(0, start - window_size) : end + window_size].lower()
            if phrase and phrase.lower() in window:
                return True, f"context_not: {phrase}"
        elif kind == "pattern_carveout":
            carve_pattern = excl.get("pattern")
            if carve_pattern and re.fullmatch(carve_pattern, matched_text):
                return True, f"pattern_carveout: {carve_pattern}"
    return False, None


def run_rule(text: str, rule: Rule) -> list[RuleMatch]:
    """Runs one deterministic rule against page text. Returns every match, including
    excluded ones (marked, not dropped) — specs/06: "Exclusion hits are logged and
    visible in the test bench," so the caller decides whether to keep or discard them."""
    if rule.trigger_type == "regex":
        raw = _run_regex_rule(text, rule.config)
    elif rule.trigger_type == "dictionary":
        raw = _run_dictionary_rule(text, rule.config)
    elif rule.trigger_type == "entity":
        raw = _run_entity_rule(text, rule.config)
    else:
        return []

    matches = []
    for start, end, matched_text, score in raw:
        excluded, reason = _evaluate_exclusions(text, start, end, rule.exclusions)
        matches.append(
            RuleMatch(
                rule_id=rule.id, rule_key=rule.rule_key, start=start, end=end,
                text=matched_text, score=score, excluded=excluded, excluded_reason=reason,
            )
        )
    return matches


def run_metadata_rule(document_metadata: dict[str, str], rule: Rule) -> bool:
    """specs/06: metadata rules check document properties (author, custodian, ...), not
    page text — no spans, so no bbox and no exclusions; this only says "did this
    document's metadata match," for the intake-stage caller to act on."""
    field = rule.config.get("field")
    pattern = rule.config.get("pattern")
    value = document_metadata.get(field, "") if field else ""
    if not value:
        return False
    return bool(re.search(pattern, value, re.IGNORECASE)) if pattern else bool(value)
