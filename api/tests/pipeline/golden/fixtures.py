"""specs/05-redaction-pipeline.md § Golden-file test suite. The spec's own list of
fixture categories ("police report, HR file, email chain, poor scan, rotated pages,
forms") includes two ("poor scan", "rotated pages") that require the OCR path
(app/pipeline/extract.py's Textract/Tesseract branch), which does not exist yet - see
the GA-readiness punch list. Every fixture here is therefore a born-digital synthetic
PDF (same fitz-generation technique as app/pipeline/sample_document.py), covering the
other four categories plus legal memos and health records.

Scope deliberately restricted to entity types with regex/checksum-based Presidio
recognizers (US_SSN, CREDIT_CARD, US_BANK_NUMBER, PHONE_NUMBER, EMAIL_ADDRESS,
US_DRIVER_LICENSE, US_PASSPORT) plus this app's own regex/dictionary rules (PS-2, PS-5,
LP-1, LP-2, HL-2, HL-3) - all deterministic and independently verified against the real
Presidio engine before being encoded here as ground truth. Rules keyed on PERSON/LOCATION
(PS-1, PS-3, HR-1, HR-4, HL-1, CPII-9) depend on spacy's NER, which has real,
input-dependent variance on short synthetic names/addresses; deliberately not exercised
here so this suite's expected set stays exact rather than a guess. See
GoldenFixture.expected's docstring for the exact-text-match contract this implies.

Every `expected` entry's `text` is the FULL matched span (e.g. "MRN: 5528491", not just
the digits) - regex rules capture their whole match, not a sub-group.
"""

from dataclasses import dataclass


@dataclass(frozen=True)
class ExpectedFinding:
    text: str
    exemption_code: str


@dataclass(frozen=True)
class GoldenFixture:
    id: str
    category: str
    lines: list[str]
    expected: list[ExpectedFinding]


