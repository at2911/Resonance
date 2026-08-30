"""Agora uid -> Participant identity resolution (docs/AGORA_INTEGRATION.md §7).

An Agora `agora_uid` is never assumed to equal an application Participant
id. The first time a uid is seen for an incident, a new Participant is
created with role UNKNOWN / confidence 0.0 — uncertainty is represented
explicitly rather than guessed — and normal role recognition (the
extraction layer's speaker_role_hint, already built in a previous slice)
takes it from there exactly as it does for manually-posted utterances.
"""

from __future__ import annotations

from app.models.enums import ParticipantRole
from app.models.incident import Participant
from app.services.incident_state.service import IncidentStateService

# The AI agent's own uid speaks with role="assistant" in Agora's transcript
# format. It is identified as a participant for timeline/audit purposes but
# is never run through extraction (see pipeline.py) — treating the agent's
# own TTS output as new incident evidence would be circular.
AGENT_ROLE_LABEL = "assistant"


def resolve_participant(
    service: IncidentStateService, incident_id: str, agora_uid: str, speaker_name: str | None
) -> Participant:
    incident = service.get(incident_id)
    for participant in incident.participants.values():
        if participant.agora_uid == agora_uid:
            return participant

    name = speaker_name or f"Speaker {agora_uid}"
    participant = service.add_participant(incident_id, name, ParticipantRole.UNKNOWN, 0.0)
    # add_participant doesn't take agora_uid (it's also used for manual,
    # non-Agora participants) — set it directly via the same service so the
    # mutation still goes through the one place incident state changes.
    return service.set_participant_agora_uid(incident_id, participant.id, agora_uid)
