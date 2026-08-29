"""specs/02-architecture.md ADR-5: contextual LLM pass behind `app/llm/provider.py` — model
id, prompt version, zero-retention config, token accounting per org, stamped on every
candidate for auditability. Same provider-seam pattern as auth/crypto/storage: a real
`BedrockProvider` for prod, a `FakeLLMProvider` for local dev/tests (selected by env, same
as everywhere else — see get_provider() below).

CLAUDE.md invariant #6: "No customer content in logs, traces, prompts stored at rest, or
model training." This module logs token counts and model/prompt version, never the prompt
or completion text itself.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass

from app.core.config import Settings, get_settings

# PLACEHOLDER — not a verified Bedrock model catalog ID. Confirm the actual available
# Claude model ID in the AWS Bedrock console (Model access page) for the target region
# once an account with Bedrock enabled exists, and set it via BEDROCK_MODEL_ID env var
# rather than trusting this constant. Deliberately not guessing a real-looking ID here.
BEDROCK_MODEL_ID = "REPLACE_ME_WITH_VERIFIED_BEDROCK_MODEL_ID"


@dataclass
class LLMResponse:
    text: str
    input_tokens: int
    output_tokens: int


class LLMProvider(ABC):
    model_id: str

    @abstractmethod
    def complete(self, system: str, user: str, max_tokens: int = 2048) -> LLMResponse: ...


class BedrockProvider(LLMProvider):
    """Real Bedrock inference. Not testable without an AWS account with Bedrock model
    access enabled — that doesn't exist yet (flagged explicitly, not silently assumed).
    zero-retention / no-training is a contractual + account-level Bedrock setting, not a
    per-call parameter — there is nothing to set here beyond using an in-boundary US
    inference profile (specs/08-security-compliance.md § AI governance).
    """

    def __init__(self, region: str, model_id: str | None = None) -> None:
        import boto3

        self.model_id = model_id or BEDROCK_MODEL_ID
        if self.model_id == BEDROCK_MODEL_ID:
            raise RuntimeError(
                "BEDROCK_MODEL_ID is still the unverified placeholder — set the real model "
                "id (from the AWS Bedrock console's Model access page) via the "
                "BEDROCK_MODEL_ID env var before using BedrockProvider."
            )
        self._client = boto3.client("bedrock-runtime", region_name=region)

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> LLMResponse:
        import json

        body = json.dumps(
            {
                "anthropic_version": "bedrock-2023-05-31",
                "max_tokens": max_tokens,
                "system": system,
                "messages": [{"role": "user", "content": user}],
            }
        )
        response = self._client.invoke_model(modelId=self.model_id, body=body)
        payload = json.loads(response["body"].read())
        text = "".join(block["text"] for block in payload["content"] if block["type"] == "text")
        usage = payload.get("usage", {})
        return LLMResponse(
            text=text,
            input_tokens=usage.get("input_tokens", 0),
            output_tokens=usage.get("output_tokens", 0),
        )


class DisabledLLMProvider(LLMProvider):
    """Bedrock isn't configured (bedrock_enabled=false) — used in ANY environment where
    that's true, not just local (get_provider() below used to fall through to a real
    BedrockProvider for env != "local" regardless of bedrock_enabled, which raises
    immediately since BEDROCK_MODEL_ID is still the placeholder — crashing detection
    entirely for any document with a llm_context rule active, which every org has by
    default). Distinct from FakeLLMProvider (that one exists so tests can script
    specific canned responses); this one always returns zero findings — contextual
    suggestions are simply absent, same as the LLM never finding anything, rather than
    the whole pipeline failing."""

    model_id = "disabled-llm-provider"

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> LLMResponse:
        return LLMResponse(text='{"findings": []}', input_tokens=0, output_tokens=0)


class FakeLLMProvider(LLMProvider):
    """Local dev / tests only. Returns pre-programmed responses keyed by a substring match
    against the user prompt, so pipeline tests can exercise chunking/grounding/confidence
    logic deterministically without any live model."""

    model_id = "fake-llm-provider"

    def __init__(self, canned_responses: list[tuple[str, str]] | None = None) -> None:
        # list of (substring_to_match_in_prompt, json_response_text)
        self.canned_responses = canned_responses or []
        self.calls: list[tuple[str, str]] = []

    def complete(self, system: str, user: str, max_tokens: int = 2048) -> LLMResponse:
        self.calls.append((system, user))
        for substring, response_text in self.canned_responses:
            if substring in user:
                return LLMResponse(text=response_text, input_tokens=len(user) // 4, output_tokens=len(response_text) // 4)
        return LLMResponse(text='{"findings": []}', input_tokens=len(user) // 4, output_tokens=5)


def get_provider(settings: Settings | None = None) -> LLMProvider:
    settings = settings or get_settings()
    if not settings.bedrock_enabled:
        return FakeLLMProvider() if settings.env == "local" else DisabledLLMProvider()
    return BedrockProvider(settings.aws_region, settings.bedrock_model_id)
