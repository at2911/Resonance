import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { ClarityScoreBreakdown } from '../types/api'
import { ClarityScore } from './ClarityScore'

const clarity: ClarityScoreBreakdown = {
  score: 67,
  confirmed_facts: 1,
  unresolved_hypotheses: 0,
  disputed_claims: 2,
  open_conflicts: 1,
  critical_information_gaps: 1,
  normal_information_gaps: 0,
  open_actions: 1,
  unowned_open_actions: 0,
  stale_actions: 0,
  root_cause_confirmed: false,
}

describe('ClarityScore', () => {
  it('renders the server-computed score verbatim, not a recomputed one', () => {
    render(<ClarityScore clarity={clarity} />)
    expect(screen.getByTestId('clarity-score')).toHaveTextContent('67%')
  })

  it('flags an unresolved root cause distinctly from a confirmed one', () => {
    render(<ClarityScore clarity={clarity} />)
    expect(screen.getByTestId('root-cause-indicator')).toHaveTextContent('unresolved')
  })

  it('shows root cause confirmed when the backend says so', () => {
    render(<ClarityScore clarity={{ ...clarity, root_cause_confirmed: true }} />)
    expect(screen.getByTestId('root-cause-indicator')).toHaveTextContent('confirmed')
  })

  it('renders a placeholder rather than a fabricated number before clarity has loaded', () => {
    render(<ClarityScore clarity={null} />)
    expect(screen.queryByTestId('clarity-score')).not.toBeInTheDocument()
  })
})
