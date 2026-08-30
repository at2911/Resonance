/**
 * Types mirror backend/app/models/{enums,incident}.py and
 * backend/app/schemas/*.py field-for-field. FastAPI serializes Pydantic
 * models with their original snake_case field names — nothing here is
 * renamed/transformed, so a diff against the backend models is always a
 * direct comparison.
 */

export type ClaimType = 'FACT' | 'HYPOTHESIS' | 'DECISION' | 'ACTION' | 'QUESTION' | 'RISK' | 'UPDATE'

export type ClaimStatus = 'CONFIRMED' | 'PROBABLE' | 'UNCONFIRMED' | 'DISPUTED' | 'RESOLVED' | 'SUPERSEDED'

export type ActionStatus = 'OPEN' | 'IN_PROGRESS' | 'BLOCKED' | 'COMPLETED' | 'CANCELLED'

export type ActionPriority = 'LOW' | 'NORMAL' | 'HIGH' | 'CRITICAL'

export type ConflictType =
  | 'DATABASE_HEALTH'
  | 'NETWORK_HEALTH'
  | 'ROOT_CAUSE'
  | 'OWNERSHIP'
  | 'STATUS'
  | 'TIMELINE'
  | 'OTHER'

export type ConflictStatus = 'OPEN' | 'ACKNOWLEDGED' | 'RESOLVED'

export type GapImportance = 'CRITICAL' | 'NORMAL'

export type GapStatus = 'OPEN' | 'RESOLVED'

export type RiskSeverity = 'LOW' | 'MEDIUM' | 'HIGH' | 'CRITICAL'

export type RiskStatus = 'OPEN' | 'MITIGATED' | 'ACCEPTED' | 'RESOLVED'

export type IncidentSeverity = 'SEV1' | 'SEV2' | 'SEV3' | 'SEV4' | 'UNKNOWN'

export type IncidentStatus = 'ACTIVE' | 'MITIGATING' | 'MONITORING' | 'RESOLVED' | 'CLOSED'

export type ParticipantRole =
  | 'INCIDENT_COMMANDER'
  | 'BACKEND_ENGINEER'
  | 'SRE'
  | 'SUPPORT'
  | 'BUSINESS_STAKEHOLDER'
  | 'UNKNOWN'

export type TimelineEventType =
  | 'INCIDENT_DETECTED'
  | 'CLAIM_ADDED'
  | 'CLAIM_UPDATED'
  | 'CONFLICT_DETECTED'
  | 'CONFLICT_RESOLVED'
  | 'GAP_DETECTED'
  | 'GAP_RESOLVED'
  | 'ACTION_ASSIGNED'
  | 'ACTION_UPDATED'
  | 'DECISION_RECORDED'
  | 'HUMAN_APPROVAL'
  | 'EXTERNAL_ACTION_PROPOSED'
  | 'EXTERNAL_ACTION_EXECUTED'
  | 'EXTERNAL_ACTION_FAILED'
  | 'RISK_IDENTIFIED'
  | 'SUMMARY_GENERATED'
  | 'PARTICIPANT_JOINED'
  | 'AGORA_SESSION_STARTED'
  | 'AGORA_SESSION_ENDED'
  | 'AGORA_AGENT_JOINED'
  | 'AGORA_AGENT_LEFT'
  | 'AGORA_AGENT_ERROR'

export type ApprovalStatus = 'PENDING' | 'APPROVED' | 'REJECTED'

export type ExternalActionType = 'SLACK_MESSAGE'

export type ExecutionStatus = 'NOT_EXECUTED' | 'EXECUTING' | 'SUCCEEDED' | 'FAILED'

export interface Participant {
  id: string
  name: string
  role: ParticipantRole
  role_confidence: number
  joined_at: string
  agora_uid: string | null
}

export interface Claim {
  id: string
  text: string
  normalized_claim: string
  type: ClaimType
  status: ClaimStatus
  confidence: number
  speaker_id: string | null
  timestamp: string
  evidence: string | null
  supporting_events: string[]
  contradicting_events: string[]
  entities: string[]
}

