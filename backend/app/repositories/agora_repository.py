"""Persistence for Agora sessions and raw conversation events.

Separate from IncidentRepository deliberately: sessions and raw events are
Agora-integration bookkeeping (session-to-incident association, webhook
dedup, evidence provenance), not part of the canonical IncidentState the
rest of the app reasons over. Same in-memory-with-a-lock pattern as
IncidentRepository for the same reasons (MVP-scale, deterministic demo).
"""

from __future__ import annotations

import threading
from typing import Optional

from app.services.agora.schemas import AgoraSession, StoredConversationEvent


class AgoraSessionNotFoundError(Exception):
    def __init__(self, session_id: str):
        super().__init__(f"Agora session not found: {session_id}")


class AgoraRepository:
    def __init__(self) -> None:
        self._lock = threading.RLock()
        self._sessions: dict[str, AgoraSession] = {}
        self._sessions_by_channel: dict[str, str] = {}
        self._sessions_by_agent_id: dict[str, str] = {}
        # incident_id -> event_id -> StoredConversationEvent
        self._events: dict[str, dict[str, StoredConversationEvent]] = {}
        self._seen_webhook_notice_ids: set[str] = set()

    # -- sessions ------------------------------------------------------

    def save_session(self, session: AgoraSession) -> AgoraSession:
        with self._lock:
            self._sessions[session.id] = session
            self._sessions_by_channel[session.channel] = session.id
            if session.agent_id:
                self._sessions_by_agent_id[session.agent_id] = session.id
            return session

    def get_session(self, session_id: str) -> AgoraSession:
        with self._lock:
            session = self._sessions.get(session_id)
            if session is None:
                raise AgoraSessionNotFoundError(session_id)
            return session

    def find_incident_id_by_channel(self, channel: str) -> Optional[str]:
        with self._lock:
            session_id = self._sessions_by_channel.get(channel)
            return self._sessions[session_id].incident_id if session_id else None

    def find_incident_id_by_agent_id(self, agent_id: str) -> Optional[str]:
        with self._lock:
            session_id = self._sessions_by_agent_id.get(agent_id)
            return self._sessions[session_id].incident_id if session_id else None

    # -- raw conversation events (dedup + provenance) -------------------

    def has_event(self, incident_id: str, event_id: str) -> bool:
        with self._lock:
            return event_id in self._events.get(incident_id, {})

    def save_event(self, incident_id: str, record: StoredConversationEvent) -> StoredConversationEvent:
        with self._lock:
            self._events.setdefault(incident_id, {})[record.event.event_id] = record
            return record

    def list_events(self, incident_id: str) -> list[StoredConversationEvent]:
        with self._lock:
            return sorted(
                self._events.get(incident_id, {}).values(), key=lambda r: r.event.timestamp
            )

    # -- webhook envelope dedup ------------------------------------------

    def seen_webhook_notice(self, notice_id: str) -> bool:
        with self._lock:
            if notice_id in self._seen_webhook_notice_ids:
                return True
            self._seen_webhook_notice_ids.add(notice_id)
            return False
