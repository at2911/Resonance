/**
 * Thin, typed wrapper over the backend HTTP API. Every function here maps
 * to an existing route — see the file/line reference in each doc comment.
 * Nothing is invented; if a route doesn't exist in the backend, it isn't
 * here either.
 */
import type {
  AddActionRequest,
  AddClaimRequest,
  AddConflictRequest,
  AddInformationGapRequest,
  Action,
  AgoraSession,
  Claim,
  ClarityScoreBreakdown,
  Conflict,
  CorrectParticipantRoleRequest,
  CreateIncidentRequest,
  DecideExternalActionRequest,
  DemoStatus,
  ExternalAction,
  ExtractionApplyResult,
  FinalSummary,
  Incident,
  InformationGap,
  Participant,
  SpeakSummaryResponse,
  StartSessionResponse,
} from '../types/api'

export const API_BASE_URL = (import.meta.env.VITE_API_BASE_URL as string | undefined) ?? 'http://127.0.0.1:8000'

export class ApiError extends Error {
  status: number
  constructor(status: number, message: string) {
    super(message)
    this.status = status
  }
}

async function request<T>(method: string, path: string, body?: unknown): Promise<T> {
  const res = await fetch(`${API_BASE_URL}${path}`, {
    method,
    headers: body !== undefined ? { 'Content-Type': 'application/json' } : undefined,
    body: body !== undefined ? JSON.stringify(body) : undefined,
  })
  let data: unknown = null
  try {
    data = await res.json()
  } catch {
    // some endpoints (e.g. health) may not return a body
  }
  if (!res.ok) {
    const detail =
      data && typeof data === 'object' && 'detail' in data
        ? String((data as { detail: unknown }).detail)
        : res.statusText
    throw new ApiError(res.status, detail)
  }
  return data as T
}

// backend/app/api/incidents.py
export const createIncident = (req: CreateIncidentRequest) => request<Incident>('POST', '/incidents', req)
export const listIncidents = () => request<Incident[]>('GET', '/incidents')
export const getIncident = (id: string) => request<Incident>('GET', `/incidents/${id}`)
export const getClarity = (id: string) => request<ClarityScoreBreakdown>('GET', `/incidents/${id}/clarity`)
export const getSummary = (id: string) => request<FinalSummary>('GET', `/incidents/${id}/summary`)

export const addClaim = (id: string, req: AddClaimRequest) =>
  request<Claim>('POST', `/incidents/${id}/claims`, req)

export const addAction = (id: string, req: AddActionRequest) =>
  request<Action>('POST', `/incidents/${id}/actions`, req)

export const updateActionStatus = (id: string, actionId: string, status: string, completion_evidence?: string) =>
  request<Action>('PATCH', `/incidents/${id}/actions/${actionId}`, { status, completion_evidence })

export const addConflict = (id: string, req: AddConflictRequest) =>
  request<Conflict>('POST', `/incidents/${id}/conflicts`, req)

export const correctParticipantRole = (id: string, participantId: string, req: CorrectParticipantRoleRequest) =>
  request<Participant>('POST', `/incidents/${id}/participants/${participantId}/correct-role`, req)

export const resolveConflict = (id: string, conflictId: string, resolution_evidence: string) =>
  request<Conflict>('POST', `/incidents/${id}/conflicts/${conflictId}/resolve`, { resolution_evidence })

export const addGap = (id: string, req: AddInformationGapRequest) =>
  request<InformationGap>('POST', `/incidents/${id}/gaps`, req)

export const resolveGap = (id: string, gapId: string) =>
  request<InformationGap>('POST', `/incidents/${id}/gaps/${gapId}/resolve`)

export const decideExternalAction = (id: string, externalActionId: string, req: DecideExternalActionRequest) =>
  request<ExternalAction>('POST', `/incidents/${id}/external-actions/${externalActionId}/decision`, req)

// backend/app/api/conversation.py
export const postUtterance = (id: string, speaker_name: string, text: string, speaker_id?: string | null) =>
  request<ExtractionApplyResult>('POST', `/incidents/${id}/utterances`, { speaker_id, speaker_name, text })

// backend/app/api/slack.py
export const proposeSlackUpdate = (id: string) =>
  request<ExternalAction>('POST', `/incidents/${id}/slack-updates`)

export const executeExternalAction = (id: string, externalActionId: string) =>
  request<ExternalAction>('POST', `/incidents/${id}/external-actions/${externalActionId}/execute`)

// backend/app/api/demo.py
export const startDemo = () => request<DemoStatus>('POST', '/demo/start')
export const pauseDemo = () => request<DemoStatus>('POST', '/demo/pause')
export const resumeDemo = () => request<DemoStatus>('POST', '/demo/resume')
export const resetDemo = () => request<DemoStatus>('POST', '/demo/reset')
export const getDemoStatus = () => request<DemoStatus>('GET', '/demo/status')

// backend/app/api/agora.py
export const startAgoraSession = (incidentId: string) =>
  request<StartSessionResponse>('POST', `/incidents/${incidentId}/agora/session`, { agent_uid: 0 })

export const endAgoraSession = (incidentId: string, sessionId: string) =>
  request<AgoraSession>('POST', `/incidents/${incidentId}/agora/session/${sessionId}/end`)

export const speakAgoraSummary = (incidentId: string, sessionId: string) =>
  request<SpeakSummaryResponse>('POST', `/incidents/${incidentId}/agora/session/${sessionId}/speak-summary`)
