"""LLM call boundary for extraction.

This is the only place the Anthropic SDK is touched. It does one thing:
force a tool call matching EXTRACTION_TOOL_SCHEMA and hand back the raw
input dict the model produced. It does not validate business rules (that's
ExtractionService, against the Pydantic schema) and it never falls back to
free-form text parsing — if the model doesn't return the tool call, that is
a failure, not a degraded-but-acceptable result.
"""

from __future__ import annotations

from typing import Protocol

from app.services.extraction.schemas import EXTRACTION_TOOL_NAME, EXTRACTION_TOOL_SCHEMA

SYSTEM_PROMPT = """You are the extraction layer of an incident-commander system. You read one \
utterance at a time from a live incident call and convert it into structured claims by calling \
the extract_incident_claims tool. You never respond in free text.

Epistemic rules — these are safety-critical, not stylistic:
- FACT + CONFIRMED: only when the speaker states direct, first-hand verification (checked, saw, \
tested, confirmed, ran a query, looked at a dashboard/log). Evidence is required and must name \
what they actually verified.
- HYPOTHESIS: any possible explanation that has not been directly verified, including phrases \
like "I think", "maybe", "could be", "probably". Status is UNCONFIRMED unless there is partial \
supporting evidence, in which case PROBABLE. NEVER mark a hypothesis CONFIRMED, no matter how \
many times it is repeated or how confidently it is stated — repetition is not verification.
- DECISION: only explicit team agreement ("let's roll back", "we've decided", "agreed, let's \
..."). A proposal alone ("should we roll back?") is a QUESTION, not a DECISION.
- ACTION: work assigned to a named person ("Bob, check the network metrics"). Extract the owner \
into action_owner. If no owner is named, leave action_owner null — never invent one.
- QUESTION: something that needs an answer and has not been answered yet.
- RISK: a potential negative consequence, not something that has already happened.
- UPDATE: a status change on something already known, that isn't itself a new fact/hypothesis.

Global rules:
- Never invent metrics, timestamps, owners, or outcomes that were not stated.
- Never upgrade a claim's confidence or status based on tone or repetition alone.
- If the utterance carries no incident-relevant content, return an empty claims array — do not \
force a classification.
- Use the provided recent-claims context to populate references_previous_claim_ids and \
contradiction_candidate_claim_ids using their real IDs. Only flag a contradiction candidate when \
the new claim and the prior claim cannot both be true as stated.
- confidence reflects your certainty in the *extraction* (did I classify this utterance \
correctly), not the truth of the claim itself — status/evidence carry the truth judgment.
"""


class LLMCallError(Exception):
    pass


class LLMExtractionClient(Protocol):
    def extract(self, context_prompt: str) -> dict: ...


class AnthropicExtractionClient:
    def __init__(self, api_key: str, model: str) -> None:
        if not api_key:
            raise LLMCallError("LLM_API_KEY is not configured")
        # Imported lazily so the module can be imported (e.g. for schema
        # tests) without the anthropic package being usable/networked.
        import anthropic

        self._client = anthropic.Anthropic(api_key=api_key)
        self._model = model

    def extract(self, context_prompt: str) -> dict:
        import anthropic

        try:
            response = self._client.messages.create(
                model=self._model,
                max_tokens=1024,
                system=SYSTEM_PROMPT,
                tools=[EXTRACTION_TOOL_SCHEMA],
                tool_choice={"type": "tool", "name": EXTRACTION_TOOL_NAME},
                messages=[{"role": "user", "content": context_prompt}],
            )
        except anthropic.APIError as e:
            raise LLMCallError(f"Anthropic API call failed: {e}") from e

        for block in response.content:
            if block.type == "tool_use" and block.name == EXTRACTION_TOOL_NAME:
                return block.input

        raise LLMCallError("Model did not return the required tool call")


def build_context_prompt(context) -> str:
    """context: ExtractionContext. Kept as a free function so it's testable
    without constructing a real client.
    """
    lines = [
        f"Incident: {context.incident_title}",
        f"Speaker: {context.speaker_name}"
        + (f" (role: {context.speaker_role.value})" if context.speaker_role else " (role unknown)"),
    ]
    if context.recent_claims:
        lines.append("Recent claims (id | type | status | claim):")
        for c in context.recent_claims:
            lines.append(f"  {c.id} | {c.type.value} | {c.status.value} | {c.normalized_claim}")
    else:
        lines.append("Recent claims: none yet.")
    lines.append(f'Utterance: "{context.utterance_text}"')
    return "\n".join(lines)
