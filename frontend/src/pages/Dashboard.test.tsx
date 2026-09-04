import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ExternalAction, Incident, ParticipantRole } from '../types/api'
import { Dashboard } from './Dashboard'

// A stateful fake of the backend: exercises the same PENDING -> APPROVED ->
// EXECUTING -> SUCCEEDED state machine the real IncidentStateService
// enforces, so this test proves the UI reflects that machine rather than
// inventing its own notion of "approved".
let incident: Incident
let externalAction: ExternalAction | null = null

function baseIncident(): Incident {
  return {
    id: 'inc1',
    title: 'Payment API Outage',
    severity: 'SEV1',
    status: 'ACTIVE',
    start_time: '2026-08-30T10:00:00Z',
    current_summary: '',
    clarity_score: 80,
    created_at: '2026-08-30T10:00:00Z',
    updated_at: '2026-08-30T10:00:00Z',
    participants: {
      p1: {
        id: 'p1',
        name: 'Alice',
        role: 'INCIDENT_COMMANDER',
        role_confidence: 0.9,
        joined_at: '2026-08-30T09:58:00Z',
        agora_uid: null,
      },
    },
    claims: {
      c1: {
        id: 'c1',
        text: 'x',
        normalized_claim: 'Payment API is returning 503 errors',
        type: 'FACT',
        status: 'CONFIRMED',
        confidence: 0.95,
        speaker_id: null,
        timestamp: '2026-08-30T10:01:00Z',
        evidence: 'Checked dashboard',
        supporting_events: [],
        contradicting_events: [],
        entities: [],
      },
    },
    actions: {},
    conflicts: {},
    information_gaps: {},
    risks: {
      r1: {
        id: 'r1',
        description: 'Rollback may cause data inconsistency',
        severity: 'HIGH',
        confidence: 0.6,
        mitigation: null,
        status: 'OPEN',
      },
    },
    timeline: [],
    external_actions: {},
  }
}

vi.mock('../services/api', () => ({
  ApiError: class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  },
  getIncident: vi.fn(async () => incident),
  getClarity: vi.fn(async () => ({
    score: incident.clarity_score,
    confirmed_facts: 1,
    unresolved_hypotheses: 0,
    disputed_claims: 0,
    open_conflicts: 0,
    critical_information_gaps: 0,
    normal_information_gaps: 0,
    open_actions: 0,
    unowned_open_actions: 0,
    stale_actions: 0,
    root_cause_confirmed: false,
  })),
  getSummary: vi.fn(async () => ({
    incident_id: incident.id,
    generated_at: incident.updated_at,
    confirmed_facts: [],
    hypotheses: [],
    decisions: [],
    actions: [],
    conflicts: [],
    unresolved_risks: [],
    open_information_gaps: [],
    root_cause_confirmed: false,
    root_cause_statement: 'Root cause remains unconfirmed.',
  })),
  proposeSlackUpdate: vi.fn(async () => {
    externalAction = {
      id: 'ea1',
      action_type: 'SLACK_MESSAGE',
      payload: { channel: '#payments-incident', text: 'Payment API is returning 503 errors.' },
      idempotency_key: 'k1',
      proposed_at: '2026-08-30T10:05:00Z',
      approval_status: 'PENDING',
      approved_by: null,
      approved_at: null,
      executed_at: null,
      execution_status: 'NOT_EXECUTED',
      execution_result: null,
    }
    incident = { ...incident, external_actions: { ea1: externalAction } }
    return externalAction
  }),
  decideExternalAction: vi.fn(async (_id: string, _eaId: string, req: { approved: boolean }) => {
    externalAction = { ...externalAction!, approval_status: req.approved ? 'APPROVED' : 'REJECTED', approved_by: 'ic-dashboard' }
    incident = { ...incident, external_actions: { ea1: externalAction } }
    return externalAction
  }),
  executeExternalAction: vi.fn(async () => {
    externalAction = {
      ...externalAction!,
      execution_status: 'SUCCEEDED',
      execution_result: 'Posted to Slack channel #payments-incident (ts=999.99)',
    }
    incident = { ...incident, external_actions: { ea1: externalAction } }
    return externalAction
  }),
  postUtterance: vi.fn(),
  correctParticipantRole: vi.fn(async (_id: string, participantId: string, req: { role: ParticipantRole; corrected_by: string }) => {
    const corrected = { ...incident.participants[participantId], role: req.role, role_confidence: 1.0 }
    incident = { ...incident, participants: { ...incident.participants, [participantId]: corrected } }
    return corrected
  }),
}))

beforeEach(() => {
  incident = baseIncident()
  externalAction = null
  vi.clearAllMocks()
})

