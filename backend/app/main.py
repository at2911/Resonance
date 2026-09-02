"""FastAPI application entrypoint."""

import logging

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.agora import router as agora_router
from app.api.conversation import router as conversation_router
from app.api.demo import router as demo_router
from app.api.incidents import router as incidents_router
from app.api.slack import router as slack_router
from app.config import get_settings

logging.basicConfig(level=get_settings().log_level)

app = FastAPI(title="Resonance — Incident Commander", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(incidents_router)
app.include_router(conversation_router)
app.include_router(slack_router)
app.include_router(agora_router)
app.include_router(demo_router)


@app.get("/health")
def health():
    return {"status": "ok"}
