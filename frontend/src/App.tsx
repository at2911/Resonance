import { useState } from 'react'
import { Dashboard } from './pages/Dashboard'
import { ApiError, createIncident } from './services/api'
import type { IncidentSeverity } from './types/api'

const SEVERITIES: IncidentSeverity[] = ['SEV1', 'SEV2', 'SEV3', 'SEV4', 'UNKNOWN']

function CreateIncidentScreen({ onCreated }: { onCreated: (id: string) => void }) {
  const [title, setTitle] = useState('Payment API Outage')
  const [severity, setSeverity] = useState<IncidentSeverity>('SEV1')
  const [busy, setBusy] = useState(false)
  const [error, setError] = useState<string | null>(null)

  async function handleCreate() {
    setBusy(true)
    setError(null)
    try {
      const incident = await createIncident({ title, severity })
      onCreated(incident.id)
    } catch (e) {
      setError(e instanceof ApiError ? e.message : 'Could not reach the backend')
    } finally {
      setBusy(false)
    }
  }

  return (
    <div style={{ maxWidth: 420, margin: '80px auto', padding: 20 }}>
      <h1 style={{ fontSize: 18 }}>🛰 Resonance — Incident Commander</h1>
      <p style={{ color: 'var(--dim)', fontSize: 13 }}>Start a new incident to open the live dashboard.</p>
      <div style={{ display: 'flex', flexDirection: 'column', gap: 10, marginTop: 16 }}>
        <input
          value={title}
          onChange={(e) => setTitle(e.target.value)}
          placeholder="Incident title"
          style={{ background: 'var(--panel2)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 6, padding: '8px 10px' }}
        />
        <select
          value={severity}
          onChange={(e) => setSeverity(e.target.value as IncidentSeverity)}
          style={{ background: 'var(--panel2)', border: '1px solid var(--border)', color: 'var(--text)', borderRadius: 6, padding: '8px 10px' }}
        >
          {SEVERITIES.map((s) => (
            <option key={s} value={s}>
              {s}
            </option>
          ))}
        </select>
        <button className="btn" disabled={busy || !title.trim()} onClick={handleCreate} data-testid="btn-create-incident">
          {busy ? 'Creating…' : 'Create Incident'}
        </button>
        {error && <div style={{ color: 'var(--critical)', fontSize: 12.5 }}>{error}</div>}
      </div>
    </div>
  )
}

export default function App() {
  const [incidentId, setIncidentId] = useState<string | null>(null)
  return incidentId ? <Dashboard incidentId={incidentId} /> : <CreateIncidentScreen onCreated={setIncidentId} />
}
