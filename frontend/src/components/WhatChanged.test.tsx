import { render, screen } from '@testing-library/react'
import { describe, expect, it } from 'vitest'
import type { TimelineEvent } from '../types/api'
import { WhatChanged } from './WhatChanged'

function makeEvent(overrides: Partial<TimelineEvent> = {}): TimelineEvent {
  return {
    id: 'e1',
    timestamp: '2026-08-30T10:05:00Z',
    event_type: 'CLAIM_ADDED',
    speaker: null,
    content: 'Payment API is returning 503 errors',
    related_claim_ids: [],
    related_action_ids: [],
    ...overrides,
  }
}

describe('WhatChanged', () => {
  it('shows only events strictly after sinceIso', () => {
    const events = [
      makeEvent({ id: 'e1', timestamp: '2026-08-30T10:00:00Z', content: 'old event' }),
      makeEvent({ id: 'e2', timestamp: '2026-08-30T10:10:00Z', content: 'new event' }),
    ]
    render(<WhatChanged events={events} sinceIso="2026-08-30T10:05:00Z" sinceLabel="since last update" />)
    expect(screen.getByText(/new event/)).toBeInTheDocument()
    expect(screen.queryByText(/old event/)).not.toBeInTheDocument()
  })

  it('shows a count badge matching the number of changed events', () => {
    const events = [
      makeEvent({ id: 'e1', timestamp: '2026-08-30T10:10:00Z' }),
      makeEvent({ id: 'e2', timestamp: '2026-08-30T10:11:00Z' }),
    ]
    render(<WhatChanged events={events} sinceIso="2026-08-30T10:00:00Z" sinceLabel="since last update" />)
    expect(screen.getByTestId('what-changed-count')).toHaveTextContent('2 new')
  })

  it('shows "Nothing new" and no count badge when nothing changed', () => {
    const events = [makeEvent({ id: 'e1', timestamp: '2026-08-30T10:00:00Z' })]
    render(<WhatChanged events={events} sinceIso="2026-08-30T10:05:00Z" sinceLabel="since last update" />)
    expect(screen.getByText('Nothing new.')).toBeInTheDocument()
    expect(screen.queryByTestId('what-changed-count')).not.toBeInTheDocument()
  })

  it('renders the sinceLabel so the reader knows what the recap is relative to', () => {
    render(<WhatChanged events={[]} sinceIso="2026-08-30T10:00:00Z" sinceLabel="since incident was created" />)
    expect(screen.getByText('since incident was created')).toBeInTheDocument()
  })
})
