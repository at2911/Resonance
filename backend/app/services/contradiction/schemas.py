"""Structured output schema for pairwise contradiction assessment."""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.enums import ConflictType

CONTRADICTION_TOOL_NAME = "assess_claim_contradiction"

CONTRADICTION_TOOL_SCHEMA = {
    "name": CONTRADICTION_TOOL_NAME,
    "description": (
        "Judge whether two incident claims genuinely contradict each other — i.e. they cannot "
        "both be true as stated, not merely that they mention the same topic or use different "
        "words. Complementary or unrelated claims are not contradictions."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "conflicts": {"type": "boolean"},
            "conflict_type": {
                "type": ["string", "null"],
                "enum": [t.value for t in ConflictType] + [None],
                "description": "Required when conflicts is true.",
            },
            "explanation": {
                "type": ["string", "null"],
                "description": "One sentence naming what specifically cannot both be true. Required when conflicts is true.",
            },
        },
        "required": ["conflicts"],
    },
}

SYSTEM_PROMPT = """You compare two claims from an incident call and judge whether they genuinely \
contradict each other by calling assess_claim_contradiction.

A contradiction means the two claims cannot both be true as stated — e.g. "the database is \
timing out" and "the database looks healthy" cannot both hold. Do NOT rely on surface wording or \
opposite-sounding words: judge the underlying meaning. Claims about different subjects, claims \
that are merely different explanations for the same symptom (two hypotheses can both be worth \
investigating without contradicting each other), or claims where one is a strict refinement of \
the other, are NOT contradictions — set conflicts to false.

If conflicts is true, pick the closest conflict_type and give a one-sentence explanation naming \
exactly what cannot both be true."""


class ContradictionVerdict(BaseModel):
    conflicts: bool
    conflict_type: Optional[ConflictType] = None
    explanation: Optional[str] = None

    @model_validator(mode="after")
    def require_type_and_explanation_when_conflicting(self) -> "ContradictionVerdict":
        if self.conflicts and (self.conflict_type is None or not self.explanation):
            raise ValueError("conflict_type and explanation are required when conflicts is true")
        return self
