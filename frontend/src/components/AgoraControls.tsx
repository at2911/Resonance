import { useState } from 'react'
import { ApiError, endAgoraSession, startAgoraSession } from '../services/api'
import type { StartSessionResponse } from '../types/api'

/** Starts/stops a real Agora Conversational AI session for this incident.
 * ASR/LLM/TTS config is built entirely server-side (app/services/agora/
 * agent_config.py) — no secret ever passes through this component or the
 * network to the browser beyond the RTC token, which is meant to be
 * shared with whoever is joining the call.
 *
 * This does NOT embed an audio/RTC call UI — joining the returned channel
 * requires an Agora-compatible client (Agora's own web demo, Studio's
 * test-call feature, or a mobile/web app using the Agora SDK). Building
 * that client is out of scope here; this component's job is only to
 * start the agent and hand over what's needed to join it. */
export function AgoraControls({ incidentId }: { incidentId: string }) {
  const [session, setSession] = useState<StartSessionResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleStart() {
    setBusy(true)
    setError(null)
    try {
      const result = await startAgoraSession(incidentId)
      setSession(result)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not reach the backend')
    } finally {
      setBusy(false)
    }
  }

  async function handleEnd() {
    if (!session) return
    setBusy(true)
    setError(null)
    try {
      await endAgoraSession(incidentId, session.session.id)
      setSession(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not reach the backend')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div className="panel" data-testid="agora-controls">
      <h2>AI Incident Commander (Agora)</h2>
      <div className="body">
        {!session ? (
          <>
            <button className="btn" disabled={busy} onClick={handleStart} data-testid="btn-agora-start">
              {busy ? 'Starting…' : '🎙 Start AI Incident Commander'}
            </button>
            <div style={{ color: 'var(--dim)', fontSize: 11, marginTop: 6 }}>
              Starts a real Agora Conversational AI agent for this incident. Requires
              AGORA_* and GEMINI_API_KEY configured on the backend.
            </div>
          </>
        ) : (
          <>
            <div style={{ fontSize: 12.5, lineHeight: 1.7 }}>
              <div>
                Status: <span className="status-chip" data-testid="agora-session-status">{session.session.status}</span>
              </div>
              <div>
                Channel: <code data-testid="agora-channel">{session.session.channel}</code>
              </div>
              {session.session.agent_id && <div>Agent ID: <code>{session.session.agent_id}</code></div>}
            </div>
            <div style={{ marginTop: 8 }}>
              <div style={{ color: 'var(--dim)', fontSize: 11 }}>
                Join this channel from an Agora-compatible client (e.g. Agora's web demo or Studio
                test call) using the channel name above and this token:
              </div>
              <textarea
                readOnly
                value={session.rtc_token}
                data-testid="agora-rtc-token"
                style={{
                  width: '100%',
                  marginTop: 4,
                  background: 'var(--panel2)',
                  border: '1px solid var(--border)',
                  color: 'var(--text)',
                  borderRadius: 6,
                  padding: 6,
                  fontSize: 10.5,
                  fontFamily: 'monospace',
                  resize: 'vertical',
                }}
                rows={2}
              />
            </div>
            <button className="btn reject small" style={{ marginTop: 8 }} disabled={busy} onClick={handleEnd} data-testid="btn-agora-end">
              End Session
            </button>
          </>
        )}
        {error && <div style={{ color: 'var(--critical)', fontSize: 12.5, marginTop: 6 }}>{error}</div>}
      </div>
    </div>
  )
}
