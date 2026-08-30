import { useEffect, useRef, useState } from 'react'
import { getDemoStatus, pauseDemo, resetDemo, resumeDemo } from '../services/api'
import type { DemoStatus } from '../types/api'

const POLL_INTERVAL_MS = 800

interface Props {
  onReset: () => void
}

/** Polling this (GET /demo/status) is what actually advances backend
 * playback — see backend/app/services/demo/service.py. Start/Pause/Resume/
 * Reset here are explicit, human-triggered POSTs; nothing here ever
 * touches the Slack approval gate — that stays exactly the ApprovalModal
 * flow the rest of the dashboard already uses. */
export function DemoControls({ onReset }: Props) {
  const [status, setStatus] = useState<DemoStatus | null>(null)
  const [busy, setBusy] = useState(false)
  const inFlight = useRef(false)

  useEffect(() => {
    let cancelled = false

    async function poll() {
      if (inFlight.current) return
      inFlight.current = true
      try {
        const s = await getDemoStatus()
        if (!cancelled) setStatus(s)
      } catch {
        // transient network hiccup — next poll retries, no need to surface it
      } finally {
        inFlight.current = false
      }
    }

    void poll()
    const timer = setInterval(() => void poll(), POLL_INTERVAL_MS)
    return () => {
      cancelled = true
      clearInterval(timer)
    }
  }, [])

  async function handlePause() {
    setBusy(true)
    try {
      setStatus(await pauseDemo())
    } finally {
      setBusy(false)
    }
  }

  async function handleResume() {
    setBusy(true)
    try {
      setStatus(await resumeDemo())
    } finally {
      setBusy(false)
    }
  }

  async function handleReset() {
    setBusy(true)
    try {
      await resetDemo()
      onReset()
    } finally {
      setBusy(false)
    }
  }

  if (!status) return null

  return (
    <div
      data-testid="demo-controls"
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 12,
        padding: '8px 20px',
        background: '#0f1a2b',
        borderBottom: '1px solid var(--accent)',
        fontSize: 12.5,
      }}
    >
      <strong style={{ textTransform: 'uppercase', color: 'var(--accent)', letterSpacing: 0.4 }}>Demo Mode</strong>
      <span className="status-chip" data-testid="demo-status">
        {status.status}
      </span>
      <span style={{ color: 'var(--dim)' }} data-testid="demo-progress">
        Step {status.current_step} / {status.total_steps}
      </span>
      {status.last_step_description && <span data-testid="demo-last-step">{status.last_step_description}</span>}

      <div style={{ marginLeft: 'auto', display: 'flex', gap: 8 }}>
        {status.status === 'PLAYING' && (
          <button className="btn secondary small" disabled={busy} onClick={handlePause} data-testid="btn-demo-pause">
            Pause
          </button>
        )}
        {status.status === 'PAUSED' && (
          <button className="btn small" disabled={busy} onClick={handleResume} data-testid="btn-demo-resume">
            Resume
          </button>
        )}
        <button className="btn reject small" disabled={busy} onClick={handleReset} data-testid="btn-demo-reset">
          Reset
        </button>
      </div>
    </div>
  )
}
