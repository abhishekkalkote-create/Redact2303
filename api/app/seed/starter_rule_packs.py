"""Canonical row data for the 5 global starter rule packs (specs/06-exemption-taxonomy.md
§ Starter packs). Single source of truth, imported by both the migration that creates
them (alembic/versions/0008_seed_starter_rule_packs.py) and the test fixture that has to
re-seed them after a TRUNCATE-based cleanup wipes the whole rule_packs table (Postgres's
`TRUNCATE ... CASCADE` sweeps any table with an FK to organizations, whole-table, even
rows whose FK value is NULL — see tests/conftest.py's docstring on why).

Design rationale (exemption codes, entity choices, context words) is documented in the
migration file, not duplicated here.
"""

from datetime import UTC, datetime


def _pack(id_: str, name: str, description: str, category: str) -> dict:
    return {"id": id_, "org_id": None, "name": name, "description": description, "category": category, "status": "active"}


def _version(id_: str, pack_id: str) -> dict:
    return {
        "id": id_, "rule_pack_id": pack_id, "org_id": None, "version": 1, "status": "published",
        "published_by": None, "published_at": datetime.now(UTC), "changelog": "Initial starter pack version.",
    }


def _rule(
    id_: str, version_id: str, rule_key: str, name: str, trigger_type: str, config: dict,
    library_code: str | None, priority: int = 100, confidence_policy: str = "suggest",
    exclusions: list | None = None, source_ref: str | None = None,
) -> dict:
    return {
        "id": id_, "rule_set_version_id": version_id, "org_id": None, "rule_key": rule_key, "name": name,
        "trigger_type": trigger_type, "config": config, "exemption_code_id": None,
        "exemption_library_code": library_code, "priority": priority, "confidence_policy": confidence_policy,
        "exclusions": exclusions or [], "scope": "org", "source_ref": source_ref, "status": "active",
    }


def get_packs() -> list[dict]:
    return [
        _pack("rpk_core_pii", "Core PII", "SSN, financial accounts, DL/passport, DOB, personal phones/emails/addresses.", "core_pii"),
        _pack("rpk_public_safety", "Public Safety", "Victim/witness identity, juveniles, informants, investigative techniques, open-case markers.", "public_safety"),
        _pack("rpk_hr", "HR / Personnel", "Employee medical, discipline, home contact, beneficiary data.", "hr"),
        _pack("rpk_legal", "Legal Privilege", "Attorney-client markers, work product, deliberative drafts.", "legal"),
        _pack("rpk_health", "Health", "PHI categories (HIPAA identifiers) for health-adjacent agencies.", "health"),
    ]


def get_versions() -> list[dict]:
    return [
        _version("rsv_core_pii_v1", "rpk_core_pii"),
        _version("rsv_public_safety_v1", "rpk_public_safety"),
        _version("rsv_hr_v1", "rpk_hr"),
        _version("rsv_legal_v1", "rpk_legal"),
        _version("rsv_health_v1", "rpk_health"),
    ]


