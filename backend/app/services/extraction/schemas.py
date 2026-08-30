"""Strict structured-output schema for the extraction layer.

The LLM never gets to emit free-form text into incident state. Every
response is forced through the Anthropic tool-use interface (see
llm_client.py) and then validated against these Pydantic models — a
response that doesn't conform is treated as a failed extraction (see
service.py's retry/degrade logic), never coerced or partially trusted.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import ClaimStatus, ClaimType, ParticipantRole, RiskSeverity

# JSON Schema handed to the LLM as a forced tool call. Keeping this in sync
# with ExtractedClaim/ExtractionResponse below is enforced by
# test_extraction_schema_matches_tool_spec.
EXTRACTION_TOOL_NAME = "extract_incident_claims"

EXTRACTION_TOOL_SCHEMA = {
    "name": EXTRACTION_TOOL_NAME,
    "description": (
        "Record the structured incident-relevant claims found in one speaker's utterance. "
        "Return an empty claims array if the utterance carries no incident-relevant content "
        "(greetings, filler, off-topic chat)."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "speaker_role_hint": {
                "type": ["string", "null"],
                "enum": [r.value for r in ParticipantRole] + [None],
                "description": "Best guess at the speaker's incident role from this utterance alone, or null if there is no signal.",
            },
            "speaker_role_confidence": {
                "type": "number",
                "minimum": 0.0,
                "maximum": 1.0,
            },
            "claims": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "type": {"type": "string", "enum": [t.value for t in ClaimType]},
                        "status": {"type": "string", "enum": [s.value for s in ClaimStatus]},
                        "claim": {
                            "type": "string",
                            "description": "Normalized, canonical form of the claim — not a verbatim quote.",
                        },
                        "confidence": {"type": "number", "minimum": 0.0, "maximum": 1.0},
                        "evidence": {
                            "type": ["string", "null"],
                            "description": "Why this status was assigned, e.g. 'speaker states they checked the dashboard'. Required for CONFIRMED or RESOLVED.",
                        },
                        "entities": {"type": "array", "items": {"type": "string"}},
                        "action_owner": {
                            "type": ["string", "null"],
                            "description": "Name mentioned as owner, only for type=ACTION.",
                        },
                        "severity": {
                            "type": ["string", "null"],
                            "enum": [s.value for s in RiskSeverity] + [None],
                            "description": "Only for type=RISK.",
                        },
                        "temporal_info": {"type": ["string", "null"]},
                        "references_previous_claim_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "IDs from the provided recent-claims context this claim relates to.",
                        },
                        "contradiction_candidate_claim_ids": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "IDs from the provided recent-claims context this claim may contradict.",
                        },
                    },
                    "required": ["type", "status", "claim", "confidence"],
                },
            },
        },
        "required": ["claims"],
    },
}


class ExtractedClaim(BaseModel):
    type: ClaimType
    status: ClaimStatus
    claim: str
    confidence: float = Field(ge=0.0, le=1.0)
    evidence: Optional[str] = None
    entities: list[str] = Field(default_factory=list)
    action_owner: Optional[str] = None
    severity: Optional[RiskSeverity] = None
    temporal_info: Optional[str] = None
    references_previous_claim_ids: list[str] = Field(default_factory=list)
    contradiction_candidate_claim_ids: list[str] = Field(default_factory=list)


class ExtractionResponse(BaseModel):
    speaker_role_hint: Optional[ParticipantRole] = None
    speaker_role_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    claims: list[ExtractedClaim] = Field(default_factory=list)


class RecentClaimContext(BaseModel):
    """Compact prior-claim context handed to the LLM so it can reference or
    flag contradictions against real claim IDs instead of inventing them.
    """

    id: str
    type: ClaimType
    status: ClaimStatus
    normalized_claim: str


class ExtractionContext(BaseModel):
    incident_title: str
    speaker_id: Optional[str] = None
    speaker_name: str
    speaker_role: Optional[ParticipantRole] = None
    utterance_text: str
    recent_claims: list[RecentClaimContext] = Field(default_factory=list)
