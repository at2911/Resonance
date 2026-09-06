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
  speakAgoraSummary: vi.fn(),
  getCurrentAgoraSession: vi.fn(),
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
    app_id: 'fake-app-id',
  }
}

// jsdom has no real WebRTC/microphone — AgoraRTC is loaded globally by
// index.html in the real app, so tests stand in a minimal fake matching
// the same shape (createClient/join/publish/createMicrophoneAudioTrack)
// AgoraControls actually calls, at the same boundary voice-test-client.html
// was manually verified against.
function installFakeAgoraRTC() {
  const client = {
    on: vi.fn(),
    join: vi.fn().mockResolvedValue(undefined),
    publish: vi.fn().mockResolvedValue(undefined),
    leave: vi.fn().mockResolvedValue(undefined),
    subscribe: vi.fn().mockResolvedValue(undefined),
  }
  const track = { close: vi.fn(), setEnabled: vi.fn() }
  ;(globalThis as any).AgoraRTC = {
    createClient: vi.fn(() => client),
    createMicrophoneAudioTrack: vi.fn().mockResolvedValue(track),
  }
  return { client, track }
}

beforeEach(async () => {
  vi.clearAllMocks()
  delete (globalThis as any).AgoraRTC
  const api = await import('../services/api')
  vi.mocked(api.getCurrentAgoraSession).mockResolvedValue(null)
})

