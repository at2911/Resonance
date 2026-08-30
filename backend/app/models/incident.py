"""Canonical IncidentState domain model.

This module is the single source of truth for what an "incident" is. The
backend Incident State Engine (app/services/incident_state) is the only
component permitted to mutate these objects. The frontend and the LLM both
receive read views derived from this state — neither owns it.

Every object that represents an AI-derived or human-derived claim about the
world carries provenance (speaker, timestamp, source_text, evidence) so a
judge (or an engineer) can always answer "why does the system believe this?".
"""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import (
    ActionPriority,
    ActionStatus,
    ApprovalStatus,
    ClaimStatus,
    ClaimType,
    ConflictStatus,
    ConflictType,
    ExecutionStatus,
    ExternalActionType,
    GapImportance,
    GapStatus,
    IncidentDimension,
    IncidentSeverity,
    IncidentStatus,
    ParticipantRole,
    RiskSeverity,
    RiskStatus,
    TimelineEventType,
)


def new_id() -> str:
    return uuid.uuid4().hex


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Participant(BaseModel):
    id: str = Field(default_factory=new_id)
    name: str
    role: ParticipantRole = ParticipantRole.UNKNOWN
    role_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    joined_at: datetime = Field(default_factory=utcnow)
    agora_uid: Optional[str] = None
    """Set when this participant was identified via an Agora conversation
    (app/services/agora/identity.py) — never assumed equal to the
    Participant id itself. None for participants added manually.
    """


class Claim(BaseModel):
    id: str = Field(default_factory=new_id)
    text: str
    """Raw source utterance the claim was extracted from."""
    normalized_claim: str
    """Canonicalized form used for comparison/contradiction detection."""
    type: ClaimType
    status: ClaimStatus
    confidence: float = Field(ge=0.0, le=1.0)
    speaker_id: Optional[str] = None
    timestamp: datetime = Field(default_factory=utcnow)
    evidence: Optional[str] = None
    supporting_events: list[str] = Field(default_factory=list)
    contradicting_events: list[str] = Field(default_factory=list)
    entities: list[str] = Field(default_factory=list)
    """Extracted entities (e.g. system/component names) — used by the
    Contradiction Engine's candidate-generation prefilter (§8) and part of
    the per-utterance extraction schema (§6). Not in the spec's minimum
    Claims field list, but required to implement both of those sections.
    """


class Action(BaseModel):
    id: str = Field(default_factory=new_id)
    description: str
    owner: Optional[str] = None
    owner_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    status: ActionStatus = ActionStatus.OPEN
    priority: ActionPriority = ActionPriority.NORMAL
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)
    due_at: Optional[datetime] = None
    dependencies: list[str] = Field(default_factory=list)
    source_event_id: Optional[str] = None
    completion_evidence: Optional[str] = None


class Conflict(BaseModel):
    id: str = Field(default_factory=new_id)
    claim_a: str
    """Claim id."""
    claim_b: str
    """Claim id."""
    conflict_type: ConflictType
    detected_at: datetime = Field(default_factory=utcnow)
    status: ConflictStatus = ConflictStatus.OPEN
    explanation: str
    resolution_evidence: Optional[str] = None


class InformationGap(BaseModel):
    id: str = Field(default_factory=new_id)
    description: str
    importance: GapImportance
    detected_at: datetime = Field(default_factory=utcnow)
    related_claims: list[str] = Field(default_factory=list)
    status: GapStatus = GapStatus.OPEN
    dimension: Optional[IncidentDimension] = None
    """Set when this gap was raised by the Information Gap Engine's fixed
    dimension checklist (§9) — lets the engine idempotently resolve/recreate
    a gap for the same dimension turn over turn instead of fuzzy-matching
    free-text descriptions. None for gaps added ad hoc through the API.
    """


class Risk(BaseModel):
    id: str = Field(default_factory=new_id)
    description: str
    severity: RiskSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    mitigation: Optional[str] = None
    status: RiskStatus = RiskStatus.OPEN


class TimelineEvent(BaseModel):
    id: str = Field(default_factory=new_id)
    timestamp: datetime = Field(default_factory=utcnow)
    event_type: TimelineEventType
    speaker: Optional[str] = None
    content: str
    related_claim_ids: list[str] = Field(default_factory=list)
    related_action_ids: list[str] = Field(default_factory=list)


class ExternalAction(BaseModel):
    id: str = Field(default_factory=new_id)
    action_type: ExternalActionType
    payload: dict
    idempotency_key: str = Field(default_factory=new_id)
    proposed_at: datetime = Field(default_factory=utcnow)
    approval_status: ApprovalStatus = ApprovalStatus.PENDING
    approved_by: Optional[str] = None
    approved_at: Optional[datetime] = None
    executed_at: Optional[datetime] = None
    execution_status: ExecutionStatus = ExecutionStatus.NOT_EXECUTED
    execution_result: Optional[str] = None


class ClarityScoreBreakdown(BaseModel):
    """Explainable, deterministic clarity indicator (see IncidentStateService.
    compute_clarity_score). This is an operational heuristic, not a
    scientifically validated metric — every component is exposed so it can
    be inspected rather than trusted blindly.
    """

    score: int
    confirmed_facts: int
    unresolved_hypotheses: int
    disputed_claims: int
    open_conflicts: int
    critical_information_gaps: int
    normal_information_gaps: int
    open_actions: int
    unowned_open_actions: int
    stale_actions: int
    root_cause_confirmed: bool


class FinalSummary(BaseModel):
    """Deterministically assembled from state — never LLM free text."""

    incident_id: str
    generated_at: datetime = Field(default_factory=utcnow)
    confirmed_facts: list[Claim]
    hypotheses: list[Claim]
    decisions: list[Claim]
    actions: list[Action]
    conflicts: list[Conflict]
    unresolved_risks: list[Risk]
    open_information_gaps: list[InformationGap]
    root_cause_confirmed: bool
    root_cause_statement: str


class Incident(BaseModel):
    id: str = Field(default_factory=new_id)
    title: str
    severity: IncidentSeverity = IncidentSeverity.UNKNOWN
    status: IncidentStatus = IncidentStatus.ACTIVE
    start_time: datetime = Field(default_factory=utcnow)
    current_summary: str = ""
    clarity_score: int = Field(default=100, ge=0, le=100)
    created_at: datetime = Field(default_factory=utcnow)
    updated_at: datetime = Field(default_factory=utcnow)

    participants: dict[str, Participant] = Field(default_factory=dict)
    claims: dict[str, Claim] = Field(default_factory=dict)
    actions: dict[str, Action] = Field(default_factory=dict)
    conflicts: dict[str, Conflict] = Field(default_factory=dict)
    information_gaps: dict[str, InformationGap] = Field(default_factory=dict)
    risks: dict[str, Risk] = Field(default_factory=dict)
    timeline: list[TimelineEvent] = Field(default_factory=list)
    external_actions: dict[str, ExternalAction] = Field(default_factory=dict)

    def root_cause_confirmed(self) -> bool:
        """True only if a FACT-type, CONFIRMED claim exists that is explicitly
        marked as addressing root cause. The engine never infers this from a
        repeated hypothesis — see app/services/incident_state/service.py.
        """
        return any(
            c.type == ClaimType.FACT
            and c.status == ClaimStatus.CONFIRMED
            and "root cause" in c.normalized_claim.lower()
            for c in self.claims.values()
        )
