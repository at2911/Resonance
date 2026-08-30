from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class DemoStatus(BaseModel):
    status: str
    """IDLE | PLAYING | PAUSED | COMPLETED"""
    incident_id: Optional[str] = None
    current_step: int
    total_steps: int
    last_step_description: Optional[str] = None
