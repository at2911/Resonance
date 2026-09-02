import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { Risk } from '../types/api'
import { RiskCard } from './RiskCard'

function makeRisk(overrides: Partial<Risk> = {}): Risk {
  return {
    id: 'r1',
    description: 'Rollback may cause data inconsistency for in-flight transactions',
    severity: 'HIGH',
    confidence: 0.6,
    mitigation: null,
    status: 'OPEN',
    ...overrides,
  }
}

describe('RiskCard', () => {
  it('renders the description, severity, and status', () => {
    render(<RiskCard risk={makeRisk()} />)
    expect(screen.getByText(/Rollback may cause data inconsistency/)).toBeInTheDocument()
    expect(screen.getByText(/HIGH/)).toBeInTheDocument()
    expect(screen.getByText('OPEN')).toBeInTheDocument()
  })

  it('shows confidence as a percentage', () => {
    render(<RiskCard risk={makeRisk({ confidence: 0.6 })} />)
    expect(screen.getByText(/confidence 60%/)).toBeInTheDocument()
  })

  it('shows mitigation when present, omits it when not stated', () => {
    const { rerender } = render(<RiskCard risk={makeRisk({ mitigation: 'Snapshot taken before rollback' })} />)
    expect(screen.getByText(/Mitigation: Snapshot taken before rollback/)).toBeInTheDocument()

    rerender(<RiskCard risk={makeRisk({ mitigation: null })} />)
    expect(screen.queryByText(/Mitigation:/)).not.toBeInTheDocument()
  })

  it('renders a distinct status for a mitigated risk rather than hiding it', () => {
    render(<RiskCard risk={makeRisk({ status: 'MITIGATED' })} />)
    expect(screen.getByText('MITIGATED')).toBeInTheDocument()
  })
})
