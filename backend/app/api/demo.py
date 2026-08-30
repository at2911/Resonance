"""Backend-driven Demo Mode endpoints (spec §19).

Deterministic, scripted, requires no LLM key, no Agora, no Slack
credentials — see app/services/demo/service.py. GET /demo/status is the
endpoint that actually advances playback (see that module's docstring for
why); the frontend polls it the same way it already polls incident state.
"""

from __future__ import annotations

from fastapi import APIRouter, Depends

from app.services.demo.dependency import get_demo_service
from app.services.demo.schemas import DemoStatus
from app.services.demo.service import DemoService

router = APIRouter(prefix="/demo", tags=["demo"])


@router.post("/start", response_model=DemoStatus)
def start_demo(service: DemoService = Depends(get_demo_service)):
    return service.start()


@router.post("/pause", response_model=DemoStatus)
def pause_demo(service: DemoService = Depends(get_demo_service)):
    return service.pause()


@router.post("/resume", response_model=DemoStatus)
def resume_demo(service: DemoService = Depends(get_demo_service)):
    return service.resume()


@router.post("/reset", response_model=DemoStatus)
def reset_demo(service: DemoService = Depends(get_demo_service)):
    return service.reset()


@router.get("/status", response_model=DemoStatus)
def demo_status(service: DemoService = Depends(get_demo_service)):
    return service.get_status()