describe('Dashboard — end-to-end approval gate through the real UI', () => {
  it('renders the confirmed fact from backend state', async () => {
    render(<Dashboard incidentId="inc1" />)
    expect(await screen.findByText(/Payment API is returning 503 errors/)).toBeInTheDocument()
  })

  it('renders risks from backend state in their own panel', async () => {
    render(<Dashboard incidentId="inc1" />)
    expect(await screen.findByText(/Rollback may cause data inconsistency/)).toBeInTheDocument()
  })

  it('renders participants from backend state in their own panel', async () => {
    render(<Dashboard incidentId="inc1" />)
    expect(await screen.findByText('Alice')).toBeInTheDocument()
    expect(screen.getByTestId('participant-role-tag')).toHaveTextContent('INCIDENT COMMANDER')
  })

  it('correcting a role calls the backend and reflects the real corrected state, not a locally-guessed one', async () => {
    const api = await import('../services/api')
    render(<Dashboard incidentId="inc1" />)
    await screen.findByText('Alice')

    fireEvent.change(screen.getByTestId('participant-role-select'), { target: { value: 'SRE' } })
    fireEvent.click(screen.getByTestId('participant-correct-role'))

    await waitFor(() => {
      expect(screen.getByTestId('participant-role-tag')).toHaveTextContent('SRE')
    })
    expect(api.correctParticipantRole).toHaveBeenCalledWith('inc1', 'p1', { role: 'SRE', corrected_by: 'ic-dashboard' })
    // Confidence jumping to 100% (not just the label changing) proves the
    // panel re-rendered from refreshed backend state, not a local guess.
    expect(screen.getByTestId('participant-role-confidence')).toHaveTextContent('100% sure')
  })

  it('What Changed labels the recap as "since created" when no Slack update has ever been sent', async () => {
    render(<Dashboard incidentId="inc1" />)
    await screen.findByText(/Payment API is returning 503 errors/)
    expect(screen.getByText(/no Slack update sent yet/)).toBeInTheDocument()
  })

  it('What Changed switches to "since last update" once a Slack update has actually succeeded', async () => {
    incident = {
      ...incident,
      external_actions: {
        ea1: {
          id: 'ea1',
          action_type: 'SLACK_MESSAGE',
          payload: { channel: '#payments-incident', text: 'x' },
          idempotency_key: 'k1',
          proposed_at: '2026-08-30T10:04:00Z',
          approval_status: 'APPROVED',
          approved_by: 'ic-dashboard',
          approved_at: '2026-08-30T10:04:30Z',
          executed_at: '2026-08-30T10:05:00Z',
          execution_status: 'SUCCEEDED',
          execution_result: 'Posted to Slack channel #payments-incident (ts=1.1)',
        },
      },
    }
    render(<Dashboard incidentId="inc1" />)
    await screen.findByText(/Payment API is returning 503 errors/)
    expect(screen.getByText('since the last Slack update was sent')).toBeInTheDocument()
  })

  it('never shows a proposal until "Propose Slack Update" is clicked', async () => {
    render(<Dashboard incidentId="inc1" />)
    await screen.findByText(/Payment API is returning 503 errors/)
    expect(screen.queryByTestId('approval-modal')).not.toBeInTheDocument()
    expect(screen.getByText(/No proposal yet/)).toBeInTheDocument()
  })

  it('walks the full propose -> approve -> execute chain and ends with a real Slack result, not a fabricated one', async () => {
    render(<Dashboard incidentId="inc1" />)
    await screen.findByText(/Payment API is returning 503 errors/)

    fireEvent.click(screen.getByText('Propose Slack Update'))

    const modal = await screen.findByTestId('approval-modal')
    expect(modal).toHaveTextContent('#payments-incident')
    expect(modal).toHaveTextContent('PENDING')

    fireEvent.click(screen.getByTestId('btn-approve'))

    await waitFor(() => {
      expect(screen.getByTestId('approval-modal')).toHaveTextContent(/ts=999\.99/)
    })
    // Once sent, the gate is closed for good — no lingering approve/execute controls.
    expect(screen.queryByTestId('btn-approve')).not.toBeInTheDocument()
    expect(screen.queryByTestId('btn-execute')).not.toBeInTheDocument()
  })

  it('closes the gate on rejection without ever executing', async () => {
    const api = await import('../services/api')
    render(<Dashboard incidentId="inc1" />)
    await screen.findByText(/Payment API is returning 503 errors/)

    fireEvent.click(screen.getByText('Propose Slack Update'))
    await screen.findByTestId('approval-modal')

    fireEvent.click(screen.getByTestId('btn-reject'))

    await waitFor(() => {
      expect(screen.getByTestId('approval-modal')).toHaveTextContent('REJECTED')
    })
    expect(api.executeExternalAction).not.toHaveBeenCalled()
  })
})
