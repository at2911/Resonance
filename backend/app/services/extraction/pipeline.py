"""Deterministic mapping from a validated ExtractionResponse into real
IncidentState mutations.

This is intentionally separate from ExtractionService: the LLM produces a
structured opinion about an utterance, but only this code decides how that
opinion becomes state, and it enforces the same anti-hallucination rule the
state engine enforces — a claim the model marked CONFIRMED/RESOLVED without
evidence is never passed through as-is, it is safely downgraded to
PROBABLE and logged, rather than raising and dropping the whole utterance.
"""

from __future__ import annotations

import logging

from pydantic import BaseModel, Field

from app.models.enums import ClaimStatus, ClaimType, RiskSeverity
from app.models.incident import Action, Claim, Risk
from app.services.extraction.schemas import ExtractionContext, ExtractionResponse
from app.services.incident_state.service import IncidentStateService

logger = logging.getLogger("extraction")


class ExtractionApplyResult(BaseModel):
    claims: list[Claim] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    role_updated: bool = False


def apply_extraction(
    service: IncidentStateService,
    incident_id: str,
    context: ExtractionContext,
    extraction: ExtractionResponse,
) -> ExtractionApplyResult:
    result = ExtractionApplyResult()

    if context.speaker_id and extraction.speaker_role_hint is not None:
        participant = service.get(incident_id).participants.get(context.speaker_id)
        if participant is not None:
            # Snapshot the confidence as a plain float before mutating — the
            # repository is in-memory and hands back the live object, so
            # holding a reference to `participant` itself would already
            # reflect the post-update value once update_role_if_more_confident
            # runs, making any before/after comparison against it a no-op.
            before_confidence = participant.role_confidence
            after = service.update_role_if_more_confident(
                incident_id,
                context.speaker_id,
                extraction.speaker_role_hint,
                extraction.speaker_role_confidence,
            )
            result.role_updated = after.role_confidence != before_confidence

    for extracted in extraction.claims:
        status = extracted.status
        evidence = extracted.evidence or None
        if status in (ClaimStatus.CONFIRMED, ClaimStatus.RESOLVED) and not evidence:
            logger.warning(
                "extraction_status_downgraded",
                extra={
                    "incident_id": incident_id,
                    "claim": extracted.claim,
                    "requested_status": status.value,
                },
            )
            status = ClaimStatus.PROBABLE

        if extracted.type == ClaimType.ACTION:
            action = service.add_action(
                incident_id,
                description=extracted.claim,
                owner=extracted.action_owner,
                owner_confidence=extracted.confidence if extracted.action_owner else 0.0,
            )
            result.actions.append(action)
        elif extracted.type == ClaimType.RISK:
            risk = service.add_risk(
                incident_id,
                description=extracted.claim,
                severity=extracted.severity or RiskSeverity.MEDIUM,
                confidence=extracted.confidence,
            )
            result.risks.append(risk)
        else:
            claim = service.add_claim(
                incident_id,
                text=context.utterance_text,
                normalized_claim=extracted.claim,
                type=extracted.type,
                status=status,
                confidence=extracted.confidence,
                speaker_id=context.speaker_id,
                evidence=evidence,
            )
            result.claims.append(claim)

    return result
