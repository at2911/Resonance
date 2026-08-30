"""Backend-driven Demo Mode (spec §19).

Deliberately not implemented with a background thread/timer — nothing
else in this codebase runs background work, and a thread would need its
own lifecycle management (leaks across test runs, restart-on-crash,
shutdown handling) for no real benefit here. Instead, playback is
advanced *lazily*: `tick()` applies the next script step only if enough
wall-clock time has passed since the last one and the session is
PLAYING. The frontend already polls incident state on an interval for
every other view in this app (see useIncident.ts) — a demo status poll
at the same cadence is what actually drives progression, while
Start/Pause/Resume/Reset remain explicit, human-triggered actions.

This holds one global demo session, matching the single-incident-room
scale the rest of this prototype is built at (IncidentStateService and
AgoraRepository are both singletons the same way).
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

from app.models.enums import IncidentSeverity, ParticipantRole
from app.services.demo.schemas import DemoStatus
from app.services.demo.script import DEMO_SCRIPT
from app.services.incident_state.service import IncidentStateService

DEFAULT_STEP_INTERVAL = timedelta(seconds=3)

STATUS_IDLE = "IDLE"
STATUS_PLAYING = "PLAYING"
STATUS_PAUSED = "PAUSED"
STATUS_COMPLETED = "COMPLETED"


def _now() -> datetime:
    return datetime.now(timezone.utc)


class DemoService:
    def __init__(
        self, state_service: IncidentStateService, step_interval: timedelta = DEFAULT_STEP_INTERVAL
    ) -> None:
        self._state_service = state_service
        self._step_interval = step_interval
        self._lock = threading.RLock()
        self._status = STATUS_IDLE
        self._incident_id: Optional[str] = None
        self._current_step = 0
        self._last_step_at: Optional[datetime] = None
        self._last_step_description: Optional[str] = None
        self._memo: dict = {}

    def start(self) -> DemoStatus:
        """Always creates a fresh incident, regardless of any prior demo
        session's state — the demo must be safe to rehearse repeatedly."""
        with self._lock:
            incident = self._state_service.create_incident("Payment API Outage", IncidentSeverity.SEV1)
            alice = self._state_service.add_participant(
                incident.id, "Alice", ParticipantRole.BACKEND_ENGINEER, 0.9
            )
            bob = self._state_service.add_participant(incident.id, "Bob", ParticipantRole.SRE, 0.9)
            priya = self._state_service.add_participant(
                incident.id, "Priya", ParticipantRole.INCIDENT_COMMANDER, 0.9
            )

            self._incident_id = incident.id
            self._memo = {"alice_id": alice.id, "bob_id": bob.id, "priya_id": priya.id}
            self._current_step = 0
            self._status = STATUS_PLAYING
            # Backdated so the very first tick() applies step 0 immediately
            # rather than making the presenter wait a full interval before
            # anything visibly happens after clicking Start.
            self._last_step_at = _now() - self._step_interval
            self._last_step_description = "Incident detected: Payment API Outage"
            return self._snapshot()

    def pause(self) -> DemoStatus:
        with self._lock:
            if self._status == STATUS_PLAYING:
                self._status = STATUS_PAUSED
            return self._snapshot()

    def resume(self) -> DemoStatus:
        with self._lock:
            if self._status == STATUS_PAUSED:
                self._status = STATUS_PLAYING
                # Same reasoning as start(): show the next beat right away.
                self._last_step_at = _now() - self._step_interval
            return self._snapshot()

    def reset(self) -> DemoStatus:
        with self._lock:
            self._status = STATUS_IDLE
            self._incident_id = None
            self._current_step = 0
            self._last_step_at = None
            self._last_step_description = None
            self._memo = {}
            return self._snapshot()

    def tick(self) -> DemoStatus:
        """Applies at most one step per call, never a burst of several
        even if far more than one interval has elapsed since the last
        poll — a live demo should always advance one beat at a time."""
        with self._lock:
            if (
                self._status == STATUS_PLAYING
                and self._incident_id is not None
                and self._current_step < len(DEMO_SCRIPT)
                and self._last_step_at is not None
                and _now() - self._last_step_at >= self._step_interval
            ):
                step = DEMO_SCRIPT[self._current_step]
                description = step.apply(self._state_service, self._incident_id, self._memo)
                self._current_step += 1
                self._last_step_at = _now()
                self._last_step_description = description
                if self._current_step >= len(DEMO_SCRIPT):
                    self._status = STATUS_COMPLETED
            return self._snapshot()

    def get_status(self) -> DemoStatus:
        return self.tick()

    def _snapshot(self) -> DemoStatus:
        return DemoStatus(
            status=self._status,
            incident_id=self._incident_id,
            current_step=self._current_step,
            total_steps=len(DEMO_SCRIPT),
            last_step_description=self._last_step_description,
        )
