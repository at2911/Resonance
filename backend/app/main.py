"""FastAPI application entrypoint.

Only the Incident State Engine is wired up in this slice. Extraction,
contradiction, gap, approval, Slack, and Agora routers are added in later
slices per the priority order in the project plan.
"""

import logging

from fastapi import FastAPI

from app.api.conversation import router as conversation_router
from app.api.incidents import router as incidents_router
from app.config import get_settings

logging.basicConfig(level=get_settings().log_level)

app = FastAPI(title="Dangling Pointers — Incident Commander", version="0.1.0")
app.include_router(incidents_router)
app.include_router(conversation_router)


@app.get("/health")
def health():
    return {"status": "ok"}
