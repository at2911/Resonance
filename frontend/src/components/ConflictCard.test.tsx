import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Claim, Conflict } from '../types/api'
import { ConflictCard } from './ConflictCard'

const claimA: Claim = {
  id: 'a',
  text: 'x',
  normalized_claim: 'Database instability',
  type: 'HYPOTHESIS',
  status: 'DISPUTED',
  confidence: 0.5,
  speaker_id: null,
  timestamp: '2026-08-30T10:00:00Z',
  evidence: null,
  supporting_events: [],
  contradicting_events: ['conf1'],
  entities: ['database'],
}
const claimB: Claim = { ...claimA, id: 'b', normalized_claim: 'Database appears healthy' }

const conflict: Conflict = {
  id: 'conf1',
  claim_a: 'a',
  claim_b: 'b',
  conflict_type: 'DATABASE_HEALTH',
  detected_at: '2026-08-30T10:01:00Z',
  status: 'OPEN',
  explanation: "Alice reports DB instability while Bob reports the DB is healthy — both can't be true",
  resolution_evidence: null,
}

describe('ConflictCard', () => {
  it('surfaces the conflict type and explanation', () => {
    render(<ConflictCard conflict={conflict} claimA={claimA} claimB={claimB} />)
    expect(screen.getByText(/DATABASE HEALTH/)).toBeInTheDocument()
    expect(screen.getByText(/both can't be true/)).toBeInTheDocument()
  })

  it('preserves and shows both conflicting claims rather than picking one', () => {
    render(<ConflictCard conflict={conflict} claimA={claimA} claimB={claimB} />)
    expect(screen.getByText(/Database instability/)).toBeInTheDocument()
    expect(screen.getByText(/Database appears healthy/)).toBeInTheDocument()
  })

  it('still renders sensibly if a referenced claim is missing from the current page of state', () => {
    render(<ConflictCard conflict={conflict} />)
    expect(screen.getByText(/DATABASE HEALTH/)).toBeInTheDocument()
  })
})
