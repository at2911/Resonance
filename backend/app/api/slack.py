"""Slack proposal + execution endpoints.

Approval itself is generic (POST /incidents/{id}/external-actions/{id}/decision
in app/api/incidents.py) — this module only adds the two Slack-specific
pieces: composing the proposed message from real state, and actually
calling Slack once approved. Execution never trusts the client to have
verified approval; mark_external_action_executing re-checks it server-side
and is the only thing that can unlock a Slack call.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException

from app.config import get_settings
from app.models.enums import ExternalActionType
from app.models.incident import ExternalAction
from app.repositories.incident_repository import IncidentNotFoundError
from app.services.incident_state.dependency import get_incident_state_service
from app.services.incident_state.service import IncidentStateService, InvalidStateTransitionError
from app.services.slack.client import SlackCallError, SlackClient, SlackWebClient
from app.services.slack.composer import SlackMessageComposer

router = APIRouter(prefix="/incidents", tags=["slack"])


def get_slack_client() -> SlackClient:
    settings = get_settings()
    try:
        return SlackWebClient(settings.slack_bot_token)
    except SlackCallError as e:
        raise HTTPException(status_code=503, detail=f"Slack unavailable: {e}") from e


@router.post("/{incident_id}/slack-updates", response_model=ExternalAction)
def propose_slack_update(
    incident_id: str,
    state_service: IncidentStateService = Depends(get_incident_state_service),
):
    settings = get_settings()
    if not settings.slack_channel_id:
        raise HTTPException(status_code=503, detail="Slack unavailable: SLACK_CHANNEL_ID is not configured")

    try:
        incident = state_service.get(incident_id)
    except IncidentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    text = SlackMessageComposer.compose(incident)
    return state_service.propose_external_action(
        incident_id,
        ExternalActionType.SLACK_MESSAGE,
        {"channel": settings.slack_channel_id, "text": text},
    )


@router.post("/{incident_id}/external-actions/{external_action_id}/execute", response_model=ExternalAction)
def execute_external_action(
    incident_id: str,
    external_action_id: str,
    state_service: IncidentStateService = Depends(get_incident_state_service),
    slack_client: SlackClient = Depends(get_slack_client),
):
    try:
        incident = state_service.get(incident_id)
    except IncidentNotFoundError as e:
        raise HTTPException(status_code=404, detail=str(e)) from e

    ea = incident.external_actions.get(external_action_id)
    if ea is None:
        raise HTTPException(status_code=404, detail=f"External action not found: {external_action_id}")
    if ea.action_type != ExternalActionType.SLACK_MESSAGE:
        raise HTTPException(status_code=400, detail=f"Unsupported external action type: {ea.action_type.value}")

    try:
        executing = state_service.mark_external_action_executing(incident_id, external_action_id)
    except InvalidStateTransitionError as e:
        raise HTTPException(status_code=409, detail=str(e)) from e

    try:
        response = slack_client.post_message(
            channel=executing.payload["channel"], text=executing.payload["text"]
        )
    except SlackCallError as e:
        # Never claim success: record the failure and let the caller retry
        # (mark_external_action_executing allows FAILED -> EXECUTING again).
        return state_service.mark_external_action_result(
            incident_id, external_action_id, succeeded=False, execution_result=str(e)
        )

    return state_service.mark_external_action_result(
        incident_id,
        external_action_id,
        succeeded=True,
        execution_result=f"Posted to Slack channel {response['channel']} (ts={response['ts']})",
    )
