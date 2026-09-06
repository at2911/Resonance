import { act, fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { Incident } from '../types/api'
import { IncidentHeader } from './IncidentHeader'

function makeIncident(): Incident {
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
    claims: {},
    actions: {},
    conflicts: {},
    information_gaps: {},
    risks: {},
    timeline: [],
    external_actions: {},
  }
}

beforeEach(() => {
  Object.assign(navigator, { clipboard: { writeText: vi.fn().mockResolvedValue(undefined) } })
})

describe('IncidentHeader — Home button', () => {
  it('is not shown when onGoHome is not provided', () => {
    render(<IncidentHeader incident={makeIncident()} />)
    expect(screen.queryByTestId('btn-go-home')).not.toBeInTheDocument()
  })

  it('calls onGoHome when clicked', () => {
    const onGoHome = vi.fn()
    render(<IncidentHeader incident={makeIncident()} onGoHome={onGoHome} />)

    fireEvent.click(screen.getByTestId('btn-go-home'))

    expect(onGoHome).toHaveBeenCalledTimes(1)
  })
})

describe('IncidentHeader — Copy Team Link', () => {
  it('copies the current page URL so a teammate lands on this exact incident', async () => {
    render(<IncidentHeader incident={makeIncident()} />)

    fireEvent.click(screen.getByTestId('btn-copy-share-link'))

    await waitFor(() => {
      expect(navigator.clipboard.writeText).toHaveBeenCalledWith(window.location.href)
    })
    expect(screen.getByTestId('btn-copy-share-link')).toHaveTextContent('Copied')
  })

  it('reverts back to the normal label after copying, so it can be clicked again', async () => {
    vi.useFakeTimers()
    render(<IncidentHeader incident={makeIncident()} />)

    fireEvent.click(screen.getByTestId('btn-copy-share-link'))
    await vi.waitFor(() => expect(screen.getByTestId('btn-copy-share-link')).toHaveTextContent('Copied'))

    act(() => {
      vi.advanceTimersByTime(2100)
    })
    expect(screen.getByTestId('btn-copy-share-link')).toHaveTextContent('Copy Team Link')
    vi.useRealTimers()
  })
})
