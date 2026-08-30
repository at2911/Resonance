from __future__ import annotations

from typing import Optional

from pydantic import BaseModel


class AddUtteranceRequest(BaseModel):
    speaker_id: Optional[str] = None
    speaker_name: str
    text: str
