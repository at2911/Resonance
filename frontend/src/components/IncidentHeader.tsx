import type { Incident } from '../types/api'

function elapsed(startIso: string): string {
  const ms = Date.now() - new Date(startIso).getTime()
  const mins = Math.max(0, Math.floor(ms / 60000))
  const h = Math.floor(mins / 60)
  const m = mins % 60
  return h > 0 ? `${h}h ${m}m` : `${m}m`
}

export function IncidentHeader({ incident }: { incident: Incident }) {
  return (
    <header
      style={{
        display: 'flex',
        alignItems: 'center',
        gap: 16,
        padding: '14px 20px',
        background: 'var(--panel)',
        borderBottom: '1px solid var(--border)',
        flexWrap: 'wrap',
      }}
    >
      <h1 style={{ fontSize: 16, margin: 0 }}>{incident.title.toUpperCase()}</h1>
      <span className={`badge status-${incident.status}`} data-testid="incident-status">
        {incident.status}
      </span>
      <span className={`badge sev-${incident.severity}`} data-testid="incident-severity">
        {incident.severity}
      </span>
      <span style={{ color: 'var(--dim)', fontSize: 12 }} data-testid="incident-elapsed">
        started {elapsed(incident.start_time)} ago
      </span>
    </header>
  )
}
