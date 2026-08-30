"""Agora event processing pipeline (docs/AGORA_INTEGRATION.md, spec
"Event Processing" section):

Agora event -> normalize -> persist raw -> deduplicate -> [skip if
agent's own speech] -> identity resolve -> extract -> apply to state.

This does not reimplement reasoning: extraction/contradiction/gap
processing is the exact same `apply_extraction` call the manual
POST /utterances endpoint makes, via the shared
`build_extraction_context` helper. Agora is only responsible for getting
a NormalizedConversationEvent and a resolved speaker into that call.
"""

from __future__ import annotations

import logging

from app.repositories.agora_repository import AgoraRepository
from app.services.agora.identity import AGENT_ROLE_LABEL, resolve_participant
from app.services.agora.schemas import NormalizedConversationEvent, StoredConversationEvent
from app.services.contradiction.service import ContradictionEngine
from app.services.extraction.context import build_extraction_context
from app.services.extraction.pipeline import ExtractionApplyResult, apply_extraction
from app.services.extraction.service import ExtractionService
from app.services.incident_state.service import IncidentStateService
from app.services.information_gaps.service import GapEngine

logger = logging.getLogger("agora")


class AgoraProcessingResult(ExtractionApplyResult):
    duplicate: bool = False
    skipped_agent_speech: bool = False


def process_normalized_event(
    event: NormalizedConversationEvent,
    agora_repo: AgoraRepository,
    state_service: IncidentStateService,
    extraction_service: ExtractionService,
    contradiction_engine: ContradictionEngine | None,
    gap_engine: GapEngine | None,
    agora_uid: str | None = None,
    speaker_name_hint: str | None = None,
) -> AgoraProcessingResult:
    if agora_repo.has_event(event.incident_id, event.event_id):
        logger.info(
            "agora_event_duplicate_skipped",
            extra={"incident_id": event.incident_id, "event_id": event.event_id},
        )
        return AgoraProcessingResult(duplicate=True)

    is_agent_speech = event.metadata.get("role") == AGENT_ROLE_LABEL

    # Resolve identity before persisting so the stored raw event carries a
    # real speaker_id whenever we have enough information to determine one
    # (skipped for the agent's own speech — it isn't a human participant).
    speaker_id = event.speaker_id
    speaker_name = event.speaker_name
    if not is_agent_speech and agora_uid:
        participant = resolve_participant(state_service, event.incident_id, agora_uid, speaker_name_hint)
        speaker_id = participant.id
        speaker_name = participant.name
        event = event.model_copy(update={"speaker_id": speaker_id, "speaker_name": speaker_name})

    if is_agent_speech:
        agora_repo.save_event(
            event.incident_id, StoredConversationEvent(event=event, processing_status="skipped_empty")
        )
        return AgoraProcessingResult(skipped_agent_speech=True)

    if not event.text.strip():
        agora_repo.save_event(
            event.incident_id, StoredConversationEvent(event=event, processing_status="skipped_empty")
        )
        return AgoraProcessingResult()

    incident = state_service.get(event.incident_id)
    context = build_extraction_context(incident, speaker_id, speaker_name or "Unknown speaker", event.text)
    extraction = extraction_service.extract(context)
    result = apply_extraction(
        state_service, event.incident_id, context, extraction, contradiction_engine, gap_engine
    )

    # "processed" means extraction ran to completion for this utterance —
    # it does not imply any claim was produced. ExtractionService already
    # degrades to an empty result on repeated LLM failure (see its own
    # retry/degrade logic) rather than raising, so there is no separate
    # failure signal to surface here; the raw event is preserved either
    # way, satisfying "never lose the utterance even if extraction fails."
    agora_repo.save_event(
        event.incident_id, StoredConversationEvent(event=event, processing_status="processed")
    )

    return AgoraProcessingResult(**result.model_dump())
