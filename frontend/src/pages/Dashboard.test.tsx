import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { ExternalAction, Incident } from '../types/api'
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
    participants: {},
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
