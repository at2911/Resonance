"""Builds an ExtractionContext from current incident state. Shared by every
utterance source (the manual POST /utterances endpoint and the Agora
pipeline) so there is exactly one place that decides what "recent claims"
and "open actions" context the LLM sees — no source-specific reasoning
logic, per the architecture rule that Agora is just another way an
utterance arrives, not a different reasoning path.
"""

from __future__ import annotations

from app.models.incident import Incident
from app.services.extraction.schemas import (
    ExtractionContext,
    RecentActionContext,
    RecentClaimContext,
)

RECENT_CLAIMS_WINDOW = 10
OPEN_ACTION_STATUSES = ("OPEN", "IN_PROGRESS", "BLOCKED")


def build_extraction_context(
    incident: Incident,
    speaker_id: str | None,
    speaker_name: str,
    text: str,
) -> ExtractionContext:
    speaker_role = None
    if speaker_id and speaker_id in incident.participants:
        speaker_role = incident.participants[speaker_id].role

    recent_claims = [
        RecentClaimContext(id=c.id, type=c.type, status=c.status, normalized_claim=c.normalized_claim)
        for c in list(incident.claims.values())[-RECENT_CLAIMS_WINDOW:]
    ]
    recent_actions = [
        RecentActionContext(id=a.id, description=a.description, owner=a.owner, status=a.status.value)
        for a in incident.actions.values()
        if a.status.value in OPEN_ACTION_STATUSES
    ]

    return ExtractionContext(
        incident_title=incident.title,
        speaker_id=speaker_id,
        speaker_name=speaker_name,
        speaker_role=speaker_role,
        utterance_text=text,
        recent_claims=recent_claims,
        recent_actions=recent_actions,
    )
