"""specs/07-ui-spec.md § 1 Auth & onboarding: "optional sample document to try
instantly (demo doc processes free, exemplifies exemption citations)."

Generated at request time rather than committed as a static binary asset — same
fitz-primitives approach as every other generated PDF in this codebase (export
certificate, deletion certificate, destruction attestation, ROI summary), and it avoids
a binary file to maintain.

Content is entirely fictional, deliberately shaped to trigger several different
exemption codes out of the box: an org with no configured default_rule_pack_ids falls
back to all 5 global starter packs (app/pipeline/detect.py's _default_rule_pack_ids), so
a brand-new org's Core PII and Public Safety rules are already active. This includes an
SSN/phone/email (Core PII -> b(6)), a witness mention, a confidential-informant code,
and an open case number (Public Safety -> 7(C)/7(D)/7(A)).
"""

import fitz

SAMPLE_DOCUMENT_FILENAME = "sample-incident-report.pdf"

_LINES = [
    "INCIDENT REPORT - SAMPLE DOCUMENT",
    "(This is a fictional demonstration document, not a real record.)",
    "",
    "Case #2024-00987 remains an open, active investigation.",
    "",
    "Reporting officer contacted the complainant, Jane Doe, at (555) 867-5309 or",
    "jane.doe@example.com. Ms. Doe's Social Security Number on file is 123-45-6789.",
    "",
    "Witness Jane Doe stated that she observed the incident from her front porch.",
    "",
    "Confidential Informant CI-4471 separately reported similar activity in the area",
    "over the preceding two weeks.",
    "",
    "This document is provided so you can see how RedactProof proposes redactions with",
    "a statutory exemption code and draft justification for each. Processing it never",
    "counts against your plan's page allowance.",
]


def generate_sample_document_pdf() -> bytes:
    doc = fitz.open()
    page = doc.new_page()
    y = 72
    for line in _LINES:
        page.insert_text((72, y), line, fontsize=11)
        y += 18
    return doc.tobytes()
