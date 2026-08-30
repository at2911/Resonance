"""AgoraAdapter: the only place Agora-specific payload shapes get turned
into NormalizedConversationEvent. Nothing downstream of this module knows
Agora's field names.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from app.services.agora.schemas import (
    AgentHistoryContent,
    AgentHistoryPayload,
    NormalizedConversationEvent,
    TranscriptSegmentIngestRequest,
)


def _synthesize_history_event_id(agent_id: str, index: int, entry: AgentHistoryContent) -> str:
    """Deterministic so a redelivered/overlapping `agent history` payload
    produces the same event_id for the same logical utterance, making
    dedup (AgoraRepository.has_event) actually work across redeliveries —
    a random id per parse would defeat that entirely.
    """
    key = f"{agent_id}:{index}:{entry.role}:{entry.content}:{entry.speech_start_ms}"
    return "hist-" + hashlib.sha256(key.encode()).hexdigest()[:24]


class AgoraAdapter:
    @staticmethod
    def normalize_history_entry(
        incident_id: str,
        payload: AgentHistoryPayload,
        index: int,
        speaker_id: str | None,
        speaker_name: str | None,
    ) -> NormalizedConversationEvent:
        entry = payload.contents[index]
        timestamp = (
            datetime.fromtimestamp(entry.speech_start_ms / 1000, tz=timezone.utc)
            if entry.speech_start_ms
            else datetime.now(timezone.utc)
        )
        return NormalizedConversationEvent(
            event_id=_synthesize_history_event_id(payload.agent_id, index, entry),
            incident_id=incident_id,
            speaker_id=speaker_id,
            speaker_name=speaker_name,
            timestamp=timestamp,
            text=entry.content,
            source="agora",
            metadata={
                "agent_id": payload.agent_id,
                "channel": payload.channel,
                "role": entry.role,
                "speech_start_ms": entry.speech_start_ms,
                "speech_end_ms": entry.speech_end_ms,
                "delivery": "webhook_agent_history",
            },
        )

    @staticmethod
    def normalize_live_segment(
        incident_id: str,
        req: TranscriptSegmentIngestRequest,
        speaker_id: str | None,
    ) -> NormalizedConversationEvent:
        return NormalizedConversationEvent(
            event_id=req.event_id,
            incident_id=incident_id,
            speaker_id=speaker_id,
            speaker_name=req.speaker_name,
            timestamp=req.timestamp or datetime.now(timezone.utc),
            text=req.text,
            source="agora",
            metadata={
                "agora_uid": req.agora_uid,
                "role": "user",
                "delivery": "live_relay",
            },
        )
