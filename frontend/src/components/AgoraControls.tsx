import { useRef, useState } from 'react'
import { ApiError, endAgoraSession, speakAgoraSummary, startAgoraSession } from '../services/api'
import type { StartSessionResponse } from '../types/api'

// Loaded globally by index.html (AgoraRTC_N-4.24.8.js) — not an npm
// import, so it's declared ambient here rather than typed properly.
declare const AgoraRTC: any

/** Starts/stops a real Agora Conversational AI session for this incident,
 * AND lets a real human join that same voice channel directly from this
 * panel — using the real Agora Web SDK (rtc mode, the correct mode for a
 * two-way conversation, not "live"/broadcast mode), not a separate
 * external client or a manually copy-pasted token. ASR/LLM/TTS config is
 * built entirely server-side (app/services/agora/agent_config.py); the
 * only thing that reaches the browser is the RTC token and App ID, both
 * meant to be used by whoever is joining the call — the App ID
 * specifically is not a secret, unlike AGORA_APP_CERTIFICATE/
 * CUSTOMER_SECRET, which never leave the backend. */
export function AgoraControls({ incidentId }: { incidentId: string }) {
  const [session, setSession] = useState<StartSessionResponse | null>(null)
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)
  const [spokenText, setSpokenText] = useState<string | null>(null)
  const [joined, setJoined] = useState(false)
  const [muted, setMuted] = useState(false)

  const clientRef = useRef<any>(null)
  const trackRef = useRef<any>(null)

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

  async function leaveCallIfJoined() {
    if (!joined) return
    try {
      if (trackRef.current) {
        trackRef.current.close()
        trackRef.current = null
      }
      if (clientRef.current) {
        await clientRef.current.leave()
      }
    } finally {
      setJoined(false)
      setMuted(false)
    }
  }

  async function handleEnd() {
    if (!session) return
    setBusy(true)
    setError(null)
    try {
      await leaveCallIfJoined()
      await endAgoraSession(incidentId, session.session.id)
      setSession(null)
      setSpokenText(null)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not reach the backend')
    } finally {
      setBusy(false)
    }
  }

  async function handleSpeak() {
    if (!session) return
    setBusy(true)
    setError(null)
    try {
      const result = await speakAgoraSummary(incidentId, session.session.id)
      setSpokenText(result.spoken_text)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not reach the backend')
    } finally {
      setBusy(false)
    }
  }

  async function handleJoinCall() {
    if (!session) return
    if (typeof AgoraRTC === 'undefined') {
      setError('Voice SDK failed to load — check your connection and reload the page.')
      return
    }
    setBusy(true)
    setError(null)
    try {
      const client = AgoraRTC.createClient({ mode: 'rtc', codec: 'vp8' })
      client.on('user-published', async (user: any, mediaType: string) => {
        if (mediaType === 'audio') {
          await client.subscribe(user, mediaType)
          user.audioTrack.play()
        }
      })
      clientRef.current = client

      const uid = Math.floor(Math.random() * 90000) + 10000
      await client.join(session.app_id, session.session.channel, session.rtc_token, uid)

      const track = await AgoraRTC.createMicrophoneAudioTrack()
      trackRef.current = track
      await client.publish([track])

      setJoined(true)
    } catch (e) {
      setError(e instanceof Error ? `Could not join the call: ${e.message}` : 'Could not join the call')
    } finally {
      setBusy(false)
    }
  }

  async function handleLeaveCall() {
    setBusy(true)
    setError(null)
    try {
      await leaveCallIfJoined()
    } catch (e) {
      setError(e instanceof Error ? e.message : 'Could not leave the call')
    } finally {
      setBusy(false)
    }
  }

  function handleToggleMute() {
    if (!trackRef.current) return
    const next = !muted
    trackRef.current.setEnabled(!next)
    setMuted(next)
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
                {joined && (
                  <span className="status-chip" style={{ marginLeft: 6, background: '#12331f', color: 'var(--fact)' }} data-testid="agora-call-connected">
                    🎙 You're connected
                  </span>
                )}
              </div>
              <div>
                Channel: <code data-testid="agora-channel">{session.session.channel}</code>
              </div>
              {session.session.agent_id && <div>Agent ID: <code>{session.session.agent_id}</code></div>}
            </div>

            <div style={{ marginTop: 10, display: 'flex', gap: 8, flexWrap: 'wrap' }}>
              {!joined ? (
                <button className="btn" disabled={busy} onClick={handleJoinCall} data-testid="btn-agora-join-call">
                  {busy ? 'Joining…' : '🎧 Join Call'}
                </button>
              ) : (
                <>
                  <button className="btn secondary small" disabled={busy} onClick={handleToggleMute} data-testid="btn-agora-mute">
                    {muted ? '🔇 Unmute' : '🎤 Mute'}
                  </button>
                  <button className="btn reject small" disabled={busy} onClick={handleLeaveCall} data-testid="btn-agora-leave-call">
                    Leave Call
                  </button>
                </>
              )}
              <button className="btn secondary small" disabled={busy} onClick={handleSpeak} data-testid="btn-agora-speak-summary">
                🔊 Speak Summary
              </button>
              <button className="btn reject small" disabled={busy} onClick={handleEnd} data-testid="btn-agora-end">
                End Session
              </button>
            </div>

            {!joined && (
              <div style={{ color: 'var(--dim)', fontSize: 11, marginTop: 6 }}>
                Click Join Call to talk to the AI incident commander directly from this browser —
                it'll ask for microphone access.
              </div>
            )}

            {spokenText && (
              <div className="evidence" style={{ marginTop: 6 }} data-testid="agora-spoken-text">
                Asked the agent to say: “{spokenText}”
              </div>
            )}
          </>
        )}
        {error && <div style={{ color: 'var(--critical)', fontSize: 12.5, marginTop: 6 }}>{error}</div>}
      </div>
    </div>
  )
}
