# 06 — Exemption Taxonomy & Rules Engine

The exemption citation engine is the #1 differentiator. Every redaction carries a code from a structured taxonomy; codes carry statute citations; the AI proposes them; humans confirm.

## Taxonomy structure (three levels)

1. **Global federal library** (seeded, maintained by us): FOIA 5 U.S.C. § 552(b) exemptions:
   - b(1) national security/classified; b(2) internal personnel rules; b(3) exempt by other statute (requires statute sub-citation field); b(4) trade secrets/confidential commercial; b(5) deliberative process / attorney-client / work product; b(6) personal privacy (personnel/medical/similar files); b(7) law-enforcement records with subparts **7(A)** pending proceedings, **7(B)** fair trial, **7(C)** law-enforcement personal privacy, **7(D)** confidential source, **7(E)** techniques/procedures, **7(F)** life/safety endangerment; b(8) financial institution exams; b(9) wells data.
2. **Global state libraries** (seeded per state, expandable): recurring categories keyed to actual statute citations, e.g. WA "RCW 42.56.240(1) — investigative records", CA "Gov. Code § 7923.600", FL Sunshine Law exemptions. Seed content categories (each state maps its statutes onto these):
   - PII (SSN, DL#, financial accounts, DOB where exempt) · law-enforcement investigative (open cases) · victim/witness identity (sexual assault, DV, minors) · confidential informants/intelligence · juvenile records · medical/health (state + HIPAA overlay) · public-employee personnel records (incl. peace-officer special statutes) · deliberative/privileged · security plans/IT vulnerabilities · trade secrets/bids · other-statute catch-all (citation required) · specific items (booking photos, CCW holders, autopsy images, 911 audio, bodycam-specific statutes).
   - v1 seeding: full libraries for 5 launch states (choose by pilot pipeline; default CA, TX, FL, WA, NY) + federal; library format makes adding states data-only. Source for expansion: RCFP Open Government Guide.
3. **Org taxonomy**: org clones library codes (customizing label/guidance) and/or adds internal reason codes (e.g., "HR-1 employee home address"). Rules reference org taxonomy entries; org codes can map to a library citation.

Each code: `code`, `label`, `statute_citation`, `description`, `when_to_use guidance`, `level`, `status`. Orgs choosing jurisdiction at onboarding get federal + their state library pre-cloned.

## Rule engine

### Rule anatomy (see 03 for schema)
`rule_key` (stable), name, `trigger_type`, config, `exemption_code_id`, priority, `confidence_policy`, exclusions, scope, source_ref, versioned within rule sets.

### Trigger types
| Type | Config | Engine |
|---|---|---|
| `regex` | pattern, validators (luhn, ssn-format), context words | Deterministic pass |
| `dictionary` | term list / uploaded CSV (e.g., officer roster, undercover unit names) | Deterministic |
| `entity` | Presidio entity (PERSON, PHONE, EMAIL, US_SSN, LOCATION, ...) + context filters | Deterministic |
| `metadata` | document properties (author, custodian) | Intake stage |
| `llm_context` | natural-language instruction, entity kinds, examples/counter-examples | LLM pass |

### Exclusions (over-redaction prevention — competitors fail here)
Every rule supports exclusion clauses evaluated after match: allowlists (public officials acting officially, agency switchboard numbers, addresses of public buildings), context conditions ("not when the person is the responding officer"), pattern carve-outs. Exclusion hits are logged and visible in the test bench.

### Starter packs (shipped, global, cloneable)
1. **Core PII** — SSN, financial accounts, DL/passport, DOB, personal phones/emails/addresses → b(6)/state PII codes.
2. **Public Safety** — victim/witness identity, juveniles, informants (7(C)/(D)/(F) mappings), techniques (7(E)), open-case markers (7(A)); dictionary hooks for officer rosters.
3. **HR / Personnel** — employee medical, discipline (jurisdiction-dependent), home contact, beneficiary data.
4. **Legal Privilege** — attorney-client markers, work product, deliberative drafts → b(5).
5. **Health** — PHI categories (HIPAA identifiers) for health-adjacent agencies.

### Natural-language rule editing
Admin writes an instruction ("Redact witness cell phone numbers but not office switchboard numbers"). LLM returns a structured rule diff (new/edited rules with trigger configs and exclusions) shown as a reviewable draft change; nothing applies without human confirm + publish. Prompt versioned; NL input stored with the rule as provenance.

### Manual-to-rule extraction
1. Upload manual/exemption guide/SOP (PDF/DOCX) → extraction job.
2. Classify sections (definitions / exemptions / examples / exclusions / procedures); semantic chunking preserving section anchors.
3. LLM proposes draft rules: trigger config, suggested exemption code (matched against org taxonomy), exclusions, `source_ref` (section anchor + quoted text), ambiguity notes.
4. Draft workspace: admin accepts/edits/merges/rejects each; accepted drafts land in a new draft rule set version.
5. Test bench (mandatory before publish): run draft version against selected sample documents; show would-be candidates + diff vs current published version; publish requires explicit action; versions immutable after publish.

## Versioning & defensibility
- Rule sets: draft → published (immutable) → archived. Documents record exact versions used; exemption logs cite rule + version per redaction.
- Taxonomy changes never rewrite history: archived codes remain resolvable on old manifests/logs.
- Everything (rule publish, NL edit, extraction accept) is audited with actor and diff.
