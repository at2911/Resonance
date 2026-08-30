"""Process-wide AgoraRepository singleton, mirroring
incident_state/dependency.py's pattern so tests can override it the same
way (app.dependency_overrides).
"""

from __future__ import annotations

from app.repositories.agora_repository import AgoraRepository

_repository = AgoraRepository()


def get_agora_repository() -> AgoraRepository:
    return _repository
