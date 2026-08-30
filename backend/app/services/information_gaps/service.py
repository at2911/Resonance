"""Information Gap Engine.

Runs a full recompute against the fixed dimension checklist (§9) rather
than reasoning incrementally per-utterance — coverage of a dimension like
"customer impact" can only be judged against the whole known picture, not
one claim at a time. A failed/degraded assessment makes no state changes
at all (never auto-resolves a real gap, never spams a false one) rather
than guessing.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field, ValidationError

from app.models.enums import ClaimStatus, ClaimType
from app.models.incident import Incident, InformationGap
from app.services.incident_state.service import IncidentStateService
from app.services.information_gaps.llm_client import GapAssessmentLLMClient, LLMCallError, build_context_prompt
from app.services.information_gaps.schemas import (
    DIMENSION_IMPORTANCE,
    GapAssessmentContext,
    GapAssessmentResponse,
)

logger = logging.getLogger("information_gaps")


class GapRecomputeResult(BaseModel):
    created: list[InformationGap] = Field(default_factory=list)
    resolved: list[InformationGap] = Field(default_factory=list)
    degraded: bool = False


def build_context(incident: Incident) -> GapAssessmentContext:
    confirmed_facts = [
        c.normalized_claim
        for c in incident.claims.values()
        if c.type == ClaimType.FACT and c.status == ClaimStatus.CONFIRMED
    ]
    decisions = [c.normalized_claim for c in incident.claims.values() if c.type == ClaimType.DECISION]
    actions = [
        f"{a.description} (owner: {a.owner or 'unassigned'}, status: {a.status.value})"
        for a in incident.actions.values()
    ]
    return GapAssessmentContext(
        incident_title=incident.title,
        confirmed_facts=confirmed_facts,
        decisions=decisions,
        actions=actions,
    )


class GapEngine:
    def __init__(self, llm_client: GapAssessmentLLMClient, max_attempts: int = 2) -> None:
        self._llm_client = llm_client
        self._max_attempts = max_attempts

    def assess(self, context: GapAssessmentContext) -> GapAssessmentResponse | None:
        prompt = build_context_prompt(context)
        last_error: Exception | None = None
        for attempt in range(1, self._max_attempts + 1):
            try:
                raw = self._llm_client.assess(prompt)
                return GapAssessmentResponse.model_validate(raw)
            except (LLMCallError, ValidationError) as e:
                last_error = e
                logger.warning(
                    "gap_assessment_attempt_failed", extra={"attempt": attempt, "error": str(e)}
                )
                if attempt < self._max_attempts:
                    prompt = (
                        prompt
                        + f"\n\nYour previous response was invalid: {e}. "
                        + "Call assess_information_gaps again with a corrected, schema-valid response covering every dimension."
                    )
        logger.error("gap_assessment_degraded", extra={"error": str(last_error)})
        return None

    def recompute(self, service: IncidentStateService, incident_id: str) -> GapRecomputeResult:
        incident = service.get(incident_id)
        assessment = self.assess(build_context(incident))
        if assessment is None:
            return GapRecomputeResult(degraded=True)

        existing_open_by_dimension = {
            g.dimension: g
            for g in incident.information_gaps.values()
            if g.status.value == "OPEN" and g.dimension is not None
        }

        result = GapRecomputeResult()
        for d in assessment.dimensions:
            existing = existing_open_by_dimension.get(d.dimension)
            if not d.covered:
                if existing is None:
                    gap = service.add_information_gap(
                        incident_id,
                        description=d.gap_description,
                        importance=DIMENSION_IMPORTANCE[d.dimension],
                        dimension=d.dimension,
                    )
                    result.created.append(gap)
            else:
                if existing is not None:
                    resolved = service.resolve_information_gap(incident_id, existing.id)
                    result.resolved.append(resolved)

        return result
