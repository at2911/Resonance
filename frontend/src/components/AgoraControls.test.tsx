import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { StartSessionResponse } from '../types/api'
import { AgoraControls } from './AgoraControls'

vi.mock('../services/api', () => ({
  ApiError: class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  },
  startAgoraSession: vi.fn(),
  endAgoraSession: vi.fn(),
}))

function session(): StartSessionResponse {
  return {
    session: {
      id: 'sess-1',
      incident_id: 'inc-1',
      channel: 'incident-abc123',
      agent_uid: 0,
      agent_id: 'agent-xyz',
      status: 'ACTIVE',
      created_at: '2026-08-31T10:00:00Z',
      ended_at: null,
    },
    rtc_token: 'fake-rtc-token-value',
  }
}

beforeEach(() => {
  vi.clearAllMocks()
})

describe('AgoraControls', () => {
  it('shows the Start button and no session details before a session exists', () => {
    render(<AgoraControls incidentId="inc-1" />)
    expect(screen.getByTestId('btn-agora-start')).toBeInTheDocument()
    expect(screen.queryByTestId('agora-session-status')).not.toBeInTheDocument()
  })

  it('starting a session shows the real channel, status, and RTC token returned by the backend', async () => {
    const api = await import('../services/api')
    vi.mocked(api.startAgoraSession).mockResolvedValue(session())

    render(<AgoraControls incidentId="inc-1" />)
    fireEvent.click(screen.getByTestId('btn-agora-start'))

    await waitFor(() => {
      expect(screen.getByTestId('agora-session-status')).toHaveTextContent('ACTIVE')
    })
    expect(screen.getByTestId('agora-channel')).toHaveTextContent('incident-abc123')
    expect(screen.getByTestId('agora-rtc-token')).toHaveValue('fake-rtc-token-value')
    expect(screen.queryByTestId('btn-agora-start')).not.toBeInTheDocument()
  })

  it('surfaces a real backend error (e.g. Gemini not configured) instead of pretending to start', async () => {
    const api = await import('../services/api')
    const { ApiError } = api
    vi.mocked(api.startAgoraSession).mockRejectedValue(
      new ApiError(503, 'Agora agent unavailable: GEMINI_API_KEY is not configured'),
    )

    render(<AgoraControls incidentId="inc-1" />)
    fireEvent.click(screen.getByTestId('btn-agora-start'))

    await waitFor(() => {
      expect(screen.getByText(/GEMINI_API_KEY is not configured/)).toBeInTheDocument()
    })
    expect(screen.getByTestId('btn-agora-start')).toBeInTheDocument()
  })

  it('ending a session calls the backend and returns to the Start state', async () => {
    const api = await import('../services/api')
    vi.mocked(api.startAgoraSession).mockResolvedValue(session())
    vi.mocked(api.endAgoraSession).mockResolvedValue({ ...session().session, status: 'ENDED' })

    render(<AgoraControls incidentId="inc-1" />)
    fireEvent.click(screen.getByTestId('btn-agora-start'))
    await screen.findByTestId('btn-agora-end')

    fireEvent.click(screen.getByTestId('btn-agora-end'))

    await waitFor(() => {
      expect(screen.getByTestId('btn-agora-start')).toBeInTheDocument()
    })
    expect(api.endAgoraSession).toHaveBeenCalledWith('inc-1', 'sess-1')
  })
})
