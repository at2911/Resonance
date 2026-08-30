"""Process-wide DemoService singleton, same pattern as
incident_state/dependency.py — wraps the same IncidentStateService
singleton the rest of the app uses (not a separate one), so a demo
incident is a completely ordinary incident to every other endpoint.
"""

from __future__ import annotations

from app.services.demo.service import DemoService
from app.services.incident_state.dependency import get_incident_state_service

_service = DemoService(get_incident_state_service())


def get_demo_service() -> DemoService:
    return _service
