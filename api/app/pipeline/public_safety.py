"""Public Safety starter pack (specs/06-exemption-taxonomy.md starter packs;
specs/10-build-plan.md Phase 2: "Public Safety + HR + Legal starter packs with
llm_context rules"). Phase 4 (rules engine self-service) turns these into DB-editable
rule_packs/rules; for Phase 2 they're a fixed Python config, same pattern as
app/pipeline/core_pii.py's Core PII pack — a code change to edit, not a UI change, until
Phase 4 lands.

HR and Legal starter packs are NOT included yet — Public Safety is the one specs/10's
Phase 2 AC actually exercises ("narrative police report where victim/witness names are
caught by context ... with 7(C) citations"); adding the other two is data-only once this
shape exists, not attempted here to avoid guessing at content nobody has asked to verify.
"""

RULE_KEY = "PUBLIC-SAFETY-LLM-P2"
RULE_VERSION = "1"

DOCUMENT_TYPE = "police_report"

LLM_CONTEXT_RULES = """\
- Redact the name of any victim of a crime, especially sexual assault, domestic violence, \
or crimes against a minor — even if only referred to by role (e.g. "the victim") elsewhere \
in the same document, if a name is given anywhere. Map to exemption code 7(C).
- Redact the identity (name, address, or other identifying detail) of anyone described as a \
confidential informant, confidential source, or someone providing information under a grant \
of confidentiality. Map to exemption code 7(D).
- Redact specific investigative techniques or procedures described in detail (e.g. \
surveillance methods, undercover operation details) if disclosure could let someone \
circumvent the law. Map to exemption code 7(E).
- Redact any information that, if disclosed, could reasonably endanger a specific named \
individual's life or physical safety (e.g. an address of someone under active threat). \
Map to exemption code 7(F).
- Do NOT redact the names or badge numbers of on-duty officers acting in their official \
capacity, unless a specific undercover/confidential-source rule above applies to them.
- Do NOT redact generic references to "the victim" or "a witness" with no name attached — \
only redact when an actual identifying name or detail is present.
"""

# federal library codes these rules are allowed to cite — used to build the exemption
# taxonomy summary passed to the prompt, and to validate the LLM didn't invent a code.
ALLOWED_LIBRARY_CODES = ("7(C)", "7(D)", "7(E)", "7(F)")
