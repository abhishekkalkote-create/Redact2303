from datetime import datetime

from pydantic import BaseModel


class RulePackOut(BaseModel):
    id: str
    org_id: str | None = None
    name: str
    description: str | None = None
    category: str
    status: str
    cloned_from_pack_id: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RulePackCreate(BaseModel):
    name: str
    description: str | None = None
    category: str
    # specs/06-exemption-taxonomy.md: "org clones library codes ... and/or adds internal
    # reason codes" — set to clone an existing pack's latest version's rules into this new
    # org-owned pack; omit for an empty custom pack.
    clone_from_pack_id: str | None = None


class RuleSetVersionOut(BaseModel):
    id: str
    rule_pack_id: str
    org_id: str | None = None
    version: int
    status: str
    published_by: str | None = None
    published_at: datetime | None = None
    changelog: str | None = None
    created_at: datetime

    model_config = {"from_attributes": True}


class RuleOut(BaseModel):
    id: str
    rule_set_version_id: str
    rule_key: str
    name: str
    trigger_type: str
    config: dict
    exemption_code_id: str | None = None
    exemption_library_code: str | None = None
    priority: int
    confidence_policy: str
    exclusions: list
    scope: str
    source_ref: str | None = None
    status: str

    model_config = {"from_attributes": True}


class RuleCreate(BaseModel):
    rule_key: str
    name: str
    trigger_type: str
    config: dict
    exemption_code_id: str | None = None
    exemption_library_code: str | None = None
    priority: int = 100
    confidence_policy: str = "suggest"
    exclusions: list = []
    scope: str = "org"
    source_ref: str | None = None


class RulePatch(BaseModel):
    name: str | None = None
    trigger_type: str | None = None
    config: dict | None = None
    exemption_code_id: str | None = None
    exemption_library_code: str | None = None
    priority: int | None = None
    confidence_policy: str | None = None
    exclusions: list | None = None
    scope: str | None = None
    source_ref: str | None = None
    status: str | None = None


class PublishVersionRequest(BaseModel):
    changelog: str | None = None


class NlEditRequest(BaseModel):
    instruction: str


class ProposedRuleChangeOut(BaseModel):
    action: str
    rule_key: str
    name: str | None = None
    trigger_type: str | None = None
    config: dict | None = None
    exemption_code: str | None = None
    exclusions: list = []
    rationale: str
    is_valid: bool
    invalid_reason: str | None = None


class NlEditResponse(BaseModel):
    """specs/06-exemption-taxonomy.md: "shown as a reviewable draft change; nothing
    applies without human confirm + publish." `prompt_version`/`instruction` are echoed
    back so the client can pass them as `source_ref` when it confirms an accepted
    proposal via the existing POST rule-set-versions/{id}/rules or PATCH /rules/{id}
    endpoints — "NL input stored with the rule as provenance," without a separate
    apply/confirm endpoint."""

    prompt_version: str
    instruction: str
    proposals: list[ProposedRuleChangeOut]
