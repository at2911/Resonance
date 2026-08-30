import { fireEvent, render, screen, waitFor } from '@testing-library/react'
import { beforeEach, describe, expect, it, vi } from 'vitest'
import type { DemoStatus } from '../types/api'
import { DemoControls } from './DemoControls'

// A stateful fake of the backend's demo session — proves the component
// reflects whatever DemoService.get_status()/pause()/resume()/reset()
// actually returns, not a client-side notion of demo state.
let session: DemoStatus

function idle(): DemoStatus {
  return { status: 'IDLE', incident_id: null, current_step: 0, total_steps: 9, last_step_description: null }
}

vi.mock('../services/api', () => ({
  getDemoStatus: vi.fn(async () => session),
  pauseDemo: vi.fn(async () => {
    session = { ...session, status: 'PAUSED' }
    return session
  }),
  resumeDemo: vi.fn(async () => {
    session = { ...session, status: 'PLAYING' }
    return session
  }),
  resetDemo: vi.fn(async () => {
    session = idle()
    return session
  }),
}))

beforeEach(() => {
  session = {
    status: 'PLAYING',
    incident_id: 'inc-demo-1',
    current_step: 3,
    total_steps: 9,
    last_step_description: 'SRE raises network hypothesis',
  }
  vi.clearAllMocks()
})

describe('DemoControls', () => {
  it('renders nothing until the first status poll resolves', () => {
    const { container } = render(<DemoControls onReset={vi.fn()} />)
    expect(container.firstChild).toBeNull()
  })

  it('shows status, progress, and the last step description once loaded', async () => {
    render(<DemoControls onReset={vi.fn()} />)
    expect(await screen.findByTestId('demo-status')).toHaveTextContent('PLAYING')
    expect(screen.getByTestId('demo-progress')).toHaveTextContent('Step 3 / 9')
    expect(screen.getByTestId('demo-last-step')).toHaveTextContent('SRE raises network hypothesis')
  })

  it('shows Pause (not Resume) while PLAYING', async () => {
    render(<DemoControls onReset={vi.fn()} />)
    await screen.findByTestId('demo-status')
    expect(screen.getByTestId('btn-demo-pause')).toBeInTheDocument()
    expect(screen.queryByTestId('btn-demo-resume')).not.toBeInTheDocument()
  })

  it('clicking Pause calls the backend and flips the displayed status to PAUSED', async () => {
    render(<DemoControls onReset={vi.fn()} />)
    await screen.findByTestId('demo-status')

    fireEvent.click(screen.getByTestId('btn-demo-pause'))

    await waitFor(() => {
      expect(screen.getByTestId('demo-status')).toHaveTextContent('PAUSED')
    })
    expect(screen.getByTestId('btn-demo-resume')).toBeInTheDocument()
    expect(screen.queryByTestId('btn-demo-pause')).not.toBeInTheDocument()
  })

  it('clicking Resume after Pause calls the backend and flips back to PLAYING', async () => {
    render(<DemoControls onReset={vi.fn()} />)
    await screen.findByTestId('demo-status')
    fireEvent.click(screen.getByTestId('btn-demo-pause'))
    await screen.findByTestId('btn-demo-resume')

    fireEvent.click(screen.getByTestId('btn-demo-resume'))

    await waitFor(() => {
      expect(screen.getByTestId('demo-status')).toHaveTextContent('PLAYING')
    })
    expect(screen.getByTestId('btn-demo-pause')).toBeInTheDocument()
  })

  it('clicking Reset calls the backend reset and invokes onReset', async () => {
    const onReset = vi.fn()
    render(<DemoControls onReset={onReset} />)
    await screen.findByTestId('demo-status')

    fireEvent.click(screen.getByTestId('btn-demo-reset'))

    await waitFor(() => {
      expect(onReset).toHaveBeenCalledTimes(1)
    })
  })

  it('Reset is always available regardless of PLAYING/PAUSED status', async () => {
    render(<DemoControls onReset={vi.fn()} />)
    await screen.findByTestId('demo-status')
    expect(screen.getByTestId('btn-demo-reset')).toBeInTheDocument()

    fireEvent.click(screen.getByTestId('btn-demo-pause'))
    await screen.findByTestId('btn-demo-resume')
    expect(screen.getByTestId('btn-demo-reset')).toBeInTheDocument()
  })
})
