"""API request DTOs.

These are intentionally separate from the domain models in app/models. A
request DTO is untrusted input; it is validated here and then passed through
explicit IncidentStateService methods that enforce the real invariants
(evidence required to confirm/resolve, valid status transitions, etc). No
DTO is ever merged directly into an Incident.
"""

from __future__ import annotations

from typing import Optional

from pydantic import BaseModel, Field

from app.models.enums import (
    ActionPriority,
    ActionStatus,
    ClaimStatus,
    ClaimType,
    ConflictType,
    ExternalActionType,
    GapImportance,
    IncidentSeverity,
    ParticipantRole,
    RiskSeverity,
)


class CreateIncidentRequest(BaseModel):
    title: str
    severity: IncidentSeverity = IncidentSeverity.UNKNOWN


class AddParticipantRequest(BaseModel):
    name: str
    role: ParticipantRole = ParticipantRole.UNKNOWN
    role_confidence: float = Field(default=0.0, ge=0.0, le=1.0)


class CorrectParticipantRoleRequest(BaseModel):
    role: ParticipantRole
    corrected_by: Optional[str] = None
    """Free-text identifier of whoever made the correction (e.g. the
    dashboard's IC name) — recorded in the timeline note, not enforced as
    a real identity/auth concept anywhere else in this MVP."""


class AddClaimRequest(BaseModel):
    text: str
    normalized_claim: str
    type: ClaimType
    status: ClaimStatus
    confidence: float = Field(ge=0.0, le=1.0)
    speaker_id: Optional[str] = None
    evidence: Optional[str] = None
    entities: list[str] = Field(default_factory=list)


class UpdateClaimStatusRequest(BaseModel):
    status: ClaimStatus
    evidence: Optional[str] = None


class AddActionRequest(BaseModel):
    description: str
    owner: Optional[str] = None
    owner_confidence: float = Field(default=0.0, ge=0.0, le=1.0)
    priority: ActionPriority = ActionPriority.NORMAL
    source_event_id: Optional[str] = None
    dependencies: list[str] = Field(default_factory=list)


class UpdateActionStatusRequest(BaseModel):
    status: ActionStatus
    completion_evidence: Optional[str] = None


class AddConflictRequest(BaseModel):
    claim_a: str
    claim_b: str
    conflict_type: ConflictType
    explanation: str


class ResolveConflictRequest(BaseModel):
    resolution_evidence: str


class AddInformationGapRequest(BaseModel):
    description: str
    importance: GapImportance
    related_claims: list[str] = Field(default_factory=list)


class AddRiskRequest(BaseModel):
    description: str
    severity: RiskSeverity
    confidence: float = Field(ge=0.0, le=1.0)
    mitigation: Optional[str] = None


class ProposeExternalActionRequest(BaseModel):
    action_type: ExternalActionType
    payload: dict


class DecideExternalActionRequest(BaseModel):
    approved: bool
    approved_by: str
