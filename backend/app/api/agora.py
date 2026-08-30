"""Agora session management, live transcript relay ingestion, and the
Agora webhook receiver.

The webhook route is deliberately NOT incident-scoped
(`POST /agora/webhook`, not `POST /incidents/{id}/agora/webhook`) — Agora's
Console configures one callback URL per project, it does not support a
dynamic per-incident path. Incident association instead comes from the
session-to-incident mapping recorded when the session was started
(AgoraRepository, keyed by channel/agent_id) — see
docs/AGORA_INTEGRATION.md §5-6 for why this is the correct shape rather
than trying to force incident_id into a URL Agora itself controls.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request

from app.api.conversation import get_contradiction_engine, get_extraction_service, get_gap_engine
from app.config import get_settings
from app.models.enums import TimelineEventType
from app.repositories.agora_repository import AgoraRepository, AgoraSessionNotFoundError
from app.repositories.incident_repository import IncidentNotFoundError
from app.services.agora.adapter import AgoraAdapter
from app.services.agora.dependency import get_agora_repository
from app.services.agora.pipeline import AgoraProcessingResult, process_normalized_event
from app.services.agora.rest_client import (
    AgoraConversationalAIClient,
    AgoraRestError,
    HttpxAgoraConversationalAIClient,
)
from app.services.agora.schemas import (
    AgentErrorPayload,
    AgentHistoryPayload,
    AgentJoinedPayload,
    AgentLeftPayload,
    AgoraSession,
    StartSessionRequest,
    StartSessionResponse,
    StoredConversationEvent,
    TranscriptSegmentIngestRequest,
)
from app.services.agora.session_service import end_session, start_session
from app.services.agora.token import AgoraTokenBuilder, TokenBuildError, TokenBuilder
from app.services.agora.webhook import WebhookVerificationError, parse_envelope, verify_signature
from app.services.contradiction.llm_client import LLMCallError as ContradictionLLMCallError
from app.services.contradiction.service import ContradictionEngine
from app.services.extraction.llm_client import LLMCallError as ExtractionLLMCallError
from app.services.extraction.service import ExtractionService
from app.services.incident_state.dependency import get_incident_state_service
from app.services.incident_state.service import IncidentStateService
from app.services.information_gaps.llm_client import LLMCallError as GapLLMCallError
from app.services.information_gaps.service import GapEngine
from app.services.llm_factory import (
    UnsupportedProviderError,
    build_contradiction_client,
    build_extraction_client,
    build_gap_assessment_client,
)

logger = logging.getLogger("agora")

router = APIRouter(tags=["agora"])


# These "optional" variants never raise on missing config — they return
# None instead. Used only by the webhook route: unlike every other Agora
# endpoint, the webhook must run signature verification (inside the route
# body) before anything else, and FastAPI resolves every `Depends()`
# parameter before the body executes regardless of where it's referenced
# in code. A getter that raises HTTPException(503) here would short-circuit
# the response before verify_signature ever ran, turning a forged/unsigned
# request into a 503 that leaks our LLM config state instead of a 401 —
# this was a real bug caught by this slice's own HTTP smoke test. Catching
# UnsupportedProviderError here too (not just *LLMCallError) matters for
# the exact same reason: a misconfigured LLM_PROVIDER must degrade the same
# way an unconfigured key does, not raise past this point.
def get_optional_extraction_service() -> Optional[ExtractionService]:
    settings = get_settings()
    try:
        return ExtractionService(build_extraction_client(settings))
    except (ExtractionLLMCallError, UnsupportedProviderError):
        return None


def get_optional_contradiction_engine() -> Optional[ContradictionEngine]:
    settings = get_settings()
    try:
        return ContradictionEngine(build_contradiction_client(settings))
    except (ContradictionLLMCallError, UnsupportedProviderError):
        return None


def get_optional_gap_engine() -> Optional[GapEngine]:
    settings = get_settings()
    try:
        return GapEngine(build_gap_assessment_client(settings))
    except (GapLLMCallError, UnsupportedProviderError):
        return None


def get_rest_client() -> AgoraConversationalAIClient:
    settings = get_settings()
    try:
        return HttpxAgoraConversationalAIClient(
            settings.agora_app_id,
            settings.agora_customer_key,
            settings.agora_customer_secret,
            settings.agora_rest_base_url,
        )
    except AgoraRestError as e:
        raise HTTPException(status_code=503, detail=f"Agora unavailable: {e}") from e


def get_token_builder() -> TokenBuilder:
    settings = get_settings()
    try:
        return AgoraTokenBuilder(settings.agora_app_id, settings.agora_app_certificate)
    except TokenBuildError as e:
        raise HTTPException(status_code=503, detail=f"Agora unavailable: {e}") from e


# ---------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------


@router.post("/incidents/{incident_id}/agora/session", response_model=StartSessionResponse)
def create_session(
    incident_id: str,
    req: StartSessionRequest,
    state_service: IncidentStateService = Depends(get_incident_state_service),
    agora_repo: AgoraRepository = Depends(get_agora_repository),
    rest_client: AgoraConversationalAIClient = Depends(get_rest_client),
    token_builder: TokenBuilder = Depends(get_token_builder),
):
    try:
        return start_session(state_service, agora_repo, rest_client, token_builder, incident_id, req)
    except IncidentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except (AgoraRestError, TokenBuildError) as e:
        raise HTTPException(status_code=502, detail=f"Failed to start Agora session: {e}") from e


@router.post("/incidents/{incident_id}/agora/session/{session_id}/end", response_model=AgoraSession)
def stop_session(
    incident_id: str,
    session_id: str,
    state_service: IncidentStateService = Depends(get_incident_state_service),
    agora_repo: AgoraRepository = Depends(get_agora_repository),
    rest_client: AgoraConversationalAIClient = Depends(get_rest_client),
):
    try:
        session = end_session(state_service, agora_repo, rest_client, session_id)
    except AgoraSessionNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e
    except AgoraRestError as e:
        raise HTTPException(status_code=502, detail=f"Failed to end Agora session: {e}") from e

    if session.incident_id != incident_id:
        raise HTTPException(status_code=404, detail="Session does not belong to this incident")
    return session


# ---------------------------------------------------------------------
# Live transcript relay ingestion (docs/AGORA_INTEGRATION.md §5, path 1)
# ---------------------------------------------------------------------


@router.post("/incidents/{incident_id}/agora/transcript-events", response_model=AgoraProcessingResult)
def ingest_transcript_event(
    incident_id: str,
    req: TranscriptSegmentIngestRequest,
    state_service: IncidentStateService = Depends(get_incident_state_service),
    agora_repo: AgoraRepository = Depends(get_agora_repository),
    extraction_service: ExtractionService = Depends(get_extraction_service),
    contradiction_engine: ContradictionEngine = Depends(get_contradiction_engine),
    gap_engine: GapEngine = Depends(get_gap_engine),
):
    try:
        state_service.get(incident_id)
    except IncidentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    event = AgoraAdapter.normalize_live_segment(incident_id, req, speaker_id=None)
    return process_normalized_event(
        event,
        agora_repo,
        state_service,
        extraction_service,
        contradiction_engine,
        gap_engine,
        agora_uid=req.agora_uid,
        speaker_name_hint=req.speaker_name,
    )


# ---------------------------------------------------------------------
# Webhook receiver (docs/AGORA_INTEGRATION.md §4/§6) — NOT incident-scoped
# ---------------------------------------------------------------------


def _resolve_incident_id(agora_repo: AgoraRepository, agent_id: str | None, channel: str | None) -> str | None:
    if agent_id:
        found = agora_repo.find_incident_id_by_agent_id(agent_id)
        if found:
            return found
    if channel:
        return agora_repo.find_incident_id_by_channel(channel)
    return None


@router.post("/agora/webhook")
async def agora_webhook(
    request: Request,
    state_service: IncidentStateService = Depends(get_incident_state_service),
    agora_repo: AgoraRepository = Depends(get_agora_repository),
    extraction_service: Optional[ExtractionService] = Depends(get_optional_extraction_service),
    contradiction_engine: Optional[ContradictionEngine] = Depends(get_optional_contradiction_engine),
    gap_engine: Optional[GapEngine] = Depends(get_optional_gap_engine),
):
    """Uses the `get_optional_*` dependency variants (never raise on
    missing config, return None instead) rather than the ones the other
    Agora/conversation routes use — see the comment above those functions
    for why: the non-optional getters would let an "LLM not configured"
    503 short-circuit this handler before verify_signature below ever
    runs, since FastAPI resolves all `Depends()` params before the body
    executes regardless of code order.
    """
    settings = get_settings()
    raw_body = await request.body()

    try:
        verify_signature(
            settings.agora_webhook_secret,
            raw_body,
            request.headers.get("Agora-Signature-V2"),
            request.headers.get("Agora-Signature"),
        )
    except WebhookVerificationError as e:
        raise HTTPException(status_code=401, detail=str(e)) from e

    try:
        envelope = parse_envelope(raw_body)
    except WebhookVerificationError as e:
        raise HTTPException(status_code=400, detail=str(e)) from e

    if agora_repo.seen_webhook_notice(envelope.noticeId):
        return {"status": "duplicate_ignored"}

    try:
        return _dispatch_webhook_event(
            envelope, state_service, agora_repo, extraction_service, contradiction_engine, gap_engine
        )
    except HTTPException:
        raise
    except Exception:
        # A malformed/unexpected payload for a known event type must never
        # crash the endpoint or corrupt incident state — log and 200 so
        # Agora doesn't retry something that will never succeed.
        logger.exception("agora_webhook_processing_failed", extra={"notice_id": envelope.noticeId})
        return {"status": "processing_error_logged"}


def _dispatch_webhook_event(
    envelope,
    state_service: IncidentStateService,
    agora_repo: AgoraRepository,
    extraction_service: Optional[ExtractionService],
    contradiction_engine: Optional[ContradictionEngine],
    gap_engine: Optional[GapEngine],
) -> dict:
    event_type = envelope.eventType

    if event_type == 101:
        payload = AgentJoinedPayload.model_validate(envelope.payload)
        incident_id = _resolve_incident_id(agora_repo, payload.agent_id, payload.channel)
        if not incident_id:
            logger.warning("agora_webhook_unassociated", extra={"event_type": 101, "agent_id": payload.agent_id})
            return {"status": "ignored_unassociated"}
        state_service.add_timeline_note(
            incident_id, TimelineEventType.AGORA_AGENT_JOINED, f"Agora agent joined channel '{payload.channel}'"
        )
        return {"status": "ok"}

    if event_type == 102:
        payload = AgentLeftPayload.model_validate(envelope.payload)
        incident_id = _resolve_incident_id(agora_repo, payload.agent_id, payload.channel)
        if not incident_id:
            logger.warning("agora_webhook_unassociated", extra={"event_type": 102, "agent_id": payload.agent_id})
            return {"status": "ignored_unassociated"}
        state_service.add_timeline_note(
            incident_id,
            TimelineEventType.AGORA_AGENT_LEFT,
            f"Agora agent left channel '{payload.channel}'" + (f": {payload.message}" if payload.message else ""),
        )
        return {"status": "ok"}

    if event_type == 103:
        payload = AgentHistoryPayload.model_validate(envelope.payload)
        incident_id = _resolve_incident_id(agora_repo, payload.agent_id, payload.channel)
        if not incident_id:
            logger.warning("agora_webhook_unassociated", extra={"event_type": 103, "agent_id": payload.agent_id})
            return {"status": "ignored_unassociated"}
        return _process_agent_history(
            payload, incident_id, state_service, agora_repo, extraction_service, contradiction_engine, gap_engine
        )

    if event_type == 110:
        payload = AgentErrorPayload.model_validate(envelope.payload)
        incident_id = _resolve_incident_id(agora_repo, payload.agent_id, payload.channel)
        if not incident_id:
            logger.warning("agora_webhook_unassociated", extra={"event_type": 110, "agent_id": payload.agent_id})
            return {"status": "ignored_unassociated"}
        messages = "; ".join(f"{e.module}: {e.message}" for e in payload.errors) or "unspecified error"
        state_service.add_timeline_note(incident_id, TimelineEventType.AGORA_AGENT_ERROR, f"Agora agent error: {messages}")
        return {"status": "ok"}

    # 104/111/112/201/202: accepted but not incident-reasoning-relevant.
    return {"status": "ignored_event_type"}


def _process_agent_history(
    payload: AgentHistoryPayload,
    incident_id: str,
    state_service: IncidentStateService,
    agora_repo: AgoraRepository,
    extraction_service: Optional[ExtractionService],
    contradiction_engine: Optional[ContradictionEngine],
    gap_engine: Optional[GapEngine],
) -> dict:
    if extraction_service is None:
        # LLM not configured: still preserve every raw event (never lose
        # transcript history over a config problem), just skip reasoning.
        # Returning 200 here is deliberate — Agora's at-least-once webhook
        # delivery would otherwise retry something that can never succeed
        # until someone fixes the config, which isn't a per-event problem.
        for index in range(len(payload.contents)):
            event = AgoraAdapter.normalize_history_entry(incident_id, payload, index, None, None)
            if not agora_repo.has_event(incident_id, event.event_id):
                agora_repo.save_event(
                    incident_id, StoredConversationEvent(event=event, processing_status="extraction_degraded")
                )
        logger.warning("agora_webhook_history_extraction_unavailable", extra={"incident_id": incident_id})
        return {"status": "extraction_unavailable_raw_events_preserved", "entries_total": len(payload.contents)}

    # Webhook `agent history` only distinguishes role user/assistant, not
    # individual human speakers (docs/AGORA_INTEGRATION.md §7) — every
    # "user" line in one history payload maps to the same synthesized
    # per-session identity unless the live-relay path already attributed
    # it to a real participant.
    synthetic_uid = f"agent-history:{payload.agent_id}:user"
    processed = 0
    for index, entry in enumerate(payload.contents):
        event = AgoraAdapter.normalize_history_entry(
            incident_id, payload, index, speaker_id=None, speaker_name=None
        )
        result = process_normalized_event(
            event,
            agora_repo,
            state_service,
            extraction_service,
            contradiction_engine,
            gap_engine,
            agora_uid=synthetic_uid if entry.role == "user" else None,
            speaker_name_hint=None,
        )
        if not result.duplicate:
            processed += 1
    return {"status": "ok", "entries_processed": processed, "entries_total": len(payload.contents)}
