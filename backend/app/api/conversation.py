"""Entry point for turning one utterance into incident state.

This stands in for the Agora Conversation Gateway for now: later, Agora
transcript events will call the same extract -> apply_extraction pipeline
per utterance instead of an HTTP request. Keeping that pipeline in
app/services/extraction/ rather than inline here means the Agora slice only
has to produce ExtractionContext objects, not duplicate any of this logic.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.repositories.incident_repository import IncidentNotFoundError
from app.schemas.conversation_schemas import AddUtteranceRequest
from app.services.contradiction.llm_client import AnthropicContradictionClient
from app.services.contradiction.llm_client import LLMCallError as ContradictionLLMCallError
from app.services.contradiction.service import ContradictionEngine
from app.services.extraction.llm_client import AnthropicExtractionClient, LLMCallError
from app.services.extraction.pipeline import ExtractionApplyResult, apply_extraction
from app.services.extraction.schemas import ExtractionContext, RecentActionContext, RecentClaimContext
from app.services.extraction.service import ExtractionService
from app.services.incident_state.dependency import get_incident_state_service
from app.services.incident_state.service import IncidentStateService
from app.services.information_gaps.llm_client import AnthropicGapAssessmentClient
from app.services.information_gaps.llm_client import LLMCallError as GapLLMCallError
from app.services.information_gaps.service import GapEngine

router = APIRouter(prefix="/incidents", tags=["conversation"])

RECENT_CLAIMS_WINDOW = 10
OPEN_ACTION_STATUSES = ("OPEN", "IN_PROGRESS", "BLOCKED")


def get_extraction_service() -> ExtractionService:
    settings = get_settings()
    try:
        client = AnthropicExtractionClient(settings.llm_api_key, settings.llm_model)
    except LLMCallError as e:
        raise HTTPException(status_code=503, detail=f"Extraction unavailable: {e}") from e
    return ExtractionService(client)


def get_contradiction_engine() -> ContradictionEngine:
    settings = get_settings()
    try:
        client = AnthropicContradictionClient(settings.llm_api_key, settings.llm_model)
    except ContradictionLLMCallError as e:
        raise HTTPException(status_code=503, detail=f"Contradiction engine unavailable: {e}") from e
    return ContradictionEngine(client)


def get_gap_engine() -> GapEngine:
    settings = get_settings()
    try:
        client = AnthropicGapAssessmentClient(settings.llm_api_key, settings.llm_model)
    except GapLLMCallError as e:
        raise HTTPException(status_code=503, detail=f"Gap engine unavailable: {e}") from e
    return GapEngine(client)


@router.post("/{incident_id}/utterances", response_model=ExtractionApplyResult)
def process_utterance(
    incident_id: str,
    req: AddUtteranceRequest,
    state_service: IncidentStateService = Depends(get_incident_state_service),
    extraction_service: ExtractionService = Depends(get_extraction_service),
    contradiction_engine: ContradictionEngine = Depends(get_contradiction_engine),
    gap_engine: GapEngine = Depends(get_gap_engine),
):
    try:
        incident = state_service.get(incident_id)
    except IncidentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    speaker_role = None
    if req.speaker_id and req.speaker_id in incident.participants:
        speaker_role = incident.participants[req.speaker_id].role

    recent_claims = [
        RecentClaimContext(id=c.id, type=c.type, status=c.status, normalized_claim=c.normalized_claim)
        for c in list(incident.claims.values())[-RECENT_CLAIMS_WINDOW:]
    ]
    recent_actions = [
        RecentActionContext(id=a.id, description=a.description, owner=a.owner, status=a.status.value)
        for a in incident.actions.values()
        if a.status.value in OPEN_ACTION_STATUSES
    ]

    context = ExtractionContext(
        incident_title=incident.title,
        speaker_id=req.speaker_id,
        speaker_name=req.speaker_name,
        speaker_role=speaker_role,
        utterance_text=req.text,
        recent_claims=recent_claims,
        recent_actions=recent_actions,
    )

    extraction = extraction_service.extract(context)
    return apply_extraction(
        state_service, incident_id, context, extraction, contradiction_engine, gap_engine
    )
