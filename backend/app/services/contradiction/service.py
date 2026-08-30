"""Contradiction Engine.

Two deliberate stages, so the expensive/fuzzy part (semantic judgment) only
ever runs on a small, cheaply-filtered candidate set:

1. Candidate generation (`find_candidates`) — pure, deterministic, no LLM.
   Claims are normalized to their extracted entity set and only claims that
   share at least one entity and belong to an eligible claim type are even
   considered. This is the "normalize into comparable representations"
   step the spec asks for — it is not string/keyword opposite-matching, it
   is topical relevance filtering.
2. Verification (`assess_pair`) — a dedicated LLM call judges whether the
   two claims can both be true. A claim pair is never marked conflicting
   by keyword heuristics; that judgment is always made against the actual
   meaning of both normalized claims.

`detect_and_record` ties these together and writes through
IncidentStateService.add_conflict, which is what actually marks both
claims DISPUTED and preserves both — this engine never mutates a Claim
directly.
"""

from __future__ import annotations

import logging

from pydantic import ValidationError

from app.models.enums import ClaimStatus, ClaimType
from app.models.incident import Claim, Conflict, Incident
from app.services.contradiction.llm_client import (
    ContradictionLLMClient,
    LLMCallError,
    build_pair_prompt,
)
from app.services.contradiction.schemas import ContradictionVerdict
from app.services.incident_state.service import IncidentStateService

logger = logging.getLogger("contradiction")

# Only claims that assert something about the world are eligible — DECISION,
# ACTION, and QUESTION are not the kind of statement that "contradicts"
# another in the sense this engine checks.
ELIGIBLE_TYPES = frozenset({ClaimType.FACT, ClaimType.HYPOTHESIS, ClaimType.UPDATE})

# A claim that has been superseded or already resolved is no longer a live
# assertion worth checking against.
INELIGIBLE_STATUSES = frozenset({ClaimStatus.SUPERSEDED, ClaimStatus.RESOLVED})


def find_candidates(new_claim: Claim, existing_claims: list[Claim]) -> list[Claim]:
    if new_claim.type not in ELIGIBLE_TYPES:
        return []
    new_entities = {e.lower() for e in new_claim.entities}
    candidates = []
    for other in existing_claims:
        if other.id == new_claim.id:
            continue
        if other.type not in ELIGIBLE_TYPES:
            continue
        if other.status in INELIGIBLE_STATUSES:
            continue
        other_entities = {e.lower() for e in other.entities}
        if new_entities and other_entities and new_entities & other_entities:
            candidates.append(other)
    return candidates


def _already_conflicting(incident: Incident, claim_a_id: str, claim_b_id: str) -> bool:
    pair = {claim_a_id, claim_b_id}
    return any(
        {c.claim_a, c.claim_b} == pair and c.status.value != "RESOLVED"
        for c in incident.conflicts.values()
    )


class ContradictionEngine:
    def __init__(self, llm_client: ContradictionLLMClient) -> None:
        self._llm_client = llm_client

    def assess_pair(self, claim_a: Claim, claim_b: Claim) -> ContradictionVerdict:
        prompt = build_pair_prompt(claim_a, claim_b)
        try:
            raw = self._llm_client.assess(prompt)
            return ContradictionVerdict.model_validate(raw)
        except (LLMCallError, ValidationError) as e:
            # Fail safe: never fabricate a conflict from an error. A missed
            # contradiction is recoverable (a later claim can re-trigger
            # detection); a false conflict pollutes the incident state.
            logger.warning(
                "contradiction_assessment_failed",
                extra={"claim_a": claim_a.id, "claim_b": claim_b.id, "error": str(e)},
            )
            return ContradictionVerdict(conflicts=False)

    def detect_and_record(
        self, service: IncidentStateService, incident_id: str, new_claim: Claim
    ) -> list[Conflict]:
        incident = service.get(incident_id)
        candidates = find_candidates(new_claim, list(incident.claims.values()))

        created: list[Conflict] = []
        for candidate in candidates:
            if _already_conflicting(incident, new_claim.id, candidate.id):
                continue
            verdict = self.assess_pair(new_claim, candidate)
            if not verdict.conflicts:
                continue
            conflict = service.add_conflict(
                incident_id,
                claim_a=new_claim.id,
                claim_b=candidate.id,
                conflict_type=verdict.conflict_type,
                explanation=verdict.explanation,
            )
            created.append(conflict)
            incident = service.get(incident_id)

        return created
