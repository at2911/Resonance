"""The deterministic demo scenario (project spec §19): a Payment API
outage narrated by a Backend Engineer, an SRE, and an Incident Commander,
demonstrating facts, a hypothesis conflict, information gaps, an owned
action, a decision, and an AI-proposed Slack update.

Every step below calls only existing, unmodified IncidentStateService
methods (and the existing SlackMessageComposer) — there is no parallel
state-mutation path here, and nothing here calls an LLM or Agora. Steps
are applied one at a time by DemoService.tick(); this module only defines
*what* each step does, not *when* — see service.py for pacing/control.

The Slack-approval steps from the spec (human approves -> Slack executes)
are deliberately NOT scripted here: this list stops at "AI proposes a
Slack update" (a PENDING ExternalAction). Approval and execution only
ever happen through the existing, unmodified
decide_external_action/mark_external_action_executing path, triggered by
an actual human clicking Approve in the dashboard — scripting that away
would defeat the entire point of the human-approval gate this project is
built around.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from app.config import get_settings
from app.models.enums import ActionPriority, ClaimStatus, ClaimType, ConflictType, ExternalActionType, GapImportance
from app.services.incident_state.service import IncidentStateService
from app.services.slack.composer import SlackMessageComposer

StepFn = Callable[[IncidentStateService, str, dict], str]


@dataclass(frozen=True)
class DemoStep:
    description: str
    apply: StepFn


def _step_fact_503(service: IncidentStateService, incident_id: str, memo: dict) -> str:
    claim = service.add_claim(
        incident_id,
        text="I checked the payment dashboard and the API is returning 503 errors.",
        normalized_claim="Payment API is returning 503 errors",
        type=ClaimType.FACT,
        status=ClaimStatus.CONFIRMED,
        confidence=0.97,
        speaker_id=memo["alice_id"],
        evidence="Alice checked the payment dashboard",
        entities=["payment-api"],
    )
    memo["fact_503_id"] = claim.id
    return "FACT confirmed: Payment API is returning 503 errors"


def _step_fact_deployment(service: IncidentStateService, incident_id: str, memo: dict) -> str:
    claim = service.add_claim(
        incident_id,
        text="Priya confirmed a deployment to payment-service went out at 10:40.",
        normalized_claim="Deployment to payment-service occurred at 10:40",
        type=ClaimType.FACT,
        status=ClaimStatus.CONFIRMED,
        confidence=0.9,
        speaker_id=memo["priya_id"],
        evidence="Priya confirmed via the deployment log",
        entities=["deployment", "payment-api"],
    )
    memo["fact_deployment_id"] = claim.id
    return "FACT confirmed: recent deployment identified"


def _step_hypothesis_database(service: IncidentStateService, incident_id: str, memo: dict) -> str:
    claim = service.add_claim(
        incident_id,
        text="I think the database connection pool might be exhausted.",
        normalized_claim="Database connection pool may be exhausted",
        type=ClaimType.HYPOTHESIS,
        status=ClaimStatus.UNCONFIRMED,
        confidence=0.55,
        speaker_id=memo["alice_id"],
        entities=["database"],
    )
    memo["hypothesis_db_id"] = claim.id
    return "HYPOTHESIS raised (Backend Engineer): database connection pool may be exhausted"


def _step_hypothesis_network(service: IncidentStateService, incident_id: str, memo: dict) -> str:
    claim = service.add_claim(
        incident_id,
        text="The database looks healthy to me; I think the network is dropping packets.",
        normalized_claim="Database appears healthy; network is dropping packets",
        type=ClaimType.HYPOTHESIS,
        status=ClaimStatus.UNCONFIRMED,
        confidence=0.6,
        speaker_id=memo["bob_id"],
        entities=["database", "network"],
    )
    memo["hypothesis_network_id"] = claim.id
    return "HYPOTHESIS raised (SRE): network packet loss — conflicts with the database hypothesis"


def _step_conflict(service: IncidentStateService, incident_id: str, memo: dict) -> str:
    service.add_conflict(
        incident_id,
        claim_a=memo["hypothesis_db_id"],
        claim_b=memo["hypothesis_network_id"],
        conflict_type=ConflictType.DATABASE_HEALTH,
        explanation=(
            "Alice reports possible database exhaustion while Bob reports the database is "
            "healthy and blames the network — both cannot be true as stated."
        ),
    )
    return "CONFLICT DETECTED: database hypothesis vs. network hypothesis"


def _step_gaps(service: IncidentStateService, incident_id: str, memo: dict) -> str:
    service.add_information_gap(
        incident_id, "Customer impact has not been established.", GapImportance.CRITICAL
    )
    service.add_information_gap(
        incident_id, "Rollback status has not been decided.", GapImportance.CRITICAL
    )
    return "INFORMATION GAPS flagged: customer impact, rollback status"


def _step_action(service: IncidentStateService, incident_id: str, memo: dict) -> str:
    action = service.add_action(
        incident_id,
        description="Check network metrics for packet loss",
        owner="Bob",
        owner_confidence=0.9,
        priority=ActionPriority.HIGH,
    )
    memo["action_id"] = action.id
    return "ACTION assigned to Bob (SRE): check network metrics"


def _step_decision(service: IncidentStateService, incident_id: str, memo: dict) -> str:
    service.add_claim(
        incident_id,
        text="Let's prepare a rollback if we don't confirm root cause within 10 minutes. Agreed.",
        normalized_claim="Team agreed to prepare a rollback if root cause isn't confirmed within 10 minutes",
        type=ClaimType.DECISION,
        status=ClaimStatus.CONFIRMED,
        confidence=0.95,
        speaker_id=memo["priya_id"],
        evidence="Explicit team agreement in conversation",
    )
    return "DECISION recorded: prepare rollback if root cause remains unconfirmed"


def _step_propose_slack(service: IncidentStateService, incident_id: str, memo: dict) -> str:
    settings = get_settings()
    incident = service.get(incident_id)
    text = SlackMessageComposer.compose(incident)
    channel = settings.slack_channel_id or "#incident-demo"
    ea = service.propose_external_action(
        incident_id, ExternalActionType.SLACK_MESSAGE, {"channel": channel, "text": text}
    )
    memo["external_action_id"] = ea.id
    return "AI proposed a Slack update — awaiting human approval"


DEMO_SCRIPT: list[DemoStep] = [
    DemoStep("Payment API 503 confirmed", _step_fact_503),
    DemoStep("Recent deployment identified", _step_fact_deployment),
    DemoStep("Engineer raises database hypothesis", _step_hypothesis_database),
    DemoStep("SRE raises network hypothesis", _step_hypothesis_network),
    DemoStep("Contradiction detected", _step_conflict),
    DemoStep("Information gaps identified", _step_gaps),
    DemoStep("Action assigned to owner", _step_action),
    DemoStep("Decision recorded", _step_decision),
    DemoStep("AI proposes Slack update", _step_propose_slack),
]
