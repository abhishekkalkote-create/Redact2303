"""Core PII starter pack (specs/06-exemption-taxonomy.md: "SSN, financial accounts,
DL/passport, DOB, personal phones/emails/addresses"). Phase 1 deliberately narrows this to
the entity types Presidio detects reliably out of the box — DOB and street addresses are
intentionally NOT included yet (DATE_TIME/LOCATION are too broad/noisy without additional
context rules to be a responsible default-on detector; adding them is a rules-engine change
in Phase 4, not a code change, so this narrowing doesn't block anything).

Confidence mapping is a fixed, simple threshold here — the graduated confidence policy
per rule (`confidence_policy`: auto_high/suggest/flag_low) is part of the Phase 4 rules
engine; Phase 1's deterministic pass always produces `suggested` candidates regardless of
confidence (specs/05-redaction-pipeline.md: "Deterministic-only findings are never
auto-approved").
"""

from dataclasses import dataclass

RULE_KEY = "CORE-PII-P1"
RULE_VERSION = "1"

# Presidio entity_type -> (rule_key suffix, library exemption code to attach)
ENTITY_TO_LIBRARY_CODE: dict[str, str] = {
    "US_SSN": "b(6)",
    "CREDIT_CARD": "b(6)",
    "US_BANK_NUMBER": "b(6)",
    "PHONE_NUMBER": "b(6)",
    "EMAIL_ADDRESS": "b(6)",
    "US_DRIVER_LICENSE": "b(6)",
    "US_PASSPORT": "b(6)",
}
# federal b(6) ("personal privacy") is the correct default per specs/06-exemption-taxonomy.md's
# category list ("PII ... where exempt") — every org has it cloned regardless of state
# (specs/06-exemption-taxonomy.md: "get federal + their state library pre-cloned"). If the
# org's own jurisdiction has a more specific "<STATE>-PII" library entry, prefer that
# instead — see app/pipeline/detect.py's `_pick_exemption_code`.
STATE_PII_LIBRARY_CODE_SUFFIX = "-PII"

SUPPORTED_ENTITIES = list(ENTITY_TO_LIBRARY_CODE.keys())


@dataclass
class Finding:
    entity_type: str
    start: int
    end: int
    text: str
    score: float


def confidence_band(score: float) -> str:
    # specs/05-redaction-pipeline.md's LLM confidence bands, reused here for consistency —
    # the deterministic pass has no separate published thresholds of its own.
    if score >= 0.85:
        return "high"
    if score >= 0.6:
        return "medium"
    return "low"