def get_rules() -> list[dict]:
    core_pii = [
        _rule("rul_cpii_1", "rsv_core_pii_v1", "CPII-1", "Social Security Number", "entity", {"entity_type": "US_SSN"}, "b(6)"),
        _rule("rul_cpii_2", "rsv_core_pii_v1", "CPII-2", "Credit card number", "entity", {"entity_type": "CREDIT_CARD"}, "b(6)"),
        _rule("rul_cpii_3", "rsv_core_pii_v1", "CPII-3", "Bank account number", "entity", {"entity_type": "US_BANK_NUMBER"}, "b(6)"),
        _rule("rul_cpii_4", "rsv_core_pii_v1", "CPII-4", "Phone number", "entity", {"entity_type": "PHONE_NUMBER"}, "b(6)"),
        _rule("rul_cpii_5", "rsv_core_pii_v1", "CPII-5", "Email address", "entity", {"entity_type": "EMAIL_ADDRESS"}, "b(6)"),
        _rule("rul_cpii_6", "rsv_core_pii_v1", "CPII-6", "Driver's license number", "entity", {"entity_type": "US_DRIVER_LICENSE"}, "b(6)"),
        _rule("rul_cpii_7", "rsv_core_pii_v1", "CPII-7", "Passport number", "entity", {"entity_type": "US_PASSPORT"}, "b(6)"),
        _rule(
            "rul_cpii_8", "rsv_core_pii_v1", "CPII-8", "Date of birth", "entity",
            {"entity_type": "DATE_TIME", "context_words": ["DOB", "date of birth", "born on", "birth date"], "context_window": 25},
            "b(6)",
        ),
        _rule(
            "rul_cpii_9", "rsv_core_pii_v1", "CPII-9", "Home address", "entity",
            {"entity_type": "LOCATION", "context_words": ["home address", "resides at", "lives at", "home residence"], "context_window": 30},
            "b(6)",
        ),
    ]
    public_safety = [
        _rule(
            "rul_ps_1", "rsv_public_safety_v1", "PS-1", "Victim/witness identity", "entity",
            {"entity_type": "PERSON", "context_words": ["victim", "witness"], "context_window": 40}, "7(C)",
        ),
        _rule(
            "rul_ps_2", "rsv_public_safety_v1", "PS-2", "Confidential informant code", "regex",
            {"pattern": r"(?i)\b(?:CI|informant)[\s#-]*\d+\b"}, "7(D)",
        ),
        _rule(
            "rul_ps_3", "rsv_public_safety_v1", "PS-3", "Juvenile identity", "entity",
            {"entity_type": "PERSON", "context_words": ["juvenile", "minor", "J.D. (juvenile)"], "context_window": 40}, "7(C)",
        ),
        _rule(
            "rul_ps_4", "rsv_public_safety_v1", "PS-4", "Officer/unit roster (customize before enabling)", "dictionary",
            {"terms": []}, "7(D)",
        ),
        _rule(
            "rul_ps_5", "rsv_public_safety_v1", "PS-5", "Open case number", "regex",
            {"pattern": r"(?i)\bcase\s*#?\s*\d{4,}-?\d*\b", "context_words": ["open", "pending", "active investigation"], "context_window": 40},
            "7(A)",
        ),
        _rule(
            "rul_ps_6", "rsv_public_safety_v1", "PS-6", "Investigative techniques/procedures", "llm_context",
            {"instruction": "Redact descriptions of specific investigative techniques, surveillance methods, or undercover tactics that could compromise future law-enforcement operations if disclosed."},
            "7(E)",
        ),
    ]
    hr = [
        _rule(
            "rul_hr_1", "rsv_hr_v1", "HR-1", "Employee medical/leave information", "entity",
            {"entity_type": "PERSON", "context_words": ["medical leave", "FMLA", "diagnosis", "disability accommodation"], "context_window": 40},
            "b(6)",
        ),
        _rule(
            "rul_hr_2", "rsv_hr_v1", "HR-2", "Employee home/personal contact", "entity",
            {"entity_type": "PHONE_NUMBER", "context_words": ["home phone", "personal cell", "emergency contact"], "context_window": 40},
            "b(6)",
        ),
        _rule(
            "rul_hr_3", "rsv_hr_v1", "HR-3", "Employee disciplinary/termination details", "llm_context",
            {"instruction": "Redact details of employee disciplinary actions, performance issues, or termination reasons for a named employee. Do not redact when the document is a general disciplinary policy not tied to a specific employee."},
            "b(6)",
        ),
        _rule(
            "rul_hr_4", "rsv_hr_v1", "HR-4", "Beneficiary / next-of-kin identity", "entity",
            {"entity_type": "PERSON", "context_words": ["beneficiary", "next of kin"], "context_window": 40}, "b(6)",
        ),
    ]
    legal = [
        _rule(
            "rul_lp_1", "rsv_legal_v1", "LP-1", "Attorney-client privilege markers", "dictionary",
            {"terms": ["privileged and confidential", "attorney-client privilege", "attorney work product", "prepared in anticipation of litigation"]},
            "b(5)",
        ),
        _rule(
            "rul_lp_2", "rsv_legal_v1", "LP-2", "Deliberative process markers", "dictionary",
            {"terms": ["deliberative process", "internal deliberations", "predecisional draft"]}, "b(5)",
        ),
        _rule(
            "rul_lp_3", "rsv_legal_v1", "LP-3", "Legal analysis/strategy without explicit marker", "llm_context",
            {"instruction": "Redact legal analysis, recommendations, or strategy discussions that reflect attorney mental impressions or legal advice, even without an explicit privilege marker."},
            "b(5)",
        ),
    ]
    health = [
        _rule(
            "rul_hl_1", "rsv_health_v1", "HL-1", "Patient identity", "entity",
            {"entity_type": "PERSON", "context_words": ["diagnosis", "patient", "treated for", "medical record"], "context_window": 40},
            "b(6)",
        ),
        _rule("rul_hl_2", "rsv_health_v1", "HL-2", "Medical record number", "regex", {"pattern": r"(?i)\bMRN[\s:#-]*\d{5,}\b"}, "b(6)"),
        _rule(
            "rul_hl_3", "rsv_health_v1", "HL-3", "Sensitive health category markers", "dictionary",
            {"terms": ["HIV status", "substance abuse treatment", "mental health treatment", "reproductive health"]}, "b(6)",
        ),
        _rule(
            "rul_hl_4", "rsv_health_v1", "HL-4", "Treatment/admission dates", "entity",
            {"entity_type": "DATE_TIME", "context_words": ["admitted on", "discharged on", "date of treatment"], "context_window": 25},
            "b(6)",
        ),
    ]
    return core_pii + public_safety + hr + legal + health
