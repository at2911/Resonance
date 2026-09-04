"""Agora-facing schemas: webhook envelope/payload shapes, the boundary
NormalizedConversationEvent (spec §-required shape — see project
architecture doc), session records, and the live-relay ingestion request.

Nothing outside app/services/agora ever sees an Agora-specific payload
shape directly — every other layer (extraction, contradiction, gaps,
state engine) only ever receives a NormalizedConversationEvent or, after
identity resolution, a plain ExtractionContext exactly as it already did
for manually-posted utterances.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Literal, Optional

from pydantic import BaseModel, Field

from app.models.enums import AgoraSessionStatus
from app.models.incident import new_id


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------------
# Normalized event — the only shape the rest of the app ever sees
# ---------------------------------------------------------------------


class NormalizedConversationEvent(BaseModel):
    event_id: str
    incident_id: str
    speaker_id: Optional[str] = None
    speaker_name: Optional[str] = None
    timestamp: datetime
    text: str
    source: Literal["agora"] = "agora"
    metadata: dict = Field(default_factory=dict)


class StoredConversationEvent(BaseModel):
    """Persisted record — what actually backs evidence provenance and
    dedup, regardless of whether extraction succeeded.
    """

    event: NormalizedConversationEvent
    received_at: datetime = Field(default_factory=utcnow)
    processing_status: Literal["processed", "extraction_degraded", "skipped_empty"] = "processed"


# ---------------------------------------------------------------------
# Webhook envelope + per-event payloads (docs/AGORA_INTEGRATION.md §4)
# ---------------------------------------------------------------------


class WebhookEnvelope(BaseModel):
    noticeId: str
    productId: int
    eventType: int
    notifyMs: int
    payload: dict


class AgentHistoryContent(BaseModel):
    role: Literal["user", "assistant"]
    content: str
    speech_start_ms: Optional[int] = None
    speech_end_ms: Optional[int] = None
    speech_algorithmic_delay: Optional[int] = None


class AgentHistoryPayload(BaseModel):
    agent_id: str
    name: Optional[str] = None
    channel: str
    start_ts: Optional[int] = None
    stop_ts: Optional[int] = None
    contents: list[AgentHistoryContent] = Field(default_factory=list)
    labels: Optional[dict] = None


class AgentJoinedPayload(BaseModel):
    agent_id: str
    name: Optional[str] = None
    start_ts: Optional[int] = None
    channel: str
    labels: Optional[dict] = None


class AgentLeftPayload(BaseModel):
    agent_id: str
    name: Optional[str] = None
    start_ts: Optional[int] = None
    stop_ts: Optional[int] = None
    channel: str
    status: Optional[str] = None
    message: Optional[str] = None
    labels: Optional[dict] = None


class AgentErrorDetail(BaseModel):
    module: str
    turn_id: Optional[int] = None
    code: Optional[int] = None
    message: Optional[str] = None


class AgentErrorPayload(BaseModel):
    agent_id: str
    name: Optional[str] = None
    channel: str
    turn_id: Optional[str] = None
    errors: list[AgentErrorDetail] = Field(default_factory=list)
    labels: Optional[dict] = None


# ---------------------------------------------------------------------
# Live-relay ingestion (docs/AGORA_INTEGRATION.md §5, "live path")
# ---------------------------------------------------------------------


class TranscriptSegmentIngestRequest(BaseModel):
    """What a client-side relay (holding the RTM transcript subscription)
    posts per finalized utterance. `event_id` is the relay's idempotency
    key — it must generate one per utterance, not per network attempt, so
    a retried POST is recognized as a duplicate rather than double-counted.
    """

    event_id: str
    agora_uid: str
    speaker_name: Optional[str] = None
    text: str
    timestamp: Optional[datetime] = None


# ---------------------------------------------------------------------
# Session
# ---------------------------------------------------------------------


class AgoraSession(BaseModel):
    id: str = Field(default_factory=new_id)
    incident_id: str
    channel: str
    agent_uid: int
    agent_id: Optional[str] = None
    status: AgoraSessionStatus = AgoraSessionStatus.STARTING
    created_at: datetime = Field(default_factory=utcnow)
    ended_at: Optional[datetime] = None


class StartSessionRequest(BaseModel):
    channel: Optional[str] = None
    """Defaults to a channel name derived from the incident id if omitted."""
    agent_uid: int = 0
    asr: Optional[dict] = None
    llm: Optional[dict] = None
    tts: Optional[dict] = None
    extra_properties: dict = Field(default_factory=dict)
    """Passed through into `properties` on the /join call verbatim — this
    integration does not choose ASR/LLM/TTS vendors on the caller's
    behalf (docs/AGORA_INTEGRATION.md §9)."""


class StartSessionResponse(BaseModel):
    session: AgoraSession
    rtc_token: str
    """Token for a human participant client to join the same channel."""


class SpeakSummaryResponse(BaseModel):
    spoken_text: str
    """The exact text sent to Agora's /speak endpoint — the same
    deterministic SlackMessageComposer output a human would see in the
    Slack approval modal, so what the agent is asked to say is always
    visible and never invented separately from that single source."""
