"""specs/06-exemption-taxonomy.md § Natural-language rule editing: "Admin writes an
instruction ... LLM returns a structured rule diff ... shown as a reviewable draft
change; nothing applies without human confirm + publish." This module renders the
prompt, parses the response, and validates it (rejecting anything that invents a trigger
type, an exemption code, or an unparseable regex) — it does NOT persist anything; that
happens only when a human confirms a proposed change via the existing rule CRUD
endpoints (app/routers/rules.py), same as any other rule edit.
"""

import json
import re
from dataclasses import dataclass, field
from pathlib import Path

from app.llm.provider import LLMProvider
from app.pipeline.rule_engine import DETERMINISTIC_TRIGGER_TYPES

PROMPT_VERSION = "1"
_PROMPT_PATH = Path(__file__).parent / "prompts" / f"nl_rule_edit_v{PROMPT_VERSION}.md"

VALID_TRIGGER_TYPES = (*DETERMINISTIC_TRIGGER_TYPES, "llm_context")
VALID_ACTIONS = ("new", "edit")


@dataclass
class ProposedRuleChange:
    action: str
    rule_key: str
    name: str | None
    trigger_type: str | None
    config: dict | None
    exemption_code: str | None
    exclusions: list
    rationale: str
    invalid_reason: str | None = field(default=None)

    @property
    def is_valid(self) -> bool:
        return self.invalid_reason is None


def render_prompt(instruction: str, existing_rules_summary: str, exemption_code_options: str) -> tuple[str, str]:
    template = _PROMPT_PATH.read_text()
    user = (
        template
        .replace("<<EXISTING_RULES_SUMMARY>>", existing_rules_summary or "(none yet)")
        .replace("<<EXEMPTION_CODE_OPTIONS>>", exemption_code_options)
        .replace("<<INSTRUCTION>>", instruction)
    )
    system = "You are a precise rules-engine assistant. Output strict JSON only."
    return system, user


def summarize_existing_rules(rules: list) -> str:
    if not rules:
        return "(none yet)"
    lines = []
    for rule in rules:
        code = rule.exemption_code_id or rule.exemption_library_code or "(none)"
        lines.append(f"- {rule.rule_key} [{rule.trigger_type}] \"{rule.name}\" -> {code}: {json.dumps(rule.config)}")
    return "\n".join(lines)


def validate_regex(pattern: str) -> str | None:
    try:
        re.compile(pattern)
    except re.error as exc:
        return f"invalid regex pattern: {exc}"
    return None


def _validate_change(raw: dict, existing_rule_keys: set[str], allowed_codes: set[str]) -> str | None:
    """Returns a rejection reason, or None if valid."""
    action = raw.get("action")
    if action not in VALID_ACTIONS:
        return f"invalid action {action!r}"

    rule_key = raw.get("rule_key")
    if not rule_key:
        return "missing rule_key"
    if action == "edit" and rule_key not in existing_rule_keys:
        return f"action=edit references unknown rule_key {rule_key!r}"

    trigger_type = raw.get("trigger_type")
    if trigger_type is not None and trigger_type not in VALID_TRIGGER_TYPES:
        return f"invalid trigger_type {trigger_type!r} (must be one of {VALID_TRIGGER_TYPES})"

    exemption_code = raw.get("exemption_code")
    if exemption_code is not None and exemption_code not in allowed_codes:
        return f"exemption_code {exemption_code!r} is not in the allowed taxonomy — the model invented a code"

    config = raw.get("config")
    if trigger_type == "regex" and config and "pattern" in config:
        error = validate_regex(config["pattern"])
        if error:
            return error

    if action == "new" and not trigger_type:
        return "action=new requires trigger_type"
    if action == "new" and not config:
        return "action=new requires config"

    return None


def parse_and_validate_diff(response_text: str, existing_rule_keys: set[str], allowed_codes: set[str]) -> list[ProposedRuleChange]:
    """Never raises — a malformed response yields zero proposed changes, matching
    app/pipeline/contextual.py's parse_findings() failure behavior."""
    try:
        match = re.search(r"\{.*\}", response_text, re.DOTALL)
        if not match:
            return []
        payload = json.loads(match.group(0))
        raw_changes = payload.get("changes", [])
    except (json.JSONDecodeError, TypeError):
        return []

    proposals = []
    for raw in raw_changes:
        if not isinstance(raw, dict):
            continue
        invalid_reason = _validate_change(raw, existing_rule_keys, allowed_codes)
        proposals.append(
            ProposedRuleChange(
                action=raw.get("action", ""), rule_key=raw.get("rule_key", ""), name=raw.get("name"),
                trigger_type=raw.get("trigger_type"), config=raw.get("config"),
                exemption_code=raw.get("exemption_code"), exclusions=raw.get("exclusions") or [],
                rationale=str(raw.get("rationale", ""))[:240], invalid_reason=invalid_reason,
            )
        )
    return proposals


def run_nl_edit(
    provider: LLMProvider, instruction: str, existing_rules: list, allowed_codes: set[str]
) -> tuple[list[ProposedRuleChange], int, int]:
    """Returns (proposals, input_tokens, output_tokens)."""
    existing_rule_keys = {r.rule_key for r in existing_rules}
    system, user = render_prompt(instruction, summarize_existing_rules(existing_rules), ", ".join(sorted(allowed_codes)))
    response = provider.complete(system, user)
    proposals = parse_and_validate_diff(response.text, existing_rule_keys, allowed_codes)
    return proposals, response.input_tokens, response.output_tokens
