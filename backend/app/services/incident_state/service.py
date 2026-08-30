"""Incident State Engine.

This is the single authority for mutating IncidentState. No other layer
(frontend, LLM extraction, API handler) is permitted to write incident state
directly — everything goes through these methods so that:

  * every mutation produces an auditable TimelineEvent,
  * state-transition rules (e.g. "a conflict needs evidence to resolve") are
    enforced in one place instead of scattered across callers,
  * the clarity score and final summary stay derived, deterministic
    projections of the same underlying state rather than separately
    hallucinated artifacts.

Callers (extraction layer, contradiction engine, gap engine, approvals,
Slack service, API routes) all depend on this service, never on the
repository directly.
"""

from __future__ import annotations

import threading
from datetime import datetime, timedelta, timezone
from typing import Optional

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
    IncidentSeverity,
    ParticipantRole,
    RiskSeverity,
    RiskStatus,
    TimelineEventType,
)
from app.models.incident import (
    Action,
    Claim,
    ClarityScoreBreakdown,
    Conflict,
    ExternalAction,
    FinalSummary,
    Incident,
    InformationGap,
    Participant,
    Risk,
    TimelineEvent,
    new_id,
    utcnow,
)
from app.repositories.incident_repository import IncidentRepository

# Deterministic clarity-score weights. Documented and adjustable, but never
# produced by an LLM — the score must be reproducible from state alone.
CRITICAL_GAP_PENALTY = 15
NORMAL_GAP_PENALTY = 5
OPEN_CONFLICT_PENALTY = 10
DISPUTED_CLAIM_PENALTY = 4
UNRESOLVED_HYPOTHESIS_PENALTY = 3
UNOWNED_ACTION_PENALTY = 8
STALE_ACTION_PENALTY = 5
STALE_ACTION_THRESHOLD = timedelta(minutes=15)

_OPEN_ACTION_STATUSES = (ActionStatus.OPEN, ActionStatus.IN_PROGRESS, ActionStatus.BLOCKED)
_OPEN_CONFLICT_STATUSES = (ConflictStatus.OPEN, ConflictStatus.ACKNOWLEDGED)

_ACTION_TRANSITIONS: dict[ActionStatus, set[ActionStatus]] = {
    ActionStatus.OPEN: {
        ActionStatus.IN_PROGRESS,
        ActionStatus.BLOCKED,
        ActionStatus.CANCELLED,
        ActionStatus.COMPLETED,
    },
    ActionStatus.IN_PROGRESS: {
        ActionStatus.BLOCKED,
        ActionStatus.COMPLETED,
        ActionStatus.CANCELLED,
        ActionStatus.OPEN,
    },
    ActionStatus.BLOCKED: {ActionStatus.OPEN, ActionStatus.IN_PROGRESS, ActionStatus.CANCELLED},
    ActionStatus.COMPLETED: set(),
    ActionStatus.CANCELLED: set(),
}

_CONFLICT_TRANSITIONS: dict[ConflictStatus, set[ConflictStatus]] = {
    ConflictStatus.OPEN: {ConflictStatus.ACKNOWLEDGED, ConflictStatus.RESOLVED},
    ConflictStatus.ACKNOWLEDGED: {ConflictStatus.RESOLVED, ConflictStatus.OPEN},
    ConflictStatus.RESOLVED: set(),
}


class InvalidStateTransitionError(Exception):
    pass


class EvidenceRequiredError(Exception):
    pass


