"""LLM call boundary for pairwise contradiction assessment.

Mirrors app/services/extraction/llm_client.py's shape deliberately: one
forced tool call, no free-form fallback, so ContradictionEngine can be
tested against a fake at this exact seam.
"""

from __future__ import annotations

from typing import Protocol

from app.services.contradiction.schemas import (
    CONTRADICTION_TOOL_NAME,
    CONTRADICTION_TOOL_SCHEMA,
    SYSTEM_PROMPT,
)


class LLMCallError(Exception):
    pass


class ContradictionLLMClient(Protocol):
    def assess(self, prompt: str) -> dict: ...


class AnthropicContradictionClient:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise LLMCallError("LLM_API_KEY is not configured")
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def assess(self, prompt: str) -> dict:
        import anthropic

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=512,
                system=SYSTEM_PROMPT,
                tools=[CONTRADICTION_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": CONTRADICTION_TOOL_NAME},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as e:
            raise LLMCallError(f"Anthropic API call failed: {e}") from e

        for block in response.content:
            if block.type == "tool_use" and block.name == CONTRADICTION_TOOL_NAME:
                return block.input

        raise LLMCallError("Model did not return the required tool call")


def build_pair_prompt(claim_a, claim_b) -> str:
    """claim_a, claim_b: app.models.incident.Claim."""

    def describe(c):
        return f'[{c.id}] type={c.type.value} status={c.status.value} claim="{c.normalized_claim}"'

    return f"Claim A: {describe(claim_a)}\nClaim B: {describe(claim_b)}"