describe('AgoraControls', () => {
  it('shows the Start button and no session details before a session exists', async () => {
    render(<AgoraControls incidentId="inc-1" />)
    expect(screen.getByTestId('btn-agora-start')).toBeInTheDocument()
    expect(screen.queryByTestId('agora-session-status')).not.toBeInTheDocument()
  })

  it('a teammate opening the shared incident URL discovers an already-active session and sees Join Call directly, not Start', async () => {
    const api = await import('../services/api')
    vi.mocked(api.getCurrentAgoraSession).mockResolvedValue(session())

    render(<AgoraControls incidentId="inc-1" />)

    await waitFor(() => {
      expect(screen.getByTestId('btn-agora-join-call')).toBeInTheDocument()
    })
    expect(screen.getByTestId('agora-channel')).toHaveTextContent('incident-abc123')
    expect(screen.queryByTestId('btn-agora-start')).not.toBeInTheDocument()
    expect(api.startAgoraSession).not.toHaveBeenCalled()
  })

  it('with no active session for this incident, still shows Start (the normal, no-session state)', async () => {
    const api = await import('../services/api')
    vi.mocked(api.getCurrentAgoraSession).mockResolvedValue(null)

    render(<AgoraControls incidentId="inc-1" />)

    await waitFor(() => expect(api.getCurrentAgoraSession).toHaveBeenCalledWith('inc-1'))
    expect(screen.getByTestId('btn-agora-start')).toBeInTheDocument()
  })

  it('starting a session shows the real channel and status, and offers Join Call', async () => {
    const api = await import('../services/api')
    vi.mocked(api.startAgoraSession).mockResolvedValue(session())

    render(<AgoraControls incidentId="inc-1" />)
    fireEvent.click(screen.getByTestId('btn-agora-start'))

    await waitFor(() => {
      expect(screen.getByTestId('agora-session-status')).toHaveTextContent('ACTIVE')
    })
    expect(screen.getByTestId('agora-channel')).toHaveTextContent('incident-abc123')
    expect(screen.getByTestId('btn-agora-join-call')).toBeInTheDocument()
    expect(screen.queryByTestId('btn-agora-start')).not.toBeInTheDocument()
  })

  it('Join Call uses the real session channel/token/app_id to join, then shows Mute and Leave Call', async () => {
    const { client, track } = installFakeAgoraRTC()
    const api = await import('../services/api')
    vi.mocked(api.startAgoraSession).mockResolvedValue(session())

    render(<AgoraControls incidentId="inc-1" />)
    fireEvent.click(screen.getByTestId('btn-agora-start'))
    await screen.findByTestId('btn-agora-join-call')

    fireEvent.click(screen.getByTestId('btn-agora-join-call'))

    await waitFor(() => {
      expect(screen.getByTestId('agora-call-connected')).toBeInTheDocument()
    })
    expect(client.join).toHaveBeenCalledWith('fake-app-id', 'incident-abc123', 'fake-rtc-token-value', expect.any(Number))
    expect(client.publish).toHaveBeenCalledWith([track])
    expect(screen.getByTestId('btn-agora-mute')).toBeInTheDocument()
    expect(screen.getByTestId('btn-agora-leave-call')).toBeInTheDocument()
    expect(screen.queryByTestId('btn-agora-join-call')).not.toBeInTheDocument()
  })

  it('Mute toggles the local track without leaving the call', async () => {
    const { track } = installFakeAgoraRTC()
    const api = await import('../services/api')
    vi.mocked(api.startAgoraSession).mockResolvedValue(session())

    render(<AgoraControls incidentId="inc-1" />)
    fireEvent.click(screen.getByTestId('btn-agora-start'))
    await screen.findByTestId('btn-agora-join-call')
    fireEvent.click(screen.getByTestId('btn-agora-join-call'))
    await screen.findByTestId('btn-agora-mute')

    fireEvent.click(screen.getByTestId('btn-agora-mute'))

    expect(track.setEnabled).toHaveBeenCalledWith(false)
    expect(screen.getByTestId('btn-agora-mute')).toHaveTextContent('Unmute')
    expect(screen.getByTestId('agora-call-connected')).toBeInTheDocument()
  })

  it('Leave Call disconnects but keeps the Agora session itself running', async () => {
    const { client, track } = installFakeAgoraRTC()
    const api = await import('../services/api')
    vi.mocked(api.startAgoraSession).mockResolvedValue(session())

    render(<AgoraControls incidentId="inc-1" />)
    fireEvent.click(screen.getByTestId('btn-agora-start'))
    await screen.findByTestId('btn-agora-join-call')
    fireEvent.click(screen.getByTestId('btn-agora-join-call'))
    await screen.findByTestId('btn-agora-leave-call')

    fireEvent.click(screen.getByTestId('btn-agora-leave-call'))

    await waitFor(() => {
      expect(screen.getByTestId('btn-agora-join-call')).toBeInTheDocument()
    })
    expect(track.close).toHaveBeenCalled()
    expect(client.leave).toHaveBeenCalled()
    expect(screen.getByTestId('agora-session-status')).toHaveTextContent('ACTIVE')
    expect(api.endAgoraSession).not.toHaveBeenCalled()
  })

  it('refuses to hand the SDK a missing app_id and shows a clear message instead of crashing', async () => {
    installFakeAgoraRTC()
    const api = await import('../services/api')
    vi.mocked(api.startAgoraSession).mockResolvedValue({ ...session(), app_id: '' })

    render(<AgoraControls incidentId="inc-1" />)
    fireEvent.click(screen.getByTestId('btn-agora-start'))
    await screen.findByTestId('btn-agora-join-call')

    fireEvent.click(screen.getByTestId('btn-agora-join-call'))

    await waitFor(() => {
      expect(screen.getByText(/missing what it needs to join/)).toBeInTheDocument()
    })
    expect(screen.queryByTestId('agora-call-connected')).not.toBeInTheDocument()
  })

  it('surfaces a real join failure (e.g. mic permission denied) instead of pretending it connected', async () => {
    const { client } = installFakeAgoraRTC()
    client.join.mockRejectedValue(new Error('Permission denied'))
    const api = await import('../services/api')
    vi.mocked(api.startAgoraSession).mockResolvedValue(session())

    render(<AgoraControls incidentId="inc-1" />)
    fireEvent.click(screen.getByTestId('btn-agora-start'))
    await screen.findByTestId('btn-agora-join-call')

    fireEvent.click(screen.getByTestId('btn-agora-join-call'))

    await waitFor(() => {
      expect(screen.getByText(/Could not join the call/)).toBeInTheDocument()
    })
    expect(screen.getByTestId('btn-agora-join-call')).toBeInTheDocument()
    expect(screen.queryByTestId('agora-call-connected')).not.toBeInTheDocument()
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

  it('Speak Summary calls the backend and shows the real spoken text it returned', async () => {
    const api = await import('../services/api')
    vi.mocked(api.startAgoraSession).mockResolvedValue(session())
    vi.mocked(api.speakAgoraSummary).mockResolvedValue({ spoken_text: 'Incident: Payment API Outage. No facts have been confirmed yet.' })

    render(<AgoraControls incidentId="inc-1" />)
    fireEvent.click(screen.getByTestId('btn-agora-start'))
    await screen.findByTestId('btn-agora-speak-summary')

    fireEvent.click(screen.getByTestId('btn-agora-speak-summary'))

    await waitFor(() => {
      expect(screen.getByTestId('agora-spoken-text')).toHaveTextContent('No facts have been confirmed yet')
    })
    expect(api.speakAgoraSummary).toHaveBeenCalledWith('inc-1', 'sess-1')
  })

  it('surfaces a real backend error from Speak Summary (e.g. session not active) instead of pretending it worked', async () => {
    const api = await import('../services/api')
    const { ApiError } = api
    vi.mocked(api.startAgoraSession).mockResolvedValue(session())
    vi.mocked(api.speakAgoraSummary).mockRejectedValue(new ApiError(409, 'Agora session sess-1 cannot speak right now: status is ENDED, not ACTIVE'))

    render(<AgoraControls incidentId="inc-1" />)
    fireEvent.click(screen.getByTestId('btn-agora-start'))
    await screen.findByTestId('btn-agora-speak-summary')

    fireEvent.click(screen.getByTestId('btn-agora-speak-summary'))

    await waitFor(() => {
      expect(screen.getByText(/cannot speak right now/)).toBeInTheDocument()
    })
    expect(screen.queryByTestId('agora-spoken-text')).not.toBeInTheDocument()
  })
})
