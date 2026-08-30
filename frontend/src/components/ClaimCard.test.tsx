import { fireEvent, render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Claim } from '../types/api'
import { ClaimCard } from './ClaimCard'

function makeClaim(overrides: Partial<Claim> = {}): Claim {
  return {
    id: 'c1',
    text: 'I checked the dashboard, payment API is returning 503s',
    normalized_claim: 'Payment API is returning 503 errors',
    type: 'FACT',
    status: 'CONFIRMED',
    confidence: 0.97,
    speaker_id: 'p1',
    timestamp: '2026-08-30T10:00:00Z',
    evidence: 'Speaker checked the dashboard',
    supporting_events: [],
    contradicting_events: [],
    entities: ['payment-api'],
    ...overrides,
  }
}

describe('ClaimCard', () => {
  it('renders a FACT with its confirmed status', () => {
    render(<ClaimCard claim={makeClaim()} speakerName="Alice" />)
    expect(screen.getByText(/Payment API is returning 503 errors/)).toBeInTheDocument()
    expect(screen.getByText('CONFIRMED')).toBeInTheDocument()
    expect(screen.getByText(/FACT/)).toBeInTheDocument()
  })

  it('renders a HYPOTHESIS distinctly from a FACT', () => {
    render(
      <ClaimCard
        claim={makeClaim({
          type: 'HYPOTHESIS',
          status: 'UNCONFIRMED',
          normalized_claim: 'Database connection pool may be exhausted',
          evidence: null,
        })}
      />,
    )
    const card = screen.getByTestId('claim-card')
    expect(card).toHaveAttribute('data-claim-type', 'HYPOTHESIS')
    expect(screen.getByText('UNCONFIRMED')).toBeInTheDocument()
  })

  it('reveals evidence provenance only after clicking "Why?"', () => {
    render(<ClaimCard claim={makeClaim()} speakerName="Alice" />)
    expect(screen.queryByTestId('evidence-panel')).not.toBeInTheDocument()

    fireEvent.click(screen.getByTestId('claim-evidence-toggle'))

    const panel = screen.getByTestId('evidence-panel')
    expect(panel).toBeInTheDocument()
    expect(panel).toHaveTextContent('Alice')
    expect(panel).toHaveTextContent('Speaker checked the dashboard')
  })

  it('shows "Not stated" when a claim has no evidence attached', () => {
    render(<ClaimCard claim={makeClaim({ evidence: null })} />)
    fireEvent.click(screen.getByTestId('claim-evidence-toggle'))
    expect(screen.getByTestId('evidence-panel')).toHaveTextContent('Not stated')
  })
})
