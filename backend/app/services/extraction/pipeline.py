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

from typing import Optional

from app.models.enums import ActionStatus, ClaimStatus, ClaimType, RiskSeverity
from app.models.incident import Action, Claim, Conflict, InformationGap, Risk
from app.services.contradiction.service import ContradictionEngine
from app.services.extraction.schemas import ExtractionContext, ExtractionResponse
from app.services.incident_state.service import IncidentStateService, InvalidStateTransitionError
from app.services.information_gaps.service import GapEngine

logger = logging.getLogger("extraction")


class ExtractionApplyResult(BaseModel):
    claims: list[Claim] = Field(default_factory=list)
    actions: list[Action] = Field(default_factory=list)
    risks: list[Risk] = Field(default_factory=list)
    conflicts: list[Conflict] = Field(default_factory=list)
    completed_actions: list[Action] = Field(default_factory=list)
    gaps_created: list[InformationGap] = Field(default_factory=list)
    gaps_resolved: list[InformationGap] = Field(default_factory=list)
    role_updated: bool = False


def apply_extraction(
    service: IncidentStateService,
    incident_id: str,
    context: ExtractionContext,
    extraction: ExtractionResponse,
    contradiction_engine: Optional[ContradictionEngine] = None,
    gap_engine: Optional[GapEngine] = None,
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
                entities=extracted.entities,
            )
            result.claims.append(claim)
            if contradiction_engine is not None:
                result.conflicts.extend(
                    contradiction_engine.detect_and_record(service, incident_id, claim)
                )
            if extracted.completes_action_id:
                completed = _complete_action_from_claim(
                    service, incident_id, extracted.completes_action_id, claim
                )
                if completed is not None:
                    result.completed_actions.append(completed)

    if gap_engine is not None:
        gap_result = gap_engine.recompute(service, incident_id)
        result.gaps_created = gap_result.created
        result.gaps_resolved = gap_result.resolved

    return result


def _complete_action_from_claim(
    service: IncidentStateService, incident_id: str, action_id: str, claim: Claim
) -> Action | None:
    incident = service.get(incident_id)
    action = incident.actions.get(action_id)
    if action is None or action.status not in (
        ActionStatus.OPEN,
        ActionStatus.IN_PROGRESS,
        ActionStatus.BLOCKED,
    ):
        # The model referenced an action ID that doesn't exist or is
        # already closed out — treat this the same as any other
        # extraction slip: log and skip, never crash the pipeline over it.
        logger.warning(
            "extraction_referenced_invalid_action",
            extra={"incident_id": incident_id, "action_id": action_id},
        )
        return None
    try:
        return service.update_action_status(
            incident_id,
            action_id,
            ActionStatus.COMPLETED,
            completion_evidence=claim.evidence or claim.text,
        )
    except InvalidStateTransitionError:
        logger.warning(
            "extraction_action_completion_race",
            extra={"incident_id": incident_id, "action_id": action_id},
        )
        return None
