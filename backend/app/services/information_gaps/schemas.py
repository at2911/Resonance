"""Structured output schema for the Information Gap Engine.

Importance per dimension is deliberately NOT decided by the LLM — it's a
fixed product-policy mapping (DIMENSION_IMPORTANCE below), matching the
spec's own example (customer impact / rollback status are CRITICAL, start
time is NORMAL). The LLM's only job is the part that actually needs
judgment: given what's been established so far, is this dimension covered
or not, and if not, a one-line description of what's missing.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field, model_validator

from app.models.enums import GapImportance, IncidentDimension

GAP_ASSESSMENT_TOOL_NAME = "assess_information_gaps"

# root_cause is intentionally NORMAL, not CRITICAL: not having a confirmed
# root cause early in an incident is expected, not alarming — it already
# has its own explicit "root cause remains unconfirmed" signal in the
# final summary and clarity score (Incident.root_cause_confirmed). Treating
# it as a normal-importance gap here avoids double-penalizing clarity score
# for something that isn't actually a missing-information problem.
DIMENSION_IMPORTANCE: dict[IncidentDimension, GapImportance] = {
    IncidentDimension.AFFECTED_SERVICE: GapImportance.CRITICAL,
    IncidentDimension.CUSTOMER_IMPACT: GapImportance.CRITICAL,
    IncidentDimension.CURRENT_SYSTEM_HEALTH: GapImportance.CRITICAL,
    IncidentDimension.ROLLBACK_STATUS: GapImportance.CRITICAL,
    IncidentDimension.IMPACT: GapImportance.NORMAL,
    IncidentDimension.START_TIME: GapImportance.NORMAL,
    IncidentDimension.SYMPTOMS: GapImportance.NORMAL,
    IncidentDimension.RECENT_CHANGES: GapImportance.NORMAL,
    IncidentDimension.DEPLOYMENT: GapImportance.NORMAL,
    IncidentDimension.MITIGATION: GapImportance.NORMAL,
    IncidentDimension.OWNER: GapImportance.NORMAL,
    IncidentDimension.ROOT_CAUSE: GapImportance.NORMAL,
}

_DIMENSION_DESCRIPTIONS = {
    IncidentDimension.AFFECTED_SERVICE: "Which service/system is affected",
    IncidentDimension.IMPACT: "What the observable impact is (errors, latency, downtime, etc.)",
    IncidentDimension.START_TIME: "When the incident started",
    IncidentDimension.SYMPTOMS: "What symptoms were observed",
    IncidentDimension.RECENT_CHANGES: "Any recent changes to the system (config, code, infra)",
    IncidentDimension.DEPLOYMENT: "Whether a recent deployment is implicated",
    IncidentDimension.CUSTOMER_IMPACT: "Whether and how customers are affected",
    IncidentDimension.CURRENT_SYSTEM_HEALTH: "The current health/status of the affected system",
    IncidentDimension.MITIGATION: "Any mitigation in progress or planned",
    IncidentDimension.OWNER: "Who owns driving the incident to resolution",
    IncidentDimension.ROOT_CAUSE: "Whether a root cause has been confirmed (not just hypothesized)",
    IncidentDimension.ROLLBACK_STATUS: "Whether a rollback has happened, is planned, or was rejected",
}

GAP_ASSESSMENT_TOOL_SCHEMA = {
    "name": GAP_ASSESSMENT_TOOL_NAME,
    "description": (
        "Assess, for each of the fixed incident dimensions, whether it is covered by what has "
        "actually been established (confirmed facts, decisions, actions) so far. Every dimension "
        "must appear exactly once."
    ),
    "input_schema": {
        "type": "object",
        "properties": {
            "dimensions": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "dimension": {"type": "string", "enum": [d.value for d in IncidentDimension]},
                        "covered": {
                            "type": "boolean",
                            "description": "True only if this has actually been explicitly established, not merely implied.",
                        },
                        "gap_description": {
                            "type": ["string", "null"],
                            "description": "Required when covered is false — a short, concrete statement of what's missing, e.g. 'Customer impact unknown'.",
                        },
                    },
                    "required": ["dimension", "covered"],
                },
            }
        },
        "required": ["dimensions"],
    },
}

SYSTEM_PROMPT = (
    "You audit an incident's known information against a fixed checklist of dimensions by "
    "calling assess_information_gaps. For each dimension below, decide if it is covered — "
    "meaning explicitly and concretely established by what's provided, not guessed or assumed — "
    "using only the confirmed facts, decisions, and actions given to you. Never mark something "
    "covered because it seems likely; if it wasn't stated, it's not covered. You must return "
    "every dimension listed, exactly once each.\n\n"
    + "\n".join(f"- {d.value}: {desc}" for d, desc in _DIMENSION_DESCRIPTIONS.items())
)


class DimensionAssessment(BaseModel):
    dimension: IncidentDimension
    covered: bool
    gap_description: Optional[str] = None

    @model_validator(mode="after")
    def require_description_when_not_covered(self) -> "DimensionAssessment":
        if not self.covered and not self.gap_description:
            raise ValueError("gap_description is required when covered is false")
        return self


class GapAssessmentResponse(BaseModel):
    dimensions: list[DimensionAssessment]

    @model_validator(mode="after")
    def require_every_dimension_exactly_once(self) -> "GapAssessmentResponse":
        seen = [d.dimension for d in self.dimensions]
        if set(seen) != set(IncidentDimension) or len(seen) != len(IncidentDimension):
            raise ValueError("Response must include every IncidentDimension exactly once")
        return self


class GapAssessmentContext(BaseModel):
    incident_title: str
    confirmed_facts: list[str] = Field(default_factory=list)
    decisions: list[str] = Field(default_factory=list)
    actions: list[str] = Field(default_factory=list)
