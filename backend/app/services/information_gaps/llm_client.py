"""LLM call boundary for information-gap assessment. Same shape as the
extraction/contradiction clients: one forced tool call, no free-form
fallback.
"""

from __future__ import annotations

from typing import Protocol

from app.services.information_gaps.schemas import (
    GAP_ASSESSMENT_TOOL_NAME,
    GAP_ASSESSMENT_TOOL_SCHEMA,
    GapAssessmentContext,
    SYSTEM_PROMPT,
)


class LLMCallError(Exception):
    pass


class GapAssessmentLLMClient(Protocol):
    def assess(self, prompt: str) -> dict: ...


class AnthropicGapAssessmentClient:
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
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=[GAP_ASSESSMENT_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": GAP_ASSESSMENT_TOOL_NAME},
                messages=[{"role": "user", "content": prompt}],
            )
        except anthropic.APIError as e:
            raise LLMCallError(f"Anthropic API call failed: {e}") from e

        for block in response.content:
            if block.type == "tool_use" and block.name == GAP_ASSESSMENT_TOOL_NAME:
                return block.input

        raise LLMCallError("Model did not return the required tool call")


def build_context_prompt(context: GapAssessmentContext) -> str:
    lines = [f"Incident: {context.incident_title}"]

    def section(title: str, items: list[str]):
        lines.append(f"{title}:")
        if items:
            lines.extend(f"  - {item}" for item in items)
        else:
            lines.append("  (none)")

    section("Confirmed facts", context.confirmed_facts)
    section("Decisions", context.decisions)
    section("Actions", context.actions)
    return "\n".join(lines)
