"""Tests for backend-driven Demo Mode (spec §19).

DemoService is constructed with step_interval=timedelta(seconds=0) in
every test so tick() advances deterministically on every call — no real
waiting, no wall-clock mocking needed. This also proves something real:
demo playback needs zero LLM/Agora/Slack configuration to run, since
DemoService never touches any of those — every test here runs with none
of that configured, same as the rest of the suite.
"""

from __future__ import annotations

from datetime import timedelta

import pytest
from fastapi.testclient import TestClient

from app.main import app
from app.models.enums import ApprovalStatus, ClaimStatus, ClaimType
from app.repositories.incident_repository import InMemoryIncidentRepository
from app.services.demo.dependency import get_demo_service
from app.services.demo.script import DEMO_SCRIPT
from app.services.demo.service import STATUS_COMPLETED, STATUS_IDLE, STATUS_PAUSED, STATUS_PLAYING, DemoService
from app.services.incident_state.dependency import get_incident_state_service
from app.services.incident_state.service import IncidentStateService

TOTAL_STEPS = len(DEMO_SCRIPT)


@pytest.fixture
def state_service() -> IncidentStateService:
    return IncidentStateService(InMemoryIncidentRepository())


@pytest.fixture
def demo_service(state_service: IncidentStateService) -> DemoService:
    return DemoService(state_service, step_interval=timedelta(seconds=0))


# ---------------------------------------------------------------------
# DemoService unit tests
# ---------------------------------------------------------------------


def test_start_creates_incident_with_three_participants_and_is_playing(demo_service, state_service):
    status = demo_service.start()

    assert status.status == STATUS_PLAYING
    assert status.incident_id is not None
    assert status.current_step == 0
    assert status.total_steps == TOTAL_STEPS

    incident = state_service.get(status.incident_id)
    assert incident.title == "Payment API Outage"
    assert len(incident.participants) == 3
    roles = {p.role.value for p in incident.participants.values()}
    assert roles == {"BACKEND_ENGINEER", "SRE", "INCIDENT_COMMANDER"}


def test_tick_advances_exactly_one_step_at_a_time(demo_service):
    demo_service.start()
    first = demo_service.tick()
    assert first.current_step == 1
    second = demo_service.tick()
    assert second.current_step == 2


def test_full_playback_produces_facts_hypotheses_conflict_gaps_action_decision(demo_service, state_service):
    status = demo_service.start()
    for _ in range(TOTAL_STEPS):
        status = demo_service.tick()

    assert status.status == STATUS_COMPLETED
    assert status.current_step == TOTAL_STEPS

    incident = state_service.get(status.incident_id)
    claims = list(incident.claims.values())

    facts = [c for c in claims if c.type == ClaimType.FACT]
    hypotheses = [c for c in claims if c.type == ClaimType.HYPOTHESIS]
    decisions = [c for c in claims if c.type == ClaimType.DECISION]

    assert len(facts) == 2 and all(c.status == ClaimStatus.CONFIRMED for c in facts)
    assert len(hypotheses) == 2 and all(c.status in (ClaimStatus.UNCONFIRMED, ClaimStatus.DISPUTED) for c in hypotheses)
    assert len(decisions) == 1 and decisions[0].status == ClaimStatus.CONFIRMED

    assert len(incident.conflicts) == 1
    conflict = next(iter(incident.conflicts.values()))
    assert conflict.conflict_type.value == "DATABASE_HEALTH"
    # Both conflicting claims preserved and marked DISPUTED, never deleted.
    assert incident.claims[conflict.claim_a].status == ClaimStatus.DISPUTED
    assert incident.claims[conflict.claim_b].status == ClaimStatus.DISPUTED

    assert len(incident.information_gaps) == 2
    assert all(g.importance.value == "CRITICAL" for g in incident.information_gaps.values())

    assert len(incident.actions) == 1
    action = next(iter(incident.actions.values()))
    assert action.owner == "Bob"
    assert action.status.value == "OPEN"

    assert len(incident.external_actions) == 1
    ea = next(iter(incident.external_actions.values()))
    assert ea.approval_status == ApprovalStatus.PENDING  # proposed, NOT auto-approved
    assert ea.payload["text"]  # a real composed message, not empty

    summary = state_service.generate_final_summary(status.incident_id)
    assert summary.root_cause_confirmed is False
    assert summary.root_cause_statement == "Root cause remains unconfirmed."


