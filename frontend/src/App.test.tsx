import { fireEvent, render, screen } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import App from './App'

vi.mock('./pages/Dashboard', () => ({
  Dashboard: ({ incidentId }: { incidentId: string }) => <div data-testid="fake-dashboard">dashboard for {incidentId}</div>,
}))

vi.mock('./services/api', () => ({
  ApiError: class ApiError extends Error {
    status: number
    constructor(status: number, message: string) {
      super(message)
      this.status = status
    }
  },
  createIncident: vi.fn(),
  startDemo: vi.fn(),
}))

beforeEach(() => {
  vi.clearAllMocks()
  window.history.replaceState(null, '', '/')
})

describe('App — shareable per-incident URLs (the "team call" fix)', () => {
  it('with no ?incident= in the URL, shows the start screen', () => {
    render(<App />)
    expect(screen.getByTestId('btn-create-incident')).toBeInTheDocument()
  })

  it('with ?incident=<id> already in the URL, a teammate lands directly on that dashboard, not the start screen', () => {
    window.history.replaceState(null, '', '/?incident=shared-abc123')
    render(<App />)
    expect(screen.getByTestId('fake-dashboard')).toHaveTextContent('shared-abc123')
    expect(screen.queryByTestId('btn-create-incident')).not.toBeInTheDocument()
  })

  it('creating an incident writes its id into the URL, so the address bar becomes the shareable link', async () => {
    const api = await import('./services/api')
    vi.mocked(api.createIncident).mockResolvedValue({ id: 'new-incident-42' } as any)

    render(<App />)
    fireEvent.click(screen.getByTestId('btn-create-incident'))

    await screen.findByTestId('fake-dashboard')
    expect(window.location.search).toBe('?incident=new-incident-42')
  })

  it('running the demo also writes its incident id into the URL', async () => {
    const api = await import('./services/api')
    vi.mocked(api.startDemo).mockResolvedValue({ incident_id: 'demo-incident-7' } as any)

    render(<App />)
    fireEvent.click(screen.getByTestId('btn-run-demo'))

    await screen.findByTestId('fake-dashboard')
    expect(window.location.search).toBe('?incident=demo-incident-7')
  })
})
