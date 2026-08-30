"""Process-wide IncidentStateService singleton, exposed as a FastAPI
dependency so tests can override it (app.dependency_overrides) with a
service backed by a fresh repository per test.
"""

from __future__ import annotations

from app.repositories.incident_repository import InMemoryIncidentRepository
from app.services.incident_state.service import IncidentStateService

_repository = InMemoryIncidentRepository()
_service = IncidentStateService(_repository)


def get_incident_state_service() -> IncidentStateService:
    return _service
