"""Incident State Engine API surface.

Deliberately minimal for this slice: create incident, mutate state through
the same methods the extraction/contradiction/gap/approval services will
call, and read back state/clarity/summary. Extraction, Slack, and Agora
endpoints land in later slices.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.models.incident import (
    Action,
    Claim,
    ClarityScoreBreakdown,
    Conflict,
    ExternalAction,
    FinalSummary,
    Incident,
    InformationGap,
    Participant,
    Risk,
)
from app.repositories.incident_repository import IncidentNotFoundError
from app.schemas.incident_schemas import (
    AddActionRequest,
    AddClaimRequest,
    AddConflictRequest,
    AddInformationGapRequest,
    AddParticipantRequest,
    AddRiskRequest,
    CreateIncidentRequest,
    DecideExternalActionRequest,
    ProposeExternalActionRequest,
    ResolveConflictRequest,
    UpdateActionStatusRequest,
    UpdateClaimStatusRequest,
)
from app.services.incident_state.service import (
    EvidenceRequiredError,
    IncidentStateService,
    InvalidStateTransitionError,
)
from app.services.incident_state.dependency import get_incident_state_service

router = APIRouter(prefix="/incidents", tags=["incidents"])


def _handle(fn):
    try:
        return fn()
    except IncidentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except KeyError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (EvidenceRequiredError, InvalidStateTransitionError, ValueError) as e:
        raise HTTPException(status_code=400, detail=str(e)) from e


ServiceDep = Depends(get_incident_state_service)


@router.post("", response_model=Incident)
def create_incident(req: CreateIncidentRequest, service: IncidentStateService = ServiceDep):
    return _handle(lambda: service.create_incident(req.title, req.severity))


@router.get("", response_model=list[Incident])
def list_incidents(service: IncidentStateService = ServiceDep):
    return _handle(lambda: service.list_all())


@router.get("/{incident_id}", response_model=Incident)
def get_incident(incident_id: str, service: IncidentStateService = ServiceDep):
    return _handle(lambda: service.get(incident_id))


@router.get("/{incident_id}/clarity", response_model=ClarityScoreBreakdown)
def get_clarity(incident_id: str, service: IncidentStateService = ServiceDep):
    return _handle(lambda: service.compute_clarity_score(incident_id))


@router.get("/{incident_id}/summary", response_model=FinalSummary)
def get_summary(incident_id: str, service: IncidentStateService = ServiceDep):
    return _handle(lambda: service.generate_final_summary(incident_id))


@router.post("/{incident_id}/participants", response_model=Participant)
def add_participant(
    incident_id: str, req: AddParticipantRequest, service: IncidentStateService = ServiceDep
):
    return _handle(
        lambda: service.add_participant(incident_id, req.name, req.role, req.role_confidence)
    )


@router.post("/{incident_id}/claims", response_model=Claim)
def add_claim(incident_id: str, req: AddClaimRequest, service: IncidentStateService = ServiceDep):
    return _handle(
        lambda: service.add_claim(
            incident_id,
            req.text,
            req.normalized_claim,
            req.type,
            req.status,
            req.confidence,
            req.speaker_id,
            req.evidence,
        )
    )


@router.patch("/{incident_id}/claims/{claim_id}", response_model=Claim)
def update_claim(
    incident_id: str,
    claim_id: str,
    req: UpdateClaimStatusRequest,
    service: IncidentStateService = ServiceDep,
):
    return _handle(
        lambda: service.update_claim_status(incident_id, claim_id, req.status, req.evidence)
    )


@router.post("/{incident_id}/actions", response_model=Action)
def add_action(
    incident_id: str, req: AddActionRequest, service: IncidentStateService = ServiceDep
):
    return _handle(
        lambda: service.add_action(
            incident_id,
            req.description,
            req.owner,
            req.owner_confidence,
            req.priority,
            req.source_event_id,
            req.dependencies,
        )
    )


@router.patch("/{incident_id}/actions/{action_id}", response_model=Action)
def update_action(
    incident_id: str,
    action_id: str,
    req: UpdateActionStatusRequest,
    service: IncidentStateService = ServiceDep,
):
    return _handle(
        lambda: service.update_action_status(
            incident_id, action_id, req.status, req.completion_evidence
        )
    )


@router.post("/{incident_id}/conflicts", response_model=Conflict)
def add_conflict(
    incident_id: str, req: AddConflictRequest, service: IncidentStateService = ServiceDep
):
    return _handle(
        lambda: service.add_conflict(
            incident_id, req.claim_a, req.claim_b, req.conflict_type, req.explanation
        )
    )


@router.post("/{incident_id}/conflicts/{conflict_id}/resolve", response_model=Conflict)
def resolve_conflict(
    incident_id: str,
    conflict_id: str,
    req: ResolveConflictRequest,
    service: IncidentStateService = ServiceDep,
):
    return _handle(
        lambda: service.resolve_conflict(incident_id, conflict_id, req.resolution_evidence)
    )


@router.post("/{incident_id}/gaps", response_model=InformationGap)
def add_gap(
    incident_id: str, req: AddInformationGapRequest, service: IncidentStateService = ServiceDep
):
    return _handle(
        lambda: service.add_information_gap(
            incident_id, req.description, req.importance, req.related_claims
        )
    )


@router.post("/{incident_id}/gaps/{gap_id}/resolve", response_model=InformationGap)
def resolve_gap(incident_id: str, gap_id: str, service: IncidentStateService = ServiceDep):
    return _handle(lambda: service.resolve_information_gap(incident_id, gap_id))


@router.post("/{incident_id}/risks", response_model=Risk)
def add_risk(incident_id: str, req: AddRiskRequest, service: IncidentStateService = ServiceDep):
    return _handle(
        lambda: service.add_risk(
            incident_id, req.description, req.severity, req.confidence, req.mitigation
        )
    )


@router.post("/{incident_id}/external-actions", response_model=ExternalAction)
def propose_external_action(
    incident_id: str,
    req: ProposeExternalActionRequest,
    service: IncidentStateService = ServiceDep,
):
    return _handle(
        lambda: service.propose_external_action(incident_id, req.action_type, req.payload)
    )


@router.post(
    "/{incident_id}/external-actions/{external_action_id}/decision",
    response_model=ExternalAction,
)
def decide_external_action(
    incident_id: str,
    external_action_id: str,
    req: DecideExternalActionRequest,
    service: IncidentStateService = ServiceDep,
):
    return _handle(
        lambda: service.decide_external_action(
            incident_id, external_action_id, req.approved, req.approved_by
        )
    )
