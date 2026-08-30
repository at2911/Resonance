"""Persistence boundary for IncidentState.

MVP uses an in-memory store: it is fast, fully deterministic for the demo,
and removes an entire class of infra failure from the critical path of a
timed hackathon demo. The interface is kept narrow and swappable so a
DATABASE_URL-backed implementation can be dropped in later (P2) without any
service-layer changes — services depend only on IncidentRepository, never on
storage details.
"""

from __future__ import annotations

import threading
from typing import Protocol

from app.models.incident import Incident


class IncidentNotFoundError(Exception):
    def __init__(self, incident_id: str):
        super().__init__(f"Incident not found: {incident_id}")
        self.incident_id = incident_id


class IncidentRepository(Protocol):
    def create(self, incident: Incident) -> Incident: ...

    def get(self, incident_id: str) -> Incident: ...

    def save(self, incident: Incident) -> Incident: ...

    def list_all(self) -> list[Incident]: ...

    def delete(self, incident_id: str) -> None: ...


class InMemoryIncidentRepository:
    """Thread-safe in-memory repository.

    A single process-wide lock is sufficient at hackathon scale (one
    incident room, single backend process) and keeps state transitions
    trivially serializable, which matters more than throughput here.
    """

    def __init__(self) -> None:
        self._store: dict[str, Incident] = {}
        self._lock = threading.RLock()

    def create(self, incident: Incident) -> Incident:
        with self._lock:
            if incident.id in self._store:
                raise ValueError(f"Incident already exists: {incident.id}")
            self._store[incident.id] = incident
            return incident

    def get(self, incident_id: str) -> Incident:
        with self._lock:
            incident = self._store.get(incident_id)
            if incident is None:
                raise IncidentNotFoundError(incident_id)
            return incident

    def save(self, incident: Incident) -> Incident:
        with self._lock:
            self._store[incident.id] = incident
            return incident

    def list_all(self) -> list[Incident]:
        with self._lock:
            return list(self._store.values())

    def delete(self, incident_id: str) -> None:
        with self._lock:
            self._store.pop(incident_id, None)

    def lock(self) -> threading.RLock:
        return self._lock
