"""Canonical enums for incident state.

These are the closed vocabularies the entire system reasons over. The LLM
extraction layer is constrained to emit only these values (see
app/services/extraction) — free-form status strings are never accepted into
the IncidentState.
"""

from enum import Enum


class ClaimType(str, Enum):
    FACT = "FACT"
    HYPOTHESIS = "HYPOTHESIS"
    DECISION = "DECISION"
    ACTION = "ACTION"
    QUESTION = "QUESTION"
    RISK = "RISK"
    UPDATE = "UPDATE"


class ClaimStatus(str, Enum):
    CONFIRMED = "CONFIRMED"
    PROBABLE = "PROBABLE"
    UNCONFIRMED = "UNCONFIRMED"
    DISPUTED = "DISPUTED"
    RESOLVED = "RESOLVED"
    SUPERSEDED = "SUPERSEDED"


class ActionStatus(str, Enum):
    OPEN = "OPEN"
    IN_PROGRESS = "IN_PROGRESS"
    BLOCKED = "BLOCKED"
    COMPLETED = "COMPLETED"
    CANCELLED = "CANCELLED"


class ActionPriority(str, Enum):
    LOW = "LOW"
    NORMAL = "NORMAL"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class ConflictType(str, Enum):
    DATABASE_HEALTH = "DATABASE_HEALTH"
    NETWORK_HEALTH = "NETWORK_HEALTH"
    ROOT_CAUSE = "ROOT_CAUSE"
    OWNERSHIP = "OWNERSHIP"
    STATUS = "STATUS"
    TIMELINE = "TIMELINE"
    OTHER = "OTHER"


class ConflictStatus(str, Enum):
    OPEN = "OPEN"
    ACKNOWLEDGED = "ACKNOWLEDGED"
    RESOLVED = "RESOLVED"


class GapImportance(str, Enum):
    CRITICAL = "CRITICAL"
    NORMAL = "NORMAL"


class GapStatus(str, Enum):
    OPEN = "OPEN"
    RESOLVED = "RESOLVED"


class RiskSeverity(str, Enum):
    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskStatus(str, Enum):
    OPEN = "OPEN"
    MITIGATED = "MITIGATED"
    ACCEPTED = "ACCEPTED"
    RESOLVED = "RESOLVED"


class IncidentSeverity(str, Enum):
    SEV1 = "SEV1"
    SEV2 = "SEV2"
    SEV3 = "SEV3"
    SEV4 = "SEV4"
    UNKNOWN = "UNKNOWN"


class IncidentStatus(str, Enum):
    ACTIVE = "ACTIVE"
    MITIGATING = "MITIGATING"
    MONITORING = "MONITORING"
    RESOLVED = "RESOLVED"
    CLOSED = "CLOSED"


class ParticipantRole(str, Enum):
    INCIDENT_COMMANDER = "INCIDENT_COMMANDER"
    BACKEND_ENGINEER = "BACKEND_ENGINEER"
    SRE = "SRE"
    SUPPORT = "SUPPORT"
    BUSINESS_STAKEHOLDER = "BUSINESS_STAKEHOLDER"
    UNKNOWN = "UNKNOWN"


class TimelineEventType(str, Enum):
    INCIDENT_DETECTED = "INCIDENT_DETECTED"
    CLAIM_ADDED = "CLAIM_ADDED"
    CLAIM_UPDATED = "CLAIM_UPDATED"
    CONFLICT_DETECTED = "CONFLICT_DETECTED"
    CONFLICT_RESOLVED = "CONFLICT_RESOLVED"
    GAP_DETECTED = "GAP_DETECTED"
    GAP_RESOLVED = "GAP_RESOLVED"
    ACTION_ASSIGNED = "ACTION_ASSIGNED"
    ACTION_UPDATED = "ACTION_UPDATED"
    DECISION_RECORDED = "DECISION_RECORDED"
    HUMAN_APPROVAL = "HUMAN_APPROVAL"
    EXTERNAL_ACTION_PROPOSED = "EXTERNAL_ACTION_PROPOSED"
    EXTERNAL_ACTION_EXECUTED = "EXTERNAL_ACTION_EXECUTED"
    EXTERNAL_ACTION_FAILED = "EXTERNAL_ACTION_FAILED"
    RISK_IDENTIFIED = "RISK_IDENTIFIED"
    SUMMARY_GENERATED = "SUMMARY_GENERATED"
    PARTICIPANT_JOINED = "PARTICIPANT_JOINED"


class ApprovalStatus(str, Enum):
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class ExternalActionType(str, Enum):
    SLACK_MESSAGE = "SLACK_MESSAGE"


class ExecutionStatus(str, Enum):
    NOT_EXECUTED = "NOT_EXECUTED"
    EXECUTING = "EXECUTING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
