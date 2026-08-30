"""Orchestrates Agora session start/end — the incident/session
association required by the spec ("every Agora conversation must belong
to an incident"). This is the only place that calls the Agora REST client
and the token builder; the webhook/pipeline layers only ever look up an
already-created session's incident_id.
"""

from __future__ import annotations

from app.models.enums import AgoraSessionStatus, TimelineEventType
from app.repositories.agora_repository import AgoraRepository
from app.services.agora.rest_client import AgoraConversationalAIClient, AgoraRestError
from app.services.agora.schemas import AgoraSession, StartSessionRequest, StartSessionResponse, utcnow
from app.services.agora.token import TokenBuilder, TokenBuildError
from app.services.incident_state.service import IncidentStateService


def start_session(
    state_service: IncidentStateService,
    agora_repo: AgoraRepository,
    rest_client: AgoraConversationalAIClient,
    token_builder: TokenBuilder,
    incident_id: str,
    req: StartSessionRequest,
) -> StartSessionResponse:
    # Validates the incident exists before touching any external service.
    state_service.get(incident_id)

    channel = req.channel or f"incident-{incident_id[:16]}"
    session = AgoraSession(
        incident_id=incident_id, channel=channel, agent_uid=req.agent_uid, status=AgoraSessionStatus.STARTING
    )
    agora_repo.save_session(session)

    try:
        agent_token = token_builder.build_rtc_token(channel, req.agent_uid)
        human_token = token_builder.build_rtc_token(channel, 0)
    except TokenBuildError:
        session.status = AgoraSessionStatus.FAILED
        agora_repo.save_session(session)
        raise

    properties = {
        "channel": channel,
        "token": agent_token,
        "agent_rtc_uid": str(req.agent_uid),
        "remote_rtc_uids": ["*"],
        **({"asr": req.asr} if req.asr else {}),
        **({"llm": req.llm} if req.llm else {}),
        **({"tts": req.tts} if req.tts else {}),
        **req.extra_properties,
    }

    try:
        response = rest_client.join(name=f"agent-{session.id}", properties=properties)
    except AgoraRestError:
        session.status = AgoraSessionStatus.FAILED
        agora_repo.save_session(session)
        raise

    session.agent_id = response.get("agent_id")
    session.status = AgoraSessionStatus.ACTIVE
    agora_repo.save_session(session)

    state_service.add_timeline_note(
        incident_id,
        TimelineEventType.AGORA_SESSION_STARTED,
        f"Agora session started on channel '{channel}'"
        + (f" (agent_id={session.agent_id})" if session.agent_id else ""),
    )

    return StartSessionResponse(session=session, rtc_token=human_token)


def end_session(
    state_service: IncidentStateService,
    agora_repo: AgoraRepository,
    rest_client: AgoraConversationalAIClient,
    session_id: str,
) -> AgoraSession:
    session = agora_repo.get_session(session_id)

    if session.agent_id and session.status == AgoraSessionStatus.ACTIVE:
        rest_client.leave(session.agent_id)

    session.status = AgoraSessionStatus.ENDED
    session.ended_at = utcnow()
    agora_repo.save_session(session)

    state_service.add_timeline_note(
        session.incident_id,
        TimelineEventType.AGORA_SESSION_ENDED,
        f"Agora session ended on channel '{session.channel}'",
    )

    return session