class IncidentStateService:
    def __init__(self, repository: IncidentRepository) -> None:
        self._repo = repository
        self._lock = threading.RLock()

    # ------------------------------------------------------------------
    # Incident lifecycle
    # ------------------------------------------------------------------

    def create_incident(
        self, title: str, severity: IncidentSeverity = IncidentSeverity.UNKNOWN
    ) -> Incident:
        with self._lock:
            incident = Incident(title=title, severity=severity)
            self._emit(
                incident,
                TimelineEventType.INCIDENT_DETECTED,
                content=f"Incident detected: {title}",
            )
            self._touch(incident)
            return self._repo.create(incident)

    def get(self, incident_id: str) -> Incident:
        return self._repo.get(incident_id)

    def list_all(self) -> list[Incident]:
        return self._repo.list_all()

    # ------------------------------------------------------------------
    # Participants
    # ------------------------------------------------------------------

    def add_participant(
        self,
        incident_id: str,
        name: str,
        role: ParticipantRole = ParticipantRole.UNKNOWN,
        role_confidence: float = 0.0,
    ) -> Participant:
        with self._lock:
            incident = self._repo.get(incident_id)
            participant = Participant(name=name, role=role, role_confidence=role_confidence)
            incident.participants[participant.id] = participant
            self._emit(
                incident,
                TimelineEventType.PARTICIPANT_JOINED,
                content=f"{name} joined ({role.value}, confidence={role_confidence:.2f})",
                speaker=participant.id,
            )
            self._touch(incident)
            self._repo.save(incident)
            return participant

    def correct_participant_role(
        self, incident_id: str, participant_id: str, role: ParticipantRole
    ) -> Participant:
        """Explicit human correction always wins — set confidence to 1.0."""
        with self._lock:
            incident = self._repo.get(incident_id)
            participant = self._require(incident.participants, participant_id, "participant")
            participant.role = role
            participant.role_confidence = 1.0
            self._touch(incident)
            self._repo.save(incident)
            return participant

    def update_role_if_more_confident(
        self,
        incident_id: str,
        participant_id: str,
        role: ParticipantRole,
        confidence: float,
    ) -> Participant:
        """Called by the extraction pipeline with an LLM's role guess for a
        speaker. Only applies it if strictly more confident than what's
        already recorded — a human correction is stored at confidence 1.0,
        so this can never overwrite one.
        """
        with self._lock:
            incident = self._repo.get(incident_id)
            participant = self._require(incident.participants, participant_id, "participant")
            if confidence > participant.role_confidence:
                participant.role = role
                participant.role_confidence = confidence
                self._touch(incident)
                self._repo.save(incident)
            return participant

    # ------------------------------------------------------------------
    # Claims (facts / hypotheses / decisions / questions / risks / updates)
    # ------------------------------------------------------------------

    def add_claim(
        self,
        incident_id: str,
        text: str,
        normalized_claim: str,
        type: ClaimType,
        status: ClaimStatus,
        confidence: float,
        speaker_id: Optional[str] = None,
        evidence: Optional[str] = None,
        entities: Optional[list[str]] = None,
    ) -> Claim:
        if status in (ClaimStatus.CONFIRMED, ClaimStatus.RESOLVED) and not evidence:
            raise EvidenceRequiredError(
                f"Claim status {status.value} requires evidence at creation time"
            )
        with self._lock:
            incident = self._repo.get(incident_id)
            claim = Claim(
                text=text,
                normalized_claim=normalized_claim,
                type=type,
                status=status,
                confidence=confidence,
                speaker_id=speaker_id,
                evidence=evidence,
                entities=entities or [],
            )
            incident.claims[claim.id] = claim
            event_type = (
                TimelineEventType.DECISION_RECORDED
                if type == ClaimType.DECISION
                else TimelineEventType.CLAIM_ADDED
            )
            self._emit(
                incident,
                event_type,
                content=f"{type.value} ({status.value}): {normalized_claim}",
                speaker=speaker_id,
                related_claim_ids=[claim.id],
            )
            self._touch(incident)
            self._repo.save(incident)
            return claim

    def update_claim_status(
        self,
        incident_id: str,
        claim_id: str,
        status: ClaimStatus,
        evidence: Optional[str] = None,
    ) -> Claim:
        """Upgrading a claim to CONFIRMED or RESOLVED always requires
        evidence — a hypothesis is never promoted merely because it was
        repeated.
        """
        if status in (ClaimStatus.CONFIRMED, ClaimStatus.RESOLVED) and not evidence:
            raise EvidenceRequiredError(f"Promoting a claim to {status.value} requires evidence")
        with self._lock:
            incident = self._repo.get(incident_id)
            claim = self._require(incident.claims, claim_id, "claim")
            claim.status = status
            if evidence:
                claim.evidence = evidence
            self._emit(
                incident,
                TimelineEventType.CLAIM_UPDATED,
                content=f"Claim updated to {status.value}: {claim.normalized_claim}",
                related_claim_ids=[claim.id],
            )
            self._touch(incident)
            self._repo.save(incident)
            return claim

    def supersede_claim(self, incident_id: str, old_claim_id: str, new_claim_id: str) -> Claim:
        """Never delete a superseded claim — mark it SUPERSEDED and keep it
        in state for provenance/audit.
        """
        with self._lock:
            incident = self._repo.get(incident_id)
            old_claim = self._require(incident.claims, old_claim_id, "claim")
            new_claim = self._require(incident.claims, new_claim_id, "claim")
            old_claim.status = ClaimStatus.SUPERSEDED
            new_claim.supporting_events.append(old_claim.id)
            self._emit(
                incident,
                TimelineEventType.CLAIM_UPDATED,
                content=f"Claim superseded by newer claim: {new_claim.normalized_claim}",
                related_claim_ids=[old_claim.id, new_claim.id],
            )
            self._touch(incident)
            self._repo.save(incident)
            return old_claim

    # ------------------------------------------------------------------
    # Actions
    # ------------------------------------------------------------------

    def add_action(
        self,
        incident_id: str,
        description: str,
        owner: Optional[str] = None,
        owner_confidence: float = 0.0,
        priority: ActionPriority = ActionPriority.NORMAL,
        source_event_id: Optional[str] = None,
        dependencies: Optional[list[str]] = None,
    ) -> Action:
        with self._lock:
            incident = self._repo.get(incident_id)
            action = Action(
                description=description,
                owner=owner,
                owner_confidence=owner_confidence,
                priority=priority,
                source_event_id=source_event_id,
                dependencies=dependencies or [],
            )
            incident.actions[action.id] = action
            owner_text = owner or "UNASSIGNED"
            self._emit(
                incident,
                TimelineEventType.ACTION_ASSIGNED,
                content=f"Action assigned to {owner_text}: {description}",
                related_action_ids=[action.id],
            )
            self._touch(incident)
            self._repo.save(incident)
            return action

    def update_action_status(
        self,
        incident_id: str,
        action_id: str,
        status: ActionStatus,
        completion_evidence: Optional[str] = None,
    ) -> Action:
        if status == ActionStatus.COMPLETED and not completion_evidence:
            raise EvidenceRequiredError("Completing an action requires completion_evidence")
        with self._lock:
            incident = self._repo.get(incident_id)
            action = self._require(incident.actions, action_id, "action")
            allowed = _ACTION_TRANSITIONS[action.status]
            if status != action.status and status not in allowed:
                raise InvalidStateTransitionError(
                    f"Cannot move action from {action.status.value} to {status.value}"
                )
            action.status = status
            action.updated_at = utcnow()
            if completion_evidence:
                action.completion_evidence = completion_evidence
            self._emit(
                incident,
                TimelineEventType.ACTION_UPDATED,
                content=f"Action -> {status.value}: {action.description}",
                related_action_ids=[action.id],
            )
            self._touch(incident)
            self._repo.save(incident)
            return action

    def reassign_action(
        self, incident_id: str, action_id: str, owner: str, owner_confidence: float = 1.0
    ) -> Action:
        with self._lock:
            incident = self._repo.get(incident_id)
            action = self._require(incident.actions, action_id, "action")
            action.owner = owner
            action.owner_confidence = owner_confidence
            action.updated_at = utcnow()
            self._emit(
                incident,
                TimelineEventType.ACTION_UPDATED,
                content=f"Action reassigned to {owner}: {action.description}",
                related_action_ids=[action.id],
            )
            self._touch(incident)
            self._repo.save(incident)
            return action

    # ------------------------------------------------------------------
    # Conflicts
    # ------------------------------------------------------------------

    def add_conflict(
        self,
        incident_id: str,
        claim_a: str,
        claim_b: str,
        conflict_type: ConflictType,
        explanation: str,
    ) -> Conflict:
        with self._lock:
            incident = self._repo.get(incident_id)
            self._require(incident.claims, claim_a, "claim")
            self._require(incident.claims, claim_b, "claim")
            conflict = Conflict(
                claim_a=claim_a,
                claim_b=claim_b,
                conflict_type=conflict_type,
                explanation=explanation,
            )
            incident.conflicts[conflict.id] = conflict
            # Both claims are preserved (never deleted) but marked DISPUTED
            # so the UI surfaces the disagreement instead of silently
            # trusting whichever arrived most recently.
            for cid in (claim_a, claim_b):
                claim = incident.claims[cid]
                if claim.status not in (ClaimStatus.RESOLVED, ClaimStatus.SUPERSEDED):
                    claim.status = ClaimStatus.DISPUTED
                claim.contradicting_events.append(conflict.id)
            self._emit(
                incident,
                TimelineEventType.CONFLICT_DETECTED,
                content=f"Conflict detected ({conflict_type.value}): {explanation}",
                related_claim_ids=[claim_a, claim_b],
            )
            self._touch(incident)
            self._repo.save(incident)
            return conflict

    def acknowledge_conflict(self, incident_id: str, conflict_id: str) -> Conflict:
        return self._transition_conflict(incident_id, conflict_id, ConflictStatus.ACKNOWLEDGED)

    def resolve_conflict(
        self, incident_id: str, conflict_id: str, resolution_evidence: str
    ) -> Conflict:
        """A conflict can only close with supporting evidence or an
        explicit human confirmation string — never silently.
        """
        if not resolution_evidence:
            raise EvidenceRequiredError("Resolving a conflict requires resolution_evidence")
        return self._transition_conflict(
            incident_id, conflict_id, ConflictStatus.RESOLVED, resolution_evidence
        )

    def _transition_conflict(
        self,
        incident_id: str,
        conflict_id: str,
        status: ConflictStatus,
        resolution_evidence: Optional[str] = None,
    ) -> Conflict:
        with self._lock:
            incident = self._repo.get(incident_id)
            conflict = self._require(incident.conflicts, conflict_id, "conflict")
            allowed = _CONFLICT_TRANSITIONS[conflict.status]
            if status != conflict.status and status not in allowed:
                raise InvalidStateTransitionError(
                    f"Cannot move conflict from {conflict.status.value} to {status.value}"
                )
            conflict.status = status
            if resolution_evidence:
                conflict.resolution_evidence = resolution_evidence
            if status == ConflictStatus.RESOLVED:
                self._emit(
                    incident,
                    TimelineEventType.CONFLICT_RESOLVED,
                    content=f"Conflict resolved: {conflict.explanation}",
                    related_claim_ids=[conflict.claim_a, conflict.claim_b],
                )
            self._touch(incident)
            self._repo.save(incident)
            return conflict

    # ------------------------------------------------------------------
    # Information gaps
    # ------------------------------------------------------------------

    def add_information_gap(
        self,
        incident_id: str,
        description: str,
        importance: GapImportance,
        related_claims: Optional[list[str]] = None,
    ) -> InformationGap:
        with self._lock:
            incident = self._repo.get(incident_id)
            gap = InformationGap(
                description=description,
                importance=importance,
                related_claims=related_claims or [],
            )
            incident.information_gaps[gap.id] = gap
            self._emit(
                incident,
                TimelineEventType.GAP_DETECTED,
                content=f"Information gap ({importance.value}): {description}",
                related_claim_ids=gap.related_claims,
            )
            self._touch(incident)
            self._repo.save(incident)
            return gap

    def resolve_information_gap(self, incident_id: str, gap_id: str) -> InformationGap:
        with self._lock:
            incident = self._repo.get(incident_id)
            gap = self._require(incident.information_gaps, gap_id, "information gap")
            gap.status = GapStatus.RESOLVED
            self._emit(
                incident,
                TimelineEventType.GAP_RESOLVED,
                content=f"Information gap resolved: {gap.description}",
                related_claim_ids=gap.related_claims,
            )
            self._touch(incident)
            self._repo.save(incident)
            return gap

    # ------------------------------------------------------------------
    # Risks
    # ------------------------------------------------------------------

    def add_risk(
        self,
        incident_id: str,
        description: str,
        severity: RiskSeverity,
        confidence: float,
        mitigation: Optional[str] = None,
    ) -> Risk:
        with self._lock:
            incident = self._repo.get(incident_id)
            risk = Risk(
                description=description,
                severity=severity,
                confidence=confidence,
                mitigation=mitigation,
            )
            incident.risks[risk.id] = risk
            self._emit(
                incident,
                TimelineEventType.RISK_IDENTIFIED,
                content=f"Risk identified ({severity.value}): {description}",
            )
            self._touch(incident)
            self._repo.save(incident)
            return risk

    def update_risk_status(self, incident_id: str, risk_id: str, status: RiskStatus) -> Risk:
        with self._lock:
            incident = self._repo.get(incident_id)
            risk = self._require(incident.risks, risk_id, "risk")
            risk.status = status
            self._touch(incident)
            self._repo.save(incident)
            return risk

    # ------------------------------------------------------------------
    # External actions (approval-gated — see app/services/approvals)
    # ------------------------------------------------------------------

    def propose_external_action(
        self, incident_id: str, action_type: ExternalActionType, payload: dict
    ) -> ExternalAction:
        with self._lock:
            incident = self._repo.get(incident_id)
            external_action = ExternalAction(action_type=action_type, payload=payload)
            incident.external_actions[external_action.id] = external_action
            self._emit(
                incident,
                TimelineEventType.EXTERNAL_ACTION_PROPOSED,
                content=f"Proposed external action ({action_type.value}), awaiting human approval",
            )
            self._touch(incident)
            self._repo.save(incident)
            return external_action

    def decide_external_action(
        self,
        incident_id: str,
        external_action_id: str,
        approved: bool,
        approved_by: str,
    ) -> ExternalAction:
        with self._lock:
            incident = self._repo.get(incident_id)
            ea = self._require(incident.external_actions, external_action_id, "external action")
            if ea.approval_status != ApprovalStatus.PENDING:
                raise InvalidStateTransitionError(
                    f"External action already {ea.approval_status.value}; refusing to re-decide"
                )
            ea.approval_status = ApprovalStatus.APPROVED if approved else ApprovalStatus.REJECTED
            ea.approved_by = approved_by
            ea.approved_at = utcnow()
            self._emit(
                incident,
                TimelineEventType.HUMAN_APPROVAL,
                content=f"External action {ea.approval_status.value.lower()} by {approved_by}",
            )
            self._touch(incident)
            self._repo.save(incident)
            return ea

    def mark_external_action_executing(
        self, incident_id: str, external_action_id: str
    ) -> ExternalAction:
        """Guards against duplicate/replayed execution: only a PENDING->
        APPROVED action that has never started executing may transition.
        """
        with self._lock:
            incident = self._repo.get(incident_id)
            ea = self._require(incident.external_actions, external_action_id, "external action")
            if ea.approval_status != ApprovalStatus.APPROVED:
                raise InvalidStateTransitionError("External action has not been approved")
            if ea.execution_status != ExecutionStatus.NOT_EXECUTED:
                raise InvalidStateTransitionError(
                    f"External action already {ea.execution_status.value}; refusing duplicate execution"
                )
            ea.execution_status = ExecutionStatus.EXECUTING
            self._touch(incident)
            self._repo.save(incident)
            return ea

    def mark_external_action_result(
        self,
        incident_id: str,
        external_action_id: str,
        succeeded: bool,
        execution_result: str,
    ) -> ExternalAction:
        with self._lock:
            incident = self._repo.get(incident_id)
            ea = self._require(incident.external_actions, external_action_id, "external action")
            if ea.execution_status != ExecutionStatus.EXECUTING:
                raise InvalidStateTransitionError(
                    "External action must be EXECUTING before recording a result"
                )
            ea.execution_status = ExecutionStatus.SUCCEEDED if succeeded else ExecutionStatus.FAILED
            ea.executed_at = utcnow()
            ea.execution_result = execution_result
            self._emit(
                incident,
                TimelineEventType.EXTERNAL_ACTION_EXECUTED
                if succeeded
                else TimelineEventType.EXTERNAL_ACTION_FAILED,
                content=execution_result,
            )
            self._touch(incident)
            self._repo.save(incident)
            return ea

    # ------------------------------------------------------------------
    # Clarity score
    # ------------------------------------------------------------------

    def compute_clarity_score(self, incident_id: str) -> ClarityScoreBreakdown:
        incident = self._repo.get(incident_id)
        return self._compute_clarity_score(incident)

    @staticmethod
    def _compute_clarity_score(incident: Incident) -> ClarityScoreBreakdown:
        now = datetime.now(timezone.utc)
        claims = list(incident.claims.values())

        confirmed_facts = sum(
            1 for c in claims if c.type == ClaimType.FACT and c.status == ClaimStatus.CONFIRMED
        )
        unresolved_hypotheses = sum(
            1
            for c in claims
            if c.type == ClaimType.HYPOTHESIS
            and c.status in (ClaimStatus.UNCONFIRMED, ClaimStatus.PROBABLE)
        )
        disputed_claims = sum(1 for c in claims if c.status == ClaimStatus.DISPUTED)

        open_conflicts = sum(
            1 for c in incident.conflicts.values() if c.status in _OPEN_CONFLICT_STATUSES
        )

        critical_gaps = sum(
            1
            for g in incident.information_gaps.values()
            if g.status == GapStatus.OPEN and g.importance == GapImportance.CRITICAL
        )
        normal_gaps = sum(
            1
            for g in incident.information_gaps.values()
            if g.status == GapStatus.OPEN and g.importance == GapImportance.NORMAL
        )

        open_actions_list = [a for a in incident.actions.values() if a.status in _OPEN_ACTION_STATUSES]
        open_actions = len(open_actions_list)
        unowned_open_actions = sum(1 for a in open_actions_list if not a.owner)
        stale_actions = sum(
            1 for a in open_actions_list if (now - a.updated_at.astimezone(timezone.utc)) > STALE_ACTION_THRESHOLD
        )

        penalty = (
            unresolved_hypotheses * UNRESOLVED_HYPOTHESIS_PENALTY
            + disputed_claims * DISPUTED_CLAIM_PENALTY
            + open_conflicts * OPEN_CONFLICT_PENALTY
            + critical_gaps * CRITICAL_GAP_PENALTY
            + normal_gaps * NORMAL_GAP_PENALTY
            + unowned_open_actions * UNOWNED_ACTION_PENALTY
            + stale_actions * STALE_ACTION_PENALTY
        )
        score = max(0, min(100, 100 - penalty))

        return ClarityScoreBreakdown(
            score=score,
            confirmed_facts=confirmed_facts,
            unresolved_hypotheses=unresolved_hypotheses,
            disputed_claims=disputed_claims,
            open_conflicts=open_conflicts,
            critical_information_gaps=critical_gaps,
            normal_information_gaps=normal_gaps,
            open_actions=open_actions,
            unowned_open_actions=unowned_open_actions,
            stale_actions=stale_actions,
            root_cause_confirmed=incident.root_cause_confirmed(),
        )

    # ------------------------------------------------------------------
    # Final summary — assembled from state, never generated by the LLM
    # ------------------------------------------------------------------

    def generate_final_summary(self, incident_id: str) -> FinalSummary:
        incident = self._repo.get(incident_id)
        claims = list(incident.claims.values())
        root_cause_confirmed = incident.root_cause_confirmed()
        return FinalSummary(
            incident_id=incident.id,
            confirmed_facts=[
                c for c in claims if c.type == ClaimType.FACT and c.status == ClaimStatus.CONFIRMED
            ],
            hypotheses=[c for c in claims if c.type == ClaimType.HYPOTHESIS],
            decisions=[c for c in claims if c.type == ClaimType.DECISION],
            actions=list(incident.actions.values()),
            conflicts=list(incident.conflicts.values()),
            unresolved_risks=[
                r for r in incident.risks.values() if r.status in (RiskStatus.OPEN, RiskStatus.MITIGATED)
            ],
            open_information_gaps=[
                g for g in incident.information_gaps.values() if g.status == GapStatus.OPEN
            ],
            root_cause_confirmed=root_cause_confirmed,
            root_cause_statement=(
                "Root cause confirmed." if root_cause_confirmed else "Root cause remains unconfirmed."
            ),
        )

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _require(collection: dict, key: str, kind: str):
        item = collection.get(key)
        if item is None:
            raise KeyError(f"{kind} not found: {key}")
        return item

    @staticmethod
    def _emit(
        incident: Incident,
        event_type: TimelineEventType,
        content: str,
        speaker: Optional[str] = None,
        related_claim_ids: Optional[list[str]] = None,
        related_action_ids: Optional[list[str]] = None,
    ) -> TimelineEvent:
        event = TimelineEvent(
            event_type=event_type,
            content=content,
            speaker=speaker,
            related_claim_ids=related_claim_ids or [],
            related_action_ids=related_action_ids or [],
        )
        incident.timeline.append(event)
        return event

    def _touch(self, incident: Incident) -> None:
        incident.updated_at = utcnow()
        incident.clarity_score = self._compute_clarity_score(incident).score