def test_demo_never_auto_approves_or_executes_the_slack_proposal(demo_service, state_service):
    """The human-approval gate must be completely untouched by demo
    playback — DemoService only ever proposes, never decides or executes."""
    status = demo_service.start()
    for _ in range(TOTAL_STEPS):
        status = demo_service.tick()

    incident = state_service.get(status.incident_id)
    ea = next(iter(incident.external_actions.values()))
    assert ea.approval_status == ApprovalStatus.PENDING
    assert ea.approved_by is None
    assert ea.execution_status.value == "NOT_EXECUTED"

    # And the existing, unmodified approval gate still works normally on
    # the demo's own incident — it's an ordinary incident to that code.
    decided = state_service.decide_external_action(status.incident_id, ea.id, approved=True, approved_by="ic-demo")
    assert decided.approval_status == ApprovalStatus.APPROVED


def test_pause_stops_further_advancement(demo_service):
    demo_service.start()
    demo_service.tick()
    paused = demo_service.pause()
    assert paused.status == STATUS_PAUSED

    still_paused = demo_service.tick()
    assert still_paused.status == STATUS_PAUSED
    assert still_paused.current_step == paused.current_step  # unchanged


def test_resume_continues_from_where_it_left_off(demo_service):
    demo_service.start()
    demo_service.tick()
    demo_service.tick()
    before = demo_service.pause()

    demo_service.tick()  # no-op while paused
    resumed = demo_service.resume()
    assert resumed.status == STATUS_PLAYING

    after = demo_service.tick()
    assert after.current_step == before.current_step + 1


def test_reset_returns_to_idle_and_start_creates_a_fresh_incident(demo_service, state_service):
    first = demo_service.start()
    demo_service.tick()
    demo_service.tick()

    reset_status = demo_service.reset()
    assert reset_status.status == STATUS_IDLE
    assert reset_status.incident_id is None
    assert reset_status.current_step == 0

    second = demo_service.start()
    assert second.incident_id != first.incident_id
    assert second.current_step == 0
    # The old incident is untouched, still exists with its partial state —
    # reset doesn't destroy history, it just starts a new session.
    old_incident = state_service.get(first.incident_id)
    assert len(old_incident.claims) == 2


def test_status_polling_alone_drives_playback_to_completion(demo_service):
    """This is the exact mechanism the frontend relies on: repeatedly
    calling get_status() (what GET /demo/status calls) must be sufficient
    to play the whole scenario, with no other trigger."""
    started = demo_service.start()
    steps_seen = {started.current_step}  # 0, before any tick — only start() itself observes this
    status = started
    for _ in range(TOTAL_STEPS + 3):
        status = demo_service.get_status()
        steps_seen.add(status.current_step)

    assert status.status == STATUS_COMPLETED
    assert steps_seen == set(range(TOTAL_STEPS + 1))  # every step number 0..N was observed, none skipped


def test_ticking_before_start_is_a_safe_no_op(demo_service):
    status = demo_service.tick()
    assert status.status == STATUS_IDLE
    assert status.incident_id is None


def test_pause_and_resume_before_start_are_safe_no_ops(demo_service):
    assert demo_service.pause().status == STATUS_IDLE
    assert demo_service.resume().status == STATUS_IDLE


def test_ticking_after_completion_is_a_safe_no_op(demo_service):
    demo_service.start()
    for _ in range(TOTAL_STEPS):
        demo_service.tick()
    completed = demo_service.tick()
    assert completed.status == STATUS_COMPLETED
    again = demo_service.tick()
    assert again.current_step == completed.current_step