FIXTURES: list[GoldenFixture] = [
    GoldenFixture(
        id="police_report_ci_case_ssn_phone",
        category="police_report",
        lines=[
            "INCIDENT REPORT",
            "Case #2025-88213 remains an open, active investigation.",
            "",
            "Confidential Informant CI-7734 reported activity near the location on file.",
            "The complainant's Social Security Number on record is 452-88-3017.",
            "Reachable for follow-up at (206) 555-0142 during business hours.",
        ],
        expected=[
            ExpectedFinding("Case #2025-88213", "7(A)"),
            ExpectedFinding("CI-7734", "7(D)"),
            ExpectedFinding("452-88-3017", "b(6)"),
            ExpectedFinding("(206) 555-0142", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="police_report_fraud_case_card_email",
        category="police_report",
        lines=[
            "FRAUD INVESTIGATION SUPPLEMENT",
            "Case #2025-90441 is an open, pending fraud investigation.",
            "",
            "The victim's card ending 4539 1488 0343 6467 was used without authorization.",
            "The victim can be reached at pat.morgan@example.com for a follow-up interview.",
        ],
        expected=[
            ExpectedFinding("Case #2025-90441", "7(A)"),
            ExpectedFinding("4539 1488 0343 6467", "b(6)"),
            ExpectedFinding("pat.morgan@example.com", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="police_report_ci_license_phone",
        category="police_report",
        lines=[
            "FIELD INTERVIEW REPORT",
            "Confidential Informant CI-2201 provided the following account.",
            "",
            "Subject presented driver's license number W9284471 at the scene.",
            "A callback number of (415) 555-0198 was provided for further contact.",
        ],
        expected=[
            ExpectedFinding("CI-2201", "7(D)"),
            ExpectedFinding("W9284471", "b(6)"),
            ExpectedFinding("(415) 555-0198", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="police_report_ci_case_bank",
        category="police_report",
        lines=[
            "EMBEZZLEMENT INVESTIGATION - SUPPLEMENTAL REPORT",
            "Case #2025-77102 remains an open, active investigation into missing funds.",
            "",
            "Confidential Informant CI-5560 identified the account used to move funds.",
            "Bank account number 8827345190 received the transfers in question.",
        ],
        expected=[
            ExpectedFinding("Case #2025-77102", "7(A)"),
            ExpectedFinding("CI-5560", "7(D)"),
            ExpectedFinding("8827345190", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="hr_file_new_hire_ssn_bank_license",
        category="hr_file",
        lines=[
            "NEW EMPLOYEE PAYROLL SETUP FORM",
            "Employee Social Security Number: 918-27-4453.",
            "",
            "Direct deposit bank account number 4471902358 on file.",
            "Identification presented: driver's license number T5827104.",
        ],
        expected=[
            ExpectedFinding("918-27-4453", "b(6)"),
            ExpectedFinding("4471902358", "b(6)"),
            ExpectedFinding("T5827104", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="hr_file_contact_update_phone_email",
        category="hr_file",
        lines=[
            "EMPLOYEE CONTACT INFORMATION UPDATE",
            "Updated phone number on file: (312) 555-0177.",
            "",
            "Updated email address on file: j.rivera@example.com.",
            "Passport number 552810394 provided for the international assignment.",
        ],
        expected=[
            ExpectedFinding("(312) 555-0177", "b(6)"),
            ExpectedFinding("j.rivera@example.com", "b(6)"),
            ExpectedFinding("552810394", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="legal_memo_privilege_deliberative_ssn",
        category="legal_memo",
        lines=[
            "MEMORANDUM",
            "Privileged and confidential. Attorney work product.",
            "",
            "This memo reflects internal deliberations regarding the pending matter.",
            "Client Social Security Number referenced in the underlying claim: 267-90-1145.",
        ],
        expected=[
            ExpectedFinding("Privileged and confidential", "b(5)"),
            ExpectedFinding("Attorney work product", "b(5)"),
            ExpectedFinding("internal deliberations", "b(5)"),
            ExpectedFinding("267-90-1145", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="legal_memo_predecisional_case_email",
        category="legal_memo",
        lines=[
            "DRAFT LEGAL ANALYSIS - INTERNAL REVIEW",
            "This predecisional draft relates to Case #2025-66310, an open matter.",
            "",
            "Attorney-client privilege applies to the analysis below.",
            "Send questions to counsel at r.chen@example.com.",
        ],
        expected=[
            ExpectedFinding("predecisional draft", "b(5)"),
            ExpectedFinding("Case #2025-66310", "7(A)"),
            ExpectedFinding("Attorney-client privilege", "b(5)"),
            ExpectedFinding("r.chen@example.com", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="health_record_mrn_category_ssn",
        category="health_record",
        lines=[
            "PATIENT ENCOUNTER SUMMARY",
            "Patient MRN: 5528491 was seen for a scheduled visit.",
            "",
            "Record includes a history of substance abuse treatment.",
            "Patient's Social Security Number on file: 341-56-7890.",
        ],
        expected=[
            ExpectedFinding("MRN: 5528491", "b(6)"),
            ExpectedFinding("substance abuse treatment", "b(6)"),
            ExpectedFinding("341-56-7890", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="health_record_mrn_phone_email",
        category="health_record",
        lines=[
            "REFERRAL COORDINATION NOTE",
            "Referring record MRN #7734021 for continuity of care.",
            "",
            "Follow-up contact: (503) 555-0163.",
            "Records may also be requested via records@example.com.",
        ],
        expected=[
            ExpectedFinding("MRN #7734021", "b(6)"),
            ExpectedFinding("(503) 555-0163", "b(6)"),
            ExpectedFinding("records@example.com", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="health_record_mental_health_mrn",
        category="health_record",
        lines=[
            "CARE COORDINATION SUMMARY",
            "Patient MRN-4419087 is receiving mental health treatment services.",
            "",
            "Reproductive health services were also discussed during the visit.",
            "Contact for records request: (720) 555-0129.",
        ],
        expected=[
            ExpectedFinding("MRN-4419087", "b(6)"),
            ExpectedFinding("mental health treatment", "b(6)"),
            ExpectedFinding("Reproductive health", "b(6)"),
            ExpectedFinding("(720) 555-0129", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="email_chain_billing_dispute",
        category="email_chain",
        lines=[
            "From: billing@example.com",
            "To: customer.rep@example.com",
            "Subject: Disputed charge follow-up",
            "",
            "The customer's card ending 4716 2909 1234 5562 was charged in error.",
            "Please reach the customer directly at d.nguyen@example.com to confirm the refund.",
        ],
        expected=[
            ExpectedFinding("billing@example.com", "b(6)"),
            ExpectedFinding("customer.rep@example.com", "b(6)"),
            ExpectedFinding("4716 2909 1234 5562", "b(6)"),
            ExpectedFinding("d.nguyen@example.com", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="email_chain_hr_onboarding",
        category="email_chain",
        lines=[
            "From: hr@example.com",
            "To: payroll@example.com",
            "Subject: New hire payroll setup",
            "",
            "New hire Social Security Number for payroll setup: 108-42-9963.",
            "Direct deposit bank account number 3390218475 has been confirmed.",
        ],
        expected=[
            ExpectedFinding("hr@example.com", "b(6)"),
            ExpectedFinding("payroll@example.com", "b(6)"),
            ExpectedFinding("108-42-9963", "b(6)"),
            ExpectedFinding("3390218475", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="form_identity_verification",
        category="form",
        lines=[
            "IDENTITY VERIFICATION FORM",
            "Social Security Number: 590-14-2287",
            "Driver's license number: R7391642",
            "Passport number: 738201456",
        ],
        expected=[
            ExpectedFinding("590-14-2287", "b(6)"),
            ExpectedFinding("R7391642", "b(6)"),
            ExpectedFinding("738201456", "b(6)"),
        ],
    ),
    GoldenFixture(
        id="form_financial_disclosure",
        category="form",
        lines=[
            "FINANCIAL DISCLOSURE FORM",
            "Card number on file: 5241 8890 3312 7741",
            "Bank account number: 6603581294",
            "Contact phone: (629) 555-0184",
        ],
        expected=[
            ExpectedFinding("5241 8890 3312 7741", "b(6)"),
            ExpectedFinding("6603581294", "b(6)"),
            ExpectedFinding("(629) 555-0184", "b(6)"),
        ],
    ),
]