export interface Action {
  id: string
  description: string
  owner: string | null
  owner_confidence: number
  status: ActionStatus
  priority: ActionPriority
  created_at: string
  updated_at: string
  due_at: string | null
  dependencies: string[]
  source_event_id: string | null
  completion_evidence: string | null
}

export interface Conflict {
  id: string
  claim_a: string
  claim_b: string
  conflict_type: ConflictType
  detected_at: string
  status: ConflictStatus
  explanation: string
  resolution_evidence: string | null
}

export interface InformationGap {
  id: string
  description: string
  importance: GapImportance
  detected_at: string
  related_claims: string[]
  status: GapStatus
  dimension: string | null
}

export interface Risk {
  id: string
  description: string
  severity: RiskSeverity
  confidence: number
  mitigation: string | null
  status: RiskStatus
}

export interface TimelineEvent {
  id: string
  timestamp: string
  event_type: TimelineEventType
  speaker: string | null
  content: string
  related_claim_ids: string[]
  related_action_ids: string[]
}

export interface ExternalAction {
  id: string
  action_type: ExternalActionType
  payload: { channel: string; text: string } & Record<string, unknown>
  idempotency_key: string
  proposed_at: string
  approval_status: ApprovalStatus
  approved_by: string | null
  approved_at: string | null
  executed_at: string | null
  execution_status: ExecutionStatus
  execution_result: string | null
}

export interface ClarityScoreBreakdown {
  score: number
  confirmed_facts: number
  unresolved_hypotheses: number
  disputed_claims: number
  open_conflicts: number
  critical_information_gaps: number
  normal_information_gaps: number
  open_actions: number
  unowned_open_actions: number
  stale_actions: number
  root_cause_confirmed: boolean
}

export interface FinalSummary {
  incident_id: string
  generated_at: string
  confirmed_facts: Claim[]
  hypotheses: Claim[]
  decisions: Claim[]
  actions: Action[]
  conflicts: Conflict[]
  unresolved_risks: Risk[]
  open_information_gaps: InformationGap[]
  root_cause_confirmed: boolean
  root_cause_statement: string
}

export interface Incident {
  id: string
  title: string
  severity: IncidentSeverity
  status: IncidentStatus
  start_time: string
  current_summary: string
  clarity_score: number
  created_at: string
  updated_at: string
  participants: Record<string, Participant>
  claims: Record<string, Claim>
  actions: Record<string, Action>
  conflicts: Record<string, Conflict>
  information_gaps: Record<string, InformationGap>
  risks: Record<string, Risk>
  timeline: TimelineEvent[]
  external_actions: Record<string, ExternalAction>
}

export interface ExtractionApplyResult {
  claims: Claim[]
  actions: Action[]
  risks: Risk[]
  conflicts: Conflict[]
  completed_actions: Action[]
  gaps_created: InformationGap[]
  gaps_resolved: InformationGap[]
  role_updated: boolean
}

// ---- Request bodies (backend/app/schemas/*.py) ----

export interface CreateIncidentRequest {
  title: string
  severity?: IncidentSeverity
}

export interface AddClaimRequest {
  text: string
  normalized_claim: string
  type: ClaimType
  status: ClaimStatus
  confidence: number
  speaker_id?: string | null
  evidence?: string | null
  entities?: string[]
}

export interface AddActionRequest {
  description: string
  owner?: string | null
  owner_confidence?: number
  priority?: ActionPriority
  source_event_id?: string | null
  dependencies?: string[]
}

export interface AddConflictRequest {
  claim_a: string
  claim_b: string
  conflict_type: ConflictType
  explanation: string
}

export interface AddInformationGapRequest {
  description: string
  importance: GapImportance
  related_claims?: string[]
}

export interface AddUtteranceRequest {
  speaker_id?: string | null
  speaker_name: string
  text: string
}

export interface DecideExternalActionRequest {
  approved: boolean
  approved_by: string
}

// ---- Demo Mode (backend/app/services/demo/schemas.py) ----

export type DemoStatusValue = 'IDLE' | 'PLAYING' | 'PAUSED' | 'COMPLETED'

export interface DemoStatus {
  status: DemoStatusValue
  incident_id: string | null
  current_step: number
  total_steps: number
  last_step_description: string | null
}