# ---------------------------------------------------------------------
# HTTP layer — no LLM/Agora/Slack configured at all, proving Demo Mode
# genuinely needs none of it.
# ---------------------------------------------------------------------


@pytest.fixture
def demo_client(state_service):
    fresh_demo_service = DemoService(state_service, step_interval=timedelta(seconds=0))
    app.dependency_overrides[get_incident_state_service] = lambda: state_service
    app.dependency_overrides[get_demo_service] = lambda: fresh_demo_service
    yield TestClient(app)
    app.dependency_overrides.clear()


def test_http_start_pause_resume_reset_cycle(demo_client):
    started = demo_client.post("/demo/start").json()
    assert started["status"] == "PLAYING"
    incident_id = started["incident_id"]
    assert incident_id

    demo_client.get(f"/incidents/{incident_id}")  # ordinary incident, reachable via the ordinary API

    paused = demo_client.post("/demo/pause").json()
    assert paused["status"] == "PAUSED"

    status_while_paused = demo_client.get("/demo/status").json()
    assert status_while_paused["status"] == "PAUSED"
    assert status_while_paused["current_step"] == paused["current_step"]

    resumed = demo_client.post("/demo/resume").json()
    assert resumed["status"] == "PLAYING"

    reset = demo_client.post("/demo/reset").json()
    assert reset["status"] == "IDLE"
    assert reset["incident_id"] is None


def test_http_polling_status_plays_the_whole_scenario_to_completion(demo_client):
    demo_client.post("/demo/start")
    last = None
    for _ in range(TOTAL_STEPS + 2):
        last = demo_client.get("/demo/status").json()

    assert last["status"] == "COMPLETED"
    incident_id = last["incident_id"]

    incident = demo_client.get(f"/incidents/{incident_id}").json()
    assert len(incident["claims"]) == 5  # 2 facts + 2 hypotheses + 1 decision
    assert len(incident["conflicts"]) == 1
    assert len(incident["information_gaps"]) == 2
    assert len(incident["actions"]) == 1
    assert len(incident["external_actions"]) == 1

    clarity = demo_client.get(f"/incidents/{incident_id}/clarity").json()
    assert clarity["open_conflicts"] == 1
    assert clarity["root_cause_confirmed"] is False


def test_http_demo_proposal_still_requires_real_human_approval_via_existing_endpoint(demo_client):
    """Isolates the approval gate itself (409 before approval) from the
    separate "Slack not configured" concern (503, already covered by
    test_slack.py) by overriding get_slack_client with a fake — same
    pattern test_slack.py itself uses. The point here is Demo Mode: the
    gate in front of a demo-proposed action is the exact same,
    unmodified gate in front of a manually-proposed one.
    """
    from app.api.slack import get_slack_client

    class FakeSlackClient:
        def post_message(self, channel, text):
            return {"ts": "1.1", "channel": channel}

    app.dependency_overrides[get_slack_client] = lambda: FakeSlackClient()

    demo_client.post("/demo/start")
    for _ in range(TOTAL_STEPS + 1):
        status = demo_client.get("/demo/status").json()

    incident_id = status["incident_id"]
    incident = demo_client.get(f"/incidents/{incident_id}").json()
    ea_id = next(iter(incident["external_actions"].keys()))
    ea = incident["external_actions"][ea_id]
    assert ea["approval_status"] == "PENDING"

    # Executing before approval must still be rejected — the existing gate,
    # completely untouched by Demo Mode.
    pre_approval = demo_client.post(f"/incidents/{incident_id}/external-actions/{ea_id}/execute")
    assert pre_approval.status_code == 409

    approved = demo_client.post(
        f"/incidents/{incident_id}/external-actions/{ea_id}/decision",
        json={"approved": True, "approved_by": "ic-demo"},
    )
    assert approved.json()["approval_status"] == "APPROVED"

    executed = demo_client.post(f"/incidents/{incident_id}/external-actions/{ea_id}/execute")
    assert executed.json()["execution_status"] == "SUCCEEDED"
